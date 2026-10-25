from pathlib import Path
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
class GameplayRead(unittest.TestCase):
    def test_real_reader_is_read_only_and_rejects_invalid_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'read'
            build=subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Werror',str(HERE/'tests/gameplay_read_test.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
