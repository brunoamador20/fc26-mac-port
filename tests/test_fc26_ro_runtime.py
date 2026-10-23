"""FC 26 nn::ro runtime (games/fc26/runtime/ro) built with the host C compiler and run on synthetic files.

The core (ro_core.c, ro_sha256.c) is plain C and runs as is. The service and the mapper (ro_service.c, ro_module.c)
are built against the kit's runtime.h / ipc.h with stand-ins for the rest of the runtime (tests/fc26_ro_service_test.c):
the whole ldr:ro flow runs, mapping included, on Linux and on macOS."""
from pathlib import Path
import hashlib
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RO = ROOT / 'games/fc26/runtime/ro'
sys.path.insert(0, str(ROOT / 'games/fc26/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc26_synth as synth
import nro_to_nso as tool


def write_fixture(directory, nro=None, name='m'):
    """Synthetic NRO, NRRs, a rewrite with patch_nso.py's layout, its manifest row and the values the C side expects."""
    nro = nro or synth.make_nro()
    digest = hashlib.sha256(nro).digest()
    (directory / f'{name}.nro').write_bytes(nro)
    others = synth.other_hashes(5)
    (directory / 'user.nrr').write_bytes(synth.make_nrr(others + [digest]))
    (directory / 'jit.nrr').write_bytes(synth.make_nrr(others + [digest], kind=1))
    (directory / 'other_program.nrr').write_bytes(synth.make_nrr([digest], program_id=synth.FC26_PROGRAM_ID + 1))
    (directory / 'without.nrr').write_bytes(synth.make_nrr(others))
    unsorted = bytearray(synth.make_nrr(others))
    unsorted[0x350:0x370], unsorted[0x370:0x390] = unsorted[0x370:0x390], unsorted[0x350:0x370]
    (directory / 'unsorted.nrr').write_bytes(unsorted)
    patched, gates = synth.fake_rewrite(nro, directory, name)
    tool.register(directory / f'{name}.nro', directory, name)
    layout = tool.read_layout(directory / f'{name}.fixups.tsv')
    sym = {n: i + 1 for i, (n, *_) in enumerate(synth.SYMBOLS)}
    values = dict(nrr_hashes=6, program_id=synth.FC26_PROGRAM_ID, nro_size=synth.NRO_SIZE, bss_size=synth.BSS_SIZE,
                  ro=synth.RO, data=synth.DATA, mod0=synth.MOD0, key_off=layout['KEY_PAGE_OFF'], patch_off=layout['PATCH_OFF'],
                  gates=len(gates), nsym=len(synth.SYMBOLS) + 1, init=0x140, init_array=synth.INIT_ARRAY,
                  sym_nro_export_fn=sym['nro_export_fn'], export_fn=0x130, relr=len(synth.RELR_TARGETS), far=synth.FAR,
                  g_abs_import=synth.G_ABS_IMPORT, g_abs_local=synth.G_ABS_LOCAL, export_data=synth.EXPORT_DATA,
                  g_glob=synth.G_GLOB, g_weak=synth.G_WEAK, g_jump0=synth.G_JUMP0, g_jump1=synth.G_JUMP1,
                  g_tls_local=synth.G_TLS_LOCAL, g_tls_sym=synth.G_TLS_SYM, tls_value=0x8,
                  patched_size=len(patched), gate0_ret=int(gates[0].split()[0], 0), gate0_arg=int(gates[0].split()[2]))
    (directory / 'expect.txt').write_text(''.join(f'{k} {v:#x}\n' for k, v in values.items()))
    return nro, patched


def build(compiler, sources, output, include):
    """Strict warnings, sanitizers where the platform has them (UBSan only on macOS: ASan hangs there, see tests.yml)."""
    sanitize = ['-fsanitize=undefined'] if platform.system() == 'Darwin' else ['-fsanitize=address,undefined']
    base = [compiler, '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-D_DEFAULT_SOURCE',
            *[f'-I{i}' for i in include], *map(str, sources), '-o', str(output), '-lpthread']
    run = subprocess.run(base[:1] + sanitize + ['-fno-sanitize-recover=all'] + base[1:], capture_output=True, text=True)
    if run.returncode:   # a toolchain without sanitizer runtimes still builds the plain test
        run = subprocess.run(base, capture_output=True, text=True)
    return run


class Core(unittest.TestCase):
    def test_core(self):
        compiler = shutil.which('cc')
        if not compiler: self.skipTest('A C compiler is required')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            write_fixture(directory)
            exe = directory / 'core'
            made = build(compiler, [ROOT / 'tests/fc26_ro_core_test.c', RO / 'ro_core.c', RO / 'ro_sha256.c'], exe, [RO])
            self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
            run = subprocess.run([str(exe), str(directory)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('ro core ok', run.stdout)


if __name__ == '__main__':
    unittest.main()
