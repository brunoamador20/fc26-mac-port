"""Verification and behavioral tests for libc filesystem overrides:
open, fstat, read, lseek, close, stat, write, ftruncate, unlink, mkdir, rmdir.
"""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
if str(HERE / 'tests') not in sys.path:
    sys.path.insert(0, str(HERE / 'tests'))
from test_host_overrides_e5 import extract_dynsym_imports, MAIN_NSO


class TestLibcFsOverrides(unittest.TestCase):
    def test_main_imported_symbols(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        for sym in ['open', 'fstat', 'read', 'lseek', 'close', 'stat',
                    'write', 'ftruncate', 'unlink', 'mkdir', 'rmdir']:
            self.assertIn(sym, imports, f'Expected {sym} to be imported by main')

    def test_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'libc_fs_overrides_test'
            cmd = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                   f'-I{HERE / "runtime"}',
                   str(HERE / 'tests/libc_fs_overrides_test.c'),
                   str(HERE / 'runtime/account.c'),
                   str(HERE / 'runtime/fs_host.c'),
                   str(HERE / 'runtime/missing.c'),
                   '-lpthread',
                   '-o', str(exe)]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'profile'
            prof.mkdir()
            env = dict(platform.os.environ, TOTK_PROFILE_DIR=str(prof))
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Execution failed:\n{run.stderr}')
            self.assertIn('ALL_LIBC_FS_OVERRIDES_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
