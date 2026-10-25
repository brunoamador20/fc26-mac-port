"""Exercise the FC 26 present-interval override compiled from real code."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class ForcePresentIntervalTest(unittest.TestCase):
    def test_fc26_interval_2_is_ignored_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'interval'
            build = subprocess.run(
                ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-I' + str(HERE / 'third_party/d2r_gfx/gfx/nvn'),
                 str(HERE / 'tests/fc26_force_present_interval_test.c'),
                 '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)

            env = dict(os.environ)
            env.pop('FC26_FORCE_PRESENT_INTERVAL', None)
            self.assertEqual(
                subprocess.run([str(exe)], capture_output=True, text=True,
                               env=env, timeout=10).returncode, 0)

            env['FC26_FORCE_PRESENT_INTERVAL'] = '1'
            self.assertEqual(
                subprocess.run([str(exe)], capture_output=True, text=True,
                               env=env, timeout=10).returncode, 0)


if __name__ == '__main__':
    unittest.main()
