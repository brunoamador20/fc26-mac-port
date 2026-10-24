"""Exercise the positive SleepThread host wait compiled from real threads.c."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]

class ThreadTimeoutTest(unittest.TestCase):
    def test_timeout_does_not_accumulate_coalescing_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'sleep'
            build = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra',
                '-Werror', '-ffunction-sections', '-Wl,-dead_strip',
                '-I'+str(HERE/'runtime'),
                '-I'+str(HERE/'third_party/d2r_gfx/gfx/nvn/include'),
                str(HERE/'tests/thread_timeout_test.c'), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ)
            env.pop('TOTK_LISTCHECK', None)
            env.pop('TOTK_DUMP_AFTER', None)
            env.pop('TOTK_FREE_CORES', None)
            env.pop('FC26_THREAD_PROFILE', None)
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
