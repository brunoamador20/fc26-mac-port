from pathlib import Path
import json
import subprocess
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]
class FrameBurst(unittest.TestCase):
    def test_real_metal_readback_keeps_consecutive_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, out = Path(tmp)/'test', Path(tmp)/'seq'
            build = subprocess.run(['xcrun','clang','-Wall','-Wextra','-Werror','-fobjc-arc',
                str(HERE/'tests/frame_burst_test.m'),'-framework','Metal','-framework','Foundation','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(exe),str(out)],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            rows=json.loads(out.with_suffix('.json').read_text())
            self.assertEqual([r['frame'] for r in rows],list(range(100,104)))
            for i,r in enumerate(rows):
                data=Path(f'{out}_{i:02}.raw').read_bytes()
                self.assertEqual(len(data),r['row']*r['height'])
                for y in range(8): self.assertEqual(data[y*r['row']:y*r['row']+32],bytes([i])*32)
