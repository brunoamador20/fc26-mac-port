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
import random
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
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


def adrp_plus_one_page(word):
    imm = (((word >> 29) & 3) | (((word >> 5) & 0x7FFFF) << 2)) + 1
    return (word & 0x9F00001F) | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5)


def enc_b(frm, to):
    return 0x14000000 | (((to - frm) >> 2) & 0x3FFFFFF)


def enc_movz(rd, imm16, hw=0):
    return 0xD2800000 | (hw << 21) | (imm16 << 5) | rd


def enc_movk(rd, imm16, hw):
    return 0xF2800000 | (hw << 21) | (imm16 << 5) | rd


def enc_br(rn):
    return 0xD61F0000 | (rn << 5)


def equiv_globals(out, nso):
    """equiv.py's module namespace for one rewrite output: only its top level runs (run_name is not __main__), so the
    images, sites and helpers (mk / run / plain_block / in_patch ...) are loaded and nothing is emulated yet. The
    returned dict is the one equiv's functions read their globals from."""
    argv = sys.argv
    sys.argv = ['equiv.py', out, 'synth', nso, '--jobs', '1', '--mutate', '0']
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)   # equiv's top level reads its .tsv files without closing them
            ns = runpy.run_path(str(D2R / 'equiv.py'), run_name='equiv_under_test')
    finally:
        sys.argv = argv
    return ns['run'].__globals__


# The PR's base (branch estoria1/ilhas-base): the single-area rewriter and checkers, before the pre-island. Addressed by
# commit so it resolves in any clone of this branch's history, whatever the local branch names are.
BASE_COMMIT = 'cf81fa19039305e6b7e9ab5bdf92d66b356d1a05'
BASE_FILES = ('patch_nso.py', 'call_window.py', 'relr.py', 'nsoimg.py', 'equiv.py', 'structck.py')


def base_d2r(dest):
    """Write the base commit's third_party/d2r tools into dest; False when that commit is not in this clone (a shallow
    checkout, as CI's): the golden rule then falls back to the committed hashes in golden_small.sha256."""
    os.makedirs(dest, exist_ok=True)
    for f in BASE_FILES:
        r = subprocess.run(['git', 'show', f'{BASE_COMMIT}:games/fc26/third_party/d2r/{f}'], capture_output=True, cwd=HERE)
        if r.returncode:
            return False
        Path(dest, f).write_bytes(r.stdout)
    return True


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


