"""FC 26 creates profile files with libc open(path, O_CREAT, mode) (tests/libc_open_mode_test.c, real runtime/fs_host.c).
The Switch ABI passes the mode in w2; the variadic host function read it from the stack, so files got random modes
(040, 0200, 0350, 0 in work/user-data and user-data-carreira, 2026-10-24) and the next boot could not read some."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class LibcOpenMode(unittest.TestCase):
    def test_mode_from_the_register_and_old_files_readable(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            exe = tmp / 'libc_open_mode_test'
            build = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', f'-I{HERE / "runtime"}',
                                    str(HERE / 'tests/libc_open_mode_test.c'), str(HERE / 'runtime/account.c'),
                                    str(HERE / 'runtime/fs_host.c'), str(HERE / 'runtime/missing.c'), '-lpthread',
                                    '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe), str(tmp / 'profile')], capture_output=True, text=True, timeout=60)
            print(run.stdout.strip())
            self.assertIn('created mode 0640', run.stdout, run.stdout + run.stderr)
            self.assertIn('unreadable file: open ok, read "old"', run.stdout, run.stdout + run.stderr)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
