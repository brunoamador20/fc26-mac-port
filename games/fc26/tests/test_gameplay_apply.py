from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]

class GameplayApply(unittest.TestCase):
    def test_real_writer_applies_reapplies_and_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'apply'
            build=subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function',
                str(HERE/'tests/gameplay_apply_test.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)

if __name__=='__main__':
    unittest.main()
