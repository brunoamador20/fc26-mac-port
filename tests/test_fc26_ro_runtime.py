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
                  patched_size=len(patched), gate0_ret=int(gates[0].split()[0], 0), gate0_arg=int(gates[0].split()[2]),
                  gate_svc_ret=next(int(g.split()[0], 0) for g in gates if g.split()[1] == 'svc'),
                  gate_timer_ret=next(int(g.split()[0], 0) for g in gates if g.split()[1] == 'cntpct'))
    (directory / 'expect.txt').write_text(''.join(f'{k} {v:#x}\n' for k, v in values.items()))
    # A module without TLS for the host link (caminho B), and one the NRR allows but that has no rewritten image.
    notls = synth.make_nro(module_id=bytes(range(0x40, 0x54)) + bytes(12), tlsdesc=False)
    (directory / 'notls.nro').write_bytes(notls)
    synth.fake_rewrite(notls, directory, 'notls')
    tool.register(directory / 'notls.nro', directory, 'notls')
    (directory / 'notls.nrr').write_bytes(synth.make_nrr([hashlib.sha256(notls).digest()]))
    stranger = synth.make_nro(module_id=bytes(range(0x60, 0x74)) + bytes(12))
    (directory / 'stranger.nro').write_bytes(stranger)
    (directory / 'stranger.nrr').write_bytes(synth.make_nrr([hashlib.sha256(stranger).digest(), digest]))
    return nro, patched


def runtime_tree(directory):
    """runtime/ro next to the runtime.h and ipc.h it includes: FC 26's own once story 2 has made them, else the kit's
    (games/by3, which FC 26's runtime is a copy of), and a game_version.h with FC 26's program id (and a version folder:
    ro_module.c's default image folder is rewritten/<TOTK_GAME_DIR>)."""
    tree = directory / 'rt/runtime'
    shutil.copytree(RO, tree / 'ro')
    for header in ('runtime.h', 'ipc.h'):
        own = ROOT / 'games/fc26/runtime' / header
        shutil.copy(own if own.exists() else ROOT / 'games/by3/runtime' / header, tree / header)
    (tree / 'game_version.h').write_text(f'#pragma once\n#define GAME_TITLE_ID {synth.FC26_PROGRAM_ID:#x}ULL\n'
                                         '#define TOTK_GAME_DIR "vtest"\n')
    return tree


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


