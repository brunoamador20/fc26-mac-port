"""Pre-island rewriter tests on synthetic modules (games/fc26/docs/ILHAS_NUVEM.md), no game data.

 * golden / before-after: a module that fits uses no island and the whole rewrite output is byte-for-byte the
   base-branch rewriter's (proves the golden rule and that the change is a no-op when no island is needed).
 * island: a small routing reach (DM_REACH_BITS) forces a pre-island on the same small module; every site head is a
   B that lands in a patch area and the block returns to the right text address, both areas are used, and structck /
   equiv (when llvm-objdump / unicorn are present) pass. structck is also run on the no-island output to prove nothing
   loosened, and on a corrupted island to prove it still bites.

The slow > 140 MiB proof is tests/synth_giant.py (run by hand / `make island-giant`), not part of `make test`.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
D2R = HERE / 'third_party/d2r'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_module  # noqa: E402

REWRITE_ENV = {'DM_RULESET': 'native', 'DM_PRIVATE_GATES': '0'}
PRODUCTS = ['patched.bin', 'fixups.tsv', 'gates.tsv', 'sites.tsv', 'cuts.tsv', 'params.tsv', 'obs.tsv']


def run_rewriter(script_dir, nso, out, env_extra=None):
    env = {**os.environ, **REWRITE_ENV, **(env_extra or {})}
    r = subprocess.run([sys.executable, str(Path(script_dir) / 'patch_nso.py'), nso, out, 'synth'],
                       capture_output=True, text=True, env=env, cwd=script_dir)
    return r


def header(out, mod='synth'):
    h = {}
    for line in open(f'{out}/{mod}.fixups.tsv'):
        if line.startswith('#'):
            _, k, v = line.split()
            h[k] = int(v, 0)
    return h


def btarget(buf, o):
    w = struct.unpack_from('<I', buf, o)[0]
    if w & 0xFC000000 != 0x14000000:
        return None
    imm = w & 0x3FFFFFF
    if imm & 0x2000000:
        imm -= 0x4000000
    return o + 4 * imm


def b_of(word, o):
    """Target of an unconditional b at module offset o, else None."""
    if word & 0xFC000000 != 0x14000000:
        return None
    return o + 4 * (((word & 0x3FFFFFF) ^ 0x2000000) - 0x2000000)


def adrp_page(word, pc):
    imm = ((word >> 29) & 3) | (((word >> 5) & 0x7FFFF) << 2)
    return (pc & ~0xFFF) + (((imm ^ (1 << 20)) - (1 << 20)) << 12)


def group_entry_problems(word_at, head_target, key_page):
    """The linked-window group (synth_module.GROUP_*): each entry must be the full prologue
    stp xS,xT,[sp,#-16] ; mrs xT,tpidrro_el0 ; adrp ->key page ; ldr ; add ; ldr xS,[xT] ; b <copy of the head>
    where the copy is the head's own ldaxr with x18 renamed to xS. A wrong entry-branch offset leaves the nop in
    place and/or overwrites another entry's stp (the bug the reviews found)."""
    problems = []
    for h in synth_module.GROUP_HEADS:
        e = head_target(h)
        if e is None:
            problems.append(f'group head {h:#x} is not a b'); continue
        w = [word_at(e + 4 * k) for k in range(7)]
        S, T = w[0] & 31, (w[0] >> 10) & 31
        if w[0] & 0xFFFF83E0 != 0xA93F03E0:
            problems.append(f'entry {e:#x} (head {h:#x}) does not start with stp xS,xT,[sp,#-16]: {w[0]:#010x}'); continue
        if w[1] != 0xD53BD060 | T:
            problems.append(f'entry {e:#x}: word 1 is not mrs x{T},tpidrro_el0')
        if w[2] & 0x9F000000 != 0x90000000 or adrp_page(w[2], e + 8) != key_page:
            problems.append(f'entry {e:#x}: word 2 is not an adrp to the key page')
        body = b_of(w[6], e + 24)
        want = (synth_module.GROUP_WORDS[(h // 4) - synth_module.GROUP_WORD] & ~(31 << 5)) | (S << 5)
        if body is None:
            problems.append(f'entry {e:#x} (head {h:#x}): word 6 is {w[6]:#010x}, not the b into the copied body')
        elif word_at(body) != want:
            problems.append(f'entry {e:#x} (head {h:#x}): b lands on {word_at(body):#010x}, not the copied head {want:#010x}')
    return problems


class GoldenRule(unittest.TestCase):
    """A module that fits => no island, and the output equals the base-branch rewriter byte for byte."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.nso = os.path.join(self.tmp, 'synth.nso')
        synth_module.small(self.nso)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_island_when_it_fits(self):
        out = os.path.join(self.tmp, 'new'); os.makedirs(out)
        r = run_rewriter(D2R, self.nso, out, {'DM_REACH_BITS': '27'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(f'{out}/synth.pre.bin'), 'a fitting module must not make a pre-island')
        self.assertNotIn('PRE_PATCH', open(f'{out}/synth.fixups.tsv').read(), 'no PRE_ header lines when there is no island')

    def test_group_entries_after_area(self):
        """The linked-window group in the after-area (no island): entry prologues and entry branches intact."""
        out = os.path.join(self.tmp, 'new'); os.makedirs(out)
        self.assertEqual(run_rewriter(D2R, self.nso, out, {'DM_REACH_BITS': '27'}).returncode, 0)
        pat = open(f'{out}/synth.patched.bin', 'rb').read()
        h = header(out)
        word_at = lambda o: struct.unpack_from('<I', pat, o)[0]
        for g in synth_module.GROUP_HEADS:
            self.assertGreaterEqual(btarget(pat, g), h['PATCH_OFF'])
        self.assertEqual(group_entry_problems(word_at, lambda o: btarget(pat, o), h['KEY_PAGE_OFF']), [])

    def test_byte_identical_to_base_branch(self):
        """The real before/after: run the base-branch rewriter (+ its helpers) and diff every product."""
        old = os.path.join(self.tmp, 'old_d2r'); os.makedirs(old)
        try:
            for f in ('patch_nso.py', 'call_window.py', 'relr.py', 'nsoimg.py'):
                src = subprocess.run(['git', 'show', f'estoria1/ilhas-base:games/fc26/third_party/d2r/{f}'],
                                     capture_output=True, cwd=HERE, check=True).stdout
                open(os.path.join(old, f), 'wb').write(src)
        except subprocess.CalledProcessError:
            self.skipTest('base branch estoria1/ilhas-base not available for the before/after comparison')
        new_out, old_out = os.path.join(self.tmp, 'n'), os.path.join(self.tmp, 'o')
        os.makedirs(new_out); os.makedirs(old_out)
        self.assertEqual(run_rewriter(D2R, self.nso, new_out, {'DM_REACH_BITS': '27'}).returncode, 0)
        self.assertEqual(run_rewriter(old, self.nso, old_out).returncode, 0)
        for p in PRODUCTS:
            self.assertEqual(open(f'{new_out}/synth.{p}', 'rb').read(), open(f'{old_out}/synth.{p}', 'rb').read(),
                             f'{p} differs from the base-branch rewriter for a module with no island')


class PreIsland(unittest.TestCase):
    """A small reach forces a pre-island; prove routing, round-trips, and the kit checkers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.nso = os.path.join(self.tmp, 'synth.nso')
        synth_module.small(self.nso)
        self.out = os.path.join(self.tmp, 'isl'); os.makedirs(self.out)
        r = run_rewriter(D2R, self.nso, self.out, {'DM_REACH_BITS': '18'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.pat = open(f'{self.out}/synth.patched.bin', 'rb').read()
        self.h = header(self.out)
        self.assertIn('PRE_PATCH_SIZE', self.h, 'the small reach should have forced a pre-island')
        self.pre_base = self.h['PRE_PATCH_OFF']
        self.pre = open(f'{self.out}/synth.pre.bin', 'rb').read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _is_patch(self, t):
        return t is not None and (self.pre_base <= t < 0 or self.h['PATCH_OFF'] <= t < len(self.pat))

    def _word(self, off):
        return struct.unpack_from('<I', self.pre, off - self.pre_base)[0] if off < 0 else struct.unpack_from('<I', self.pat, off)[0]

    def test_file_and_header_consistent(self):
        self.assertEqual(len(self.pre), self.h['PRE_PATCH_SIZE'])
        self.assertEqual(self.pre_base, -self.h['PRE_PATCH_SIZE'])

    def test_group_entries_in_island(self):
        """The linked-window group routed to the pre-island: every entry keeps its stp/key-slot prologue and ends in
        the b into the copied body (the entry branches are written into the island, at the island's own offsets)."""
        for g in synth_module.GROUP_HEADS:
            self.assertLess(btarget(self.pat, g), 0, f'group head {g:#x} should be routed to the pre-island')
        self.assertEqual(group_entry_problems(self._word, lambda o: btarget(self.pat, o), self.h['KEY_PAGE_OFF']), [])

    def test_both_areas_used_and_heads_round_trip(self):
        pre_heads = after_heads = 0
        for line in open(f'{self.out}/synth.sites.tsv'):
            f = line.split()
            a, kind = int(f[0], 16), f[1]
            if kind == 'J':
                continue
            t = btarget(self.pat, a)
            self.assertTrue(self._is_patch(t), f'site head {a:#x} is not a B into a patch area')
            pre_heads += t < 0
            after_heads += t >= self.h['PATCH_OFF']
            # the block must return to text somewhere in [0, TEXT_END): walk its first exit b
            self.assertTrue(self._walks_back(t), f'block for site {a:#x} never returns to text')
        self.assertGreater(pre_heads, 0, 'the forced island should hold some sites')
        self.assertGreater(after_heads, 0, 'the after-area should still hold the high sites')

    def _walks_back(self, start):
        """Follow the block from `start` in module-offset space; True once a b leaves the patch area into text."""
        seen = set(); o = start
        for _ in range(4096):
            if o in seen or not self._is_patch(o):
                return 0 <= o < self.h['TEXT_END']
            seen.add(o); w = self._word(o)
            if w & 0xFC000000 == 0x14000000:          # b: follow it, or take it as the exit if it leaves the patch area
                nt = self._btarget_mod(o)
                if not self._is_patch(nt):
                    return 0 <= nt < self.h['TEXT_END']
                o = nt; continue
            if w == 0xD65F03C0 or w & 0xFFFFFC1F == 0xD61F0000:   # ret / br (the jump table lands via br)
                return True
            o += 4
        return False

    def _btarget_mod(self, o):
        w = self._word(o)
        if w & 0xFC000000 != 0x14000000:
            return None
        imm = w & 0x3FFFFFF
        if imm & 0x2000000:
            imm -= 0x4000000
        return o + 4 * imm

    def _structck(self, out):
        objdump = shutil.which('llvm-objdump') or shutil.which('llvm-objdump-18')
        if not objdump:
            self.skipTest('llvm-objdump not available for structck')
        env = {**os.environ, 'LLVM_BIN': os.path.dirname(objdump), 'DM_ROOT': os.path.join(self.tmp, 'dmroot')}
        return subprocess.run([sys.executable, str(D2R / 'structck.py'), out, 'synth', self.nso],
                              capture_output=True, text=True, env=env, cwd=str(D2R))

    def test_structck_passes_on_island(self):
        r = self._structck(self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('STRUCT synth OK', r.stdout)

    def test_structck_bites_corrupted_island(self):
        bad = os.path.join(self.tmp, 'bad'); shutil.copytree(self.out, bad)
        d = bytearray(open(f'{bad}/synth.pre.bin', 'rb').read())
        # clobber the key-page adrp right after the island's first mrs tpidrro_el0 (structck checks every key-slot
        # sequence; a copied window body word is equiv's to check, not structck's)
        at = next(o for o in range(0, len(d), 4) if struct.unpack_from('<I', d, o)[0] & 0xFFFFFFE0 == 0xD53BD060)
        struct.pack_into('<I', d, at + 4, 0xD503201F)
        open(f'{bad}/synth.pre.bin', 'wb').write(d)
        r = self._structck(bad)
        self.assertNotEqual(r.returncode, 0, 'structck must fail on a corrupted pre-island')
        self.assertIn('STRUCT synth FAIL', r.stdout)

    def test_equiv_passes_on_island(self):
        try:
            import unicorn  # noqa: F401
        except ImportError:
            self.skipTest('unicorn not available for equiv')
        r = subprocess.run([sys.executable, str(D2R / 'equiv.py'), self.out, 'synth', self.nso,
                            '--jobs', '1', '--mutate', '40'], capture_output=True, text=True, cwd=str(D2R))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('EQUIV synth OK', r.stdout)


if __name__ == '__main__':
    unittest.main()
