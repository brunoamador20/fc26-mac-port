"""Real Metal 4 profiler, including clear-only and depth-only render passes."""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN = HERE / 'third_party/d2r_gfx/gfx/nvn'

class GpuProfilerTest(unittest.TestCase):
    def test_clear_and_draw_timestamps(self):
        if platform.system() != 'Darwin' or not shutil.which('clang'):
            self.skipTest('Metal 4 and clang required')
        with tempfile.TemporaryDirectory() as tmp:
            exe, capture = Path(tmp)/'profiler', Path(tmp)/'capture.tsv'
            build = subprocess.run(['clang', '-fobjc-arc', '-O2', '-Wall', '-Wextra',
                '-Wno-unused-function', '-I'+str(NVN), str(HERE/'tests/gpuprof_test.m'),
                '-framework', 'Foundation', '-framework', 'Metal', '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ, DM_NVN_GPUPROF='0', DM_NVN_GPUPROF_FILE=str(capture))
            run = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=30)
            if run.returncode == 77:
                self.skipTest('No Metal device')
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('4 encoders, dropped 0, invalid 0', run.stderr)
            rows = [line.split('\t') for line in capture.read_text().splitlines()]
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(len(r) == 13 and r[2] == 'R' and float(r[3]) >= 0 for r in rows))
            self.assertEqual([int(r[4]) for r in rows], [0, 1, 1, 1])
            self.assertEqual([int(r[8]) for r in rows], [0, 0, 0, 252])