class Service(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('cc')
        if not cls.compiler: raise unittest.SkipTest('A C compiler is required')
        cls.temp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.temp.name)
        write_fixture(cls.dir)
        tree = runtime_tree(cls.dir)
        cls.exe = cls.dir / 'service'
        sources = [ROOT / 'tests/fc26_ro_service_test.c'] + [tree / 'ro' / f for f in ('ro_core.c', 'ro_sha256.c', 'ro_module.c', 'ro_service.c')]
        made = build(cls.compiler, sources, cls.exe, [tree])
        if made.returncode: raise AssertionError(made.stdout + made.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_mode(self, mode, directory, **env):
        import os
        return subprocess.run([str(self.exe), mode, str(directory)], capture_output=True, text=True, env=dict(os.environ, **env))

    def test_flow(self):
        run = self.run_mode('flow', self.dir)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('ro service ok', run.stdout)
        self.assertIn('[fc26-ro] mapped m at', run.stderr)
        self.assertIn('linked by the host: relative=5 symbolic=6 cross=4 weak_zero=1', run.stderr)

    def test_authorized_module_without_image_stops(self):
        run = self.run_mode('missing', self.dir)
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        self.assertIn('has no rewritten image', run.stderr)
        self.assertIn(hashlib.sha256((self.dir / 'stranger.nro').read_bytes()).hexdigest(), run.stderr)

    def test_probe_lists_imports_as_the_host_would_link_them(self):
        import json
        run = self.run_mode('probe', self.dir)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        rows = {r['module']: r for r in map(json.loads, run.stdout.splitlines())}
        self.assertEqual(set(rows), {'m', 'notls'})
        m = rows['m']
        self.assertEqual((m['status'], m['imports'], m['relative'], m['symbolic'], m['gates']), ('pass', 5, 5, 6, 2))
        self.assertEqual((m['overridden'], m['missing'], m['weak_missing']), (['__cxa_guard_acquire'], [], ['weak_optional_hook']))
        self.assertEqual(m['tlsdesc'], ['(local)', 'nro_tls_var'])
        self.assertEqual(rows['notls']['tlsdesc'], [])
        hidden = self.run_mode('probe', self.dir, TEST_HIDE_SYMBOL='pthread_mutex_lock')
        self.assertEqual(hidden.returncode, 1, hidden.stdout + hidden.stderr)
        self.assertEqual([json.loads(l)['missing'] for l in hidden.stdout.splitlines()], [['pthread_mutex_lock']] * 2)

    def test_image_that_does_not_match_the_manifest_stops(self):
        tampered = self.dir / 'tampered'
        shutil.copytree(self.dir, tampered, ignore=shutil.ignore_patterns('rt', 'service*', 'tampered'))
        image = bytearray((tampered / 'm.patched.bin').read_bytes()); image[0x4010] ^= 1
        (tampered / 'm.patched.bin').write_bytes(image)
        run = self.run_mode('tampered', tampered, FC26_RO_DIR=str(tampered))
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        self.assertIn('SHA-256 differs', run.stderr)

    def test_late_slots_relinked_and_unmap_clears(self):
        with tempfile.TemporaryDirectory() as temp:
            late_dir = Path(temp)
            late_symbols = [
                ('late_var0', 1, 1, 0x8280),
                ('late_var1', 1, 1, 0x8288),
            ]
            late = synth.make_nro(module_id=bytes(range(0x70, 0x84)) + bytes(12), extra_symbols=late_symbols)
            (late_dir / 'late.nro').write_bytes(late)
            synth.fake_rewrite(late, late_dir, 'late')
            tool.register(late_dir / 'late.nro', late_dir, 'late')
            digest = hashlib.sha256(late).digest()
            (late_dir / 'late.nrr').write_bytes(synth.make_nrr([digest]))
            values = dict(bss_size=synth.BSS_SIZE, late_var0=0x8280, late_var1=0x8288)
            (late_dir / 'expect.txt').write_text(''.join(f'{k} {v:#x}\n' for k, v in values.items()))

            run = subprocess.run([str(self.exe), 'late', str(late_dir)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, f'late slots test failed:\n{run.stderr}\n{run.stdout}')
            self.assertIn('[fc26-ro] late slot late_var0 -> late+0x8280', run.stderr)
            self.assertIn('[fc26-ro] late slot late_var1 -> late+0x8288', run.stderr)
            self.assertIn('late slots relinked', run.stderr)
            self.assertIn('late slots cleared', run.stderr)

    def test_late_slot_unexported_symbol_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            late_dir = Path(temp)
            late_symbols = [
                ('late_var0', 1, 1, 0x8280),
                ('late_var1', 1, 1, 0x8288),
            ]
            late = synth.make_nro(module_id=bytes(range(0x70, 0x84)) + bytes(12), extra_symbols=late_symbols)
            (late_dir / 'late.nro').write_bytes(late)
            synth.fake_rewrite(late, late_dir, 'late')
            tool.register(late_dir / 'late.nro', late_dir, 'late')
            digest = hashlib.sha256(late).digest()
            (late_dir / 'late.nrr').write_bytes(synth.make_nrr([digest]))
            values = dict(bss_size=synth.BSS_SIZE, late_var0=0x8280, late_var1=0x8288)
            (late_dir / 'expect.txt').write_text(''.join(f'{k} {v:#x}\n' for k, v in values.items()))

            run = subprocess.run([str(self.exe), 'late_missing', str(late_dir)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 3, f'late missing test failed:\n{run.stderr}\n{run.stdout}')
            self.assertIn('[fc26-missing]', run.stderr)
            self.assertIn('nonexistent_late_symbol', run.stderr)


if __name__ == '__main__':
    unittest.main()
