"""csrng answers GenerateRandomBytes (runtime/csrng.c). Career mode opens it through sm when it sets up its first match
(boot car1, 2026-10-23); without the service the runtime stopped with 'IPC service not implemented'.
Built from the real runtime sources (ipc.c, missing.c, csrng.c, and the offline services tests/offline_ipc.c links) with
the same harness as test_offline_services.py; the request is built as the sdk's CMIF client builds it."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

try:
    from test_offline_services import SOURCES, opus_flags          # unittest discover -s tests
except ImportError:
    from tests.test_offline_services import SOURCES, opus_flags

HERE = Path(__file__).resolve().parents[1]


class Csrng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        opus = opus_flags()
        if opus is None:
            raise unittest.SkipTest('libopus is required (tests/offline_ipc.c links hwopus.c)')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'csrng_ipc'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_DEFAULT_SOURCE'])
        build = subprocess.run([compiler, *flags, f'-I{HERE / "runtime"}', *(str(HERE / s) for s in SOURCES + ['runtime/csrng.c']),
                                *opus, '-lpthread', '-lm', '-o', str(cls.exe)], capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_generate_random_bytes(self):
        run = subprocess.run([str(self.exe), 'csrng'], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('ok: csrng GenerateRandomBytes (B buffer): 64 random bytes, two calls differ', run.stdout)

    def test_unknown_command_still_stops_with_name_and_number(self):
        run = subprocess.run([str(self.exe), 'command', 'csrng', '1'], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('[fc26-missing] ipc command: service "csrng" command 1', run.stderr)


if __name__ == '__main__':
    unittest.main()
