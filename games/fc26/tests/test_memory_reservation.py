"""Real macOS address reservations through the runtime's memory_init."""
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]
@unittest.skipUnless(platform.system() == 'Darwin', 'macOS Mach address space')
class MemoryReservation(unittest.TestCase):
    def test_free_gap_between_legacy_search_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'reservation'
            build = subprocess.run(['xcrun','clang','-std=gnu11','-O2','-Wall','-Wextra',
                '-ffunction-sections','-Wl,-dead_strip',
                '-I'+str(HERE/'runtime'), '-I'+str(HERE/'third_party/d2r_gfx/gfx/nvn/include'),
                str(HERE/'tests/memory_reservation_test.c'), '-framework','CoreFoundation',
                '-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for args in ([], ['default-alias']):
                with self.subTest(alias='pinned 8 GiB' if not args else 'default 64..8 GiB'):
                    run = subprocess.run([str(exe), *args],capture_output=True,text=True,timeout=15)
                    if run.returncode == 77:
                        self.skipTest(run.stderr)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertIn('PASS: real reservation',run.stderr)
                    print(run.stderr, end='')
if __name__ == '__main__':
    unittest.main()