class EquivRules(unittest.TestCase):
    """equiv.py, white box: a module with no island is judged exactly as before (only offsets >= PATCH_OFF are patch
    code; the ARENA and the TSD, both mapped below the module base, never are), the pre-island counts only through its
    own range, and plain_block accepts a block only when its adrp lands exactly on the key page."""

    A = 0x100   # a text word of the synthetic module that is a nop and no site / window / call

    @classmethod
    def setUpClass(cls):
        try:
            import unicorn  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('unicorn not available for equiv')
        cls.tmp = tempfile.mkdtemp()
        cls.nso = os.path.join(cls.tmp, 'synth.nso')
        synth_module.small(cls.nso)
        cls.flat, cls.isl = os.path.join(cls.tmp, 'flat'), os.path.join(cls.tmp, 'isl')
        for out, bits in ((cls.flat, '27'), (cls.isl, '18')):
            os.makedirs(out)
            r = run_rewriter(D2R, cls.nso, out, {'DM_REACH_BITS': bits})
            assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _end_pc(self, g, image, pre_img, tsd_code=b''):
        """Run the patched side from text word A in equiv's own emulator; return where equiv's code hook ended it."""
        u, st = g['mk'](bytes(image), bytes(g['ARENA_SZ']), bytes(pre_img))
        if tsd_code:
            u.mem_write(g['TSD'], tsd_code)               # below the TSD key slots (TSD + 8*300 ...)
        init = g['init_state'](random.Random(7), 0)
        return g['run'](u, st, g['IB'] + self.A, True, init)[-1]

    def _tsd_back_to_text(self, g):
        """Code for the TSD page: jump back to text word A+4 (IB + A + 4)."""
        back = g['IB'] + self.A + 4
        return struct.pack('<III', enc_movz(17, back & 0xFFFF), enc_movk(17, back >> 32, 2), enc_br(17))

    def test_hook_no_island_stops_outside_patch(self):
        """No island: a patch block that jumps into the TSD (below IB) leaves patch code there; the run must end at
        the TSD, as before the pre-island change (counting addr < IB as patch let it run on back into text)."""
        g = equiv_globals(self.flat, self.nso)
        self.assertEqual(g['PRE_SIZE'], 0)
        img = bytearray(g['pat'])
        S = (len(img) + 0xF) & ~0xF
        img += bytes(S - len(img)) + struct.pack('<II', enc_movz(16, g['TSD'] >> 16, 1), enc_br(16))
        struct.pack_into('<I', img, self.A, enc_b(self.A, S))
        self.assertEqual(self._end_pc(g, img, b'', self._tsd_back_to_text(g)), g['TSD'])
        for off in (g['ARENA'] - g['IB'], g['TSD'] - g['IB'], -4, g['PATCH_OFF'] - 4):
            self.assertFalse(g['in_patch'](off), f'{off:#x} must not count as patch code without an island')
        self.assertTrue(g['in_patch'](g['PATCH_OFF']))

    def test_hook_island_counts_only_the_island(self):
        g = equiv_globals(self.isl, self.nso)
        PB = g['PRE_BASE']
        self.assertLess(PB, 0)
        img = bytearray(g['pat'])
        struct.pack_into('<I', img, self.A, enc_b(self.A, PB))
        pre_img = bytearray(g['pre'])
        struct.pack_into('<I', pre_img, 0, enc_b(PB, self.A + 4))          # island block straight back to text
        self.assertEqual(self._end_pc(g, img, pre_img), g['IB'] + self.A + 4, 'the pre-island must count as patch code')
        struct.pack_into('<II', pre_img, 0, enc_movz(16, g['TSD'] >> 16, 1), enc_br(16))   # island block -> TSD
        self.assertEqual(self._end_pc(g, img, pre_img, self._tsd_back_to_text(g)), g['TSD'], 'the TSD is not patch code')
        self.assertFalse(g['in_patch'](g['ARENA'] - g['IB']))
        self.assertFalse(g['in_patch'](g['TSD'] - g['IB']))

    def test_plain_block_checks_the_exact_key_page(self):
        """plain_block takes a block only when its adrp (at s+8) lands exactly on KEY_PAGE_OFF: in the after-area as
        before, and in the pre-island at its negative offset. One page off must reject it."""
        cases = 0
        for out in (self.flat, self.isl):
            g = equiv_globals(out, self.nso)
            pat0, pre0 = g['pat'], g['pre']
            by_area = {}
            for a in g['sites']:
                if a in g['winend'] or a in g['brinfo'] or not g['plain_block'](a):
                    continue
                by_area.setdefault(btarget(pat0, a) < 0, a)
            self.assertIn(False, by_area, 'an after-area plain block')
            if out == self.isl:
                self.assertIn(True, by_area, 'a pre-island plain block')
            for in_pre, a in by_area.items():
                s = btarget(pat0, a)
                self.assertEqual(g['plain_block'](a), s + 24)
                if in_pre:
                    buf = bytearray(pre0); i = s + 8 - g['PRE_BASE']
                else:
                    buf = bytearray(pat0); i = s + 8
                struct.pack_into('<I', buf, i, adrp_plus_one_page(struct.unpack_from('<I', buf, i)[0]))
                g['pre' if in_pre else 'pat'] = bytes(buf)
                try:
                    self.assertIsNone(g['plain_block'](a), f'adrp one page off the key page accepted ({out}, site {a:#x})')
                finally:
                    g['pat'], g['pre'] = pat0, pre0
                cases += 1
        self.assertEqual(cases, 3)

    def test_no_island_judged_exactly_as_the_base(self):
        """No island: this equiv and the base commit's print the same report (every DIFF / NOEFF / MUTMISS line and the
        verdict with its trial and mutation counts) for the same output and seed."""
        old = os.path.join(self.tmp, 'base_d2r')
        if not base_d2r(old):
            self.skipTest(f'base commit {BASE_COMMIT[:12]} not in this clone')
        reports = []
        for d in (old, str(D2R)):
            r = subprocess.run([sys.executable, 'equiv.py', self.flat, 'synth', self.nso, '--jobs', '1', '--mutate', '40'],
                               capture_output=True, text=True, cwd=d)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            reports.append(r.stdout.splitlines())
        self.assertIn('EQUIV synth OK', reports[1][-1])
        self.assertEqual(reports[1], reports[0])

    def test_jobs_1_runs_without_a_process_pool(self):
        """--jobs 1 runs every job in this one process (a multiprocessing Pool is forbidden) and frees each job's
        emulators before the next: the whole run on the island output stays far under the 1.28 GB it reached when
        they piled up (2.69 GB on main, where every emulator maps the whole image)."""
        code = ('import multiprocessing.pool, resource, runpy, sys\n'
                'def no_pool(*a, **k): raise SystemExit("equiv --jobs 1 created a multiprocessing Pool")\n'
                'multiprocessing.pool.Pool.__init__ = no_pool\n'
                f'sys.argv = ["equiv.py", {self.isl!r}, "synth", {self.nso!r}, "--jobs", "1", "--mutate", "6"]\n'
                'try:\n'
                f'    runpy.run_path({str(D2R / "equiv.py")!r}, run_name="__main__")\n'
                'finally:\n'
                '    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n'
                '    print("PEAK_MIB", peak // (1 << 20) if sys.platform == "darwin" else peak // 1024)\n')
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(D2R))
        self.assertIn('EQUIV synth OK', r.stdout, r.stdout[-2000:] + r.stderr[-2000:])
        peak = int(r.stdout.split('PEAK_MIB')[1].split()[0])
        self.assertLess(peak, 600, f'equiv --jobs 1 peaked at {peak} MiB')


if __name__ == '__main__':
    unittest.main()
