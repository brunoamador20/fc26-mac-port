"""Compile the actual optional clock probe; never substitute a fake implementation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
class TimeProbeTest(unittest.TestCase):
    def test_disabled_and_real_tick_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'probe'
            build=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',str(HERE/'tests/time_probe_test.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            env=dict(os.environ);env.pop('FC26_TIME_PROFILE',None)
            run=subprocess.run([str(exe)],env=env,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stderr,'')
            env['FC26_TIME_PROFILE']='1'
            run=subprocess.run([str(exe),'on'],env=env,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('hardware-main:n=1,v=1280000,d=640000,ms=33.333333',run.stderr)
            self.assertIn('host-vblank:n=1,v=4,d=2,ms=33.333333',run.stderr)
