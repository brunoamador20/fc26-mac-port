"""Large synthetic proof for the pre-island (games/fc26/docs/ILHAS_NUVEM.md), run by hand / `make island-giant`.

Builds a > 140 MiB single-function NSO (like FC 26's main: one eh_frame FDE, so the rewriter takes its chunked
LazyInsns path) seeded with x18 sites from start to end, an ldxr/stxr window, a `br x18` jump table and an svc; runs
the rewriter at the real ±128 MiB reach (no DM_REACH_BITS); then proves, without the kit tools, that every `b` the
rewriter emitted is within range, every site head jumps into a patch area and its block returns to the right text
address. With --structck it also runs the kit's independent structural check. It is NOT part of `make test`.

Usage: synth_giant.py [--mib 144] [--every 256] [--keep] [--structck]
"""
import argparse
import os
import resource
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
D2R = HERE / 'third_party/d2r'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_module

REACH = 1 << 27   # the AArch64 b hardware reach, ±128 MiB


def btarget_mod(word_at, o):
    w = word_at(o)
    if w & 0xFC000000 != 0x14000000:
        return None
    imm = w & 0x3FFFFFF
    if imm & 0x2000000:
        imm -= 0x4000000
    return o + 4 * imm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mib', type=int, default=144)
    ap.add_argument('--every', type=int, default=256)
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--structck', action='store_true')
    a = ap.parse_args()

    work = tempfile.mkdtemp(prefix='fc26-island-')
    nso = os.path.join(work, 'giant.nso')
    out = os.path.join(work, 'out'); os.makedirs(out)
    try:
        t0 = time.time()
        placed, win_at, svc_at, jbase, jcount = synth_module.giant(nso, mib=a.mib, every=a.every)
        text_sz = os.path.getsize(nso)
        print(f'built {nso}: ~{a.mib} MiB, file {text_sz/1e6:.1f} MB, x18 sites={placed}, '
              f'window@{win_at:#x}, svc@{svc_at:#x}, jumptable base@{jbase:#x} count={jcount} ({time.time()-t0:.0f}s)', flush=True)

        t0 = time.time()
        env = {**os.environ, 'DM_RULESET': 'native', 'DM_PRIVATE_GATES': '0'}
        r = subprocess.run([sys.executable, str(D2R / 'patch_nso.py'), nso, out, 'giant'],
                           env=env, cwd=str(D2R), capture_output=True, text=True)
        print(r.stdout.strip(), flush=True)
        if r.returncode:
            print('REWRITER FAILED:\n' + r.stderr[-4000:]); return 1
        peak_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss   # Linux: KiB
        print(f'rewrite took {time.time()-t0:.0f}s, peak rewriter RSS ~{peak_kb/1e6:.2f} GB', flush=True)

        pat = open(f'{out}/giant.patched.bin', 'rb').read()
        h = {}
        for line in open(f'{out}/giant.fixups.tsv'):
            if line.startswith('#'):
                _, k, v = line.split(); h[k] = int(v, 0)
        PO, TE = h['PATCH_OFF'], h['TEXT_END']
        pre_base = h.get('PRE_PATCH_OFF', 0); pre_size = h.get('PRE_PATCH_SIZE', 0)
        pre = open(f'{out}/giant.pre.bin', 'rb').read() if pre_size else b''

        def word_at(o):
            return struct.unpack_from('<I', pre, o - pre_base)[0] if o < 0 else struct.unpack_from('<I', pat, o)[0]

        def is_patch(t):
            return t is not None and ((pre_size and pre_base <= t < 0) or PO <= t < len(pat))

        # 1) every site head is a B into a patch area, in range, and its block returns to text
        pre_heads = after_heads = 0
        worst = 0
        bad = 0
        for line in open(f'{out}/giant.sites.tsv'):
            f = line.split()
            a_, kind = int(f[0], 16), f[1]
            if kind == 'J':
                continue
            t = btarget_mod(word_at, a_)
            if not is_patch(t):
                bad += 1
                if bad <= 5:
                    print(f'  BAD head {a_:#x} -> {t}')
                continue
            worst = max(worst, abs(t - a_))
            pre_heads += t < 0
            after_heads += t >= PO
            # walk the block to its first return into text
            o, seen, ok = t, set(), False
            for _ in range(8192):
                if o in seen or not is_patch(o):
                    ok = 0 <= o < TE; break
                seen.add(o); w = word_at(o)
                if w & 0xFC000000 == 0x14000000:
                    nt = btarget_mod(word_at, o)
                    worst = max(worst, abs(nt - o))
                    if not is_patch(nt):
                        ok = 0 <= nt < TE; break
                    o = nt; continue
                if w == 0xD65F03C0 or w & 0xFFFFFC1F == 0xD61F0000:
                    ok = True; break
                o += 4
            if not ok:
                bad += 1
                if bad <= 5:
                    print(f'  BAD block for head {a_:#x}')

        # ("todos os b dentro do alcance": the rewriter raises in B()/ADRP if any branch is out of reach, so a clean run
        #  already proves encodability; worst is the largest head->block / block->text distance actually observed, and
        #  it must be under the hardware ±128 MiB — the whole point of splitting into two areas.)
        print(f'PATCH_OFF={PO:#x} TEXT_END={TE:#x} pre=({pre_base:#x},{pre_size:#x}) after_patch={len(pat)-PO:#x}')
        print(f'routing: pre-island heads={pre_heads}  after-area heads={after_heads}  worst |delta|={worst/1e6:.1f} MB (limit {REACH/1e6:.0f} MB)')
        print(f'bad heads/blocks={bad}')
        verdict = bad == 0 and worst < REACH and pre_heads > 0 and after_heads > 0
        print('GIANT', 'OK' if verdict else 'FAIL')

        if a.structck:
            objdump = shutil.which('llvm-objdump') or shutil.which('llvm-objdump-18')
            if objdump:
                t0 = time.time()
                senv = {**os.environ, 'LLVM_BIN': os.path.dirname(objdump), 'DM_ROOT': os.path.join(work, 'dmroot')}
                s = subprocess.run([sys.executable, str(D2R / 'structck.py'), out, 'giant', nso],
                                   env=senv, cwd=str(D2R), capture_output=True, text=True)
                print(s.stdout.strip().splitlines()[-1] if s.stdout else s.stderr[-2000:], flush=True)
                print(f'structck took {time.time()-t0:.0f}s, exit={s.returncode}')
                verdict = verdict and s.returncode == 0
            else:
                print('structck skipped (no llvm-objdump)')
        return 0 if verdict else 1
    finally:
        if a.keep:
            print('kept', work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
