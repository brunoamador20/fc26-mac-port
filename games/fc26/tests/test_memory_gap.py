"""Synthetic test for memory_gap_find:
Tests finding the inaccessible host gap between known memory regions.
Proves:
1. Ordered regions with address between two regions
2. Unordered regions with address between two regions
3. Address between distant regions
4. Address above all regions (size = 0 - base)
5. Address below all regions (base = 0)
6. Address exactly at the end boundary of a region
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class TestMemoryGap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')

        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmp_dir.name) / 'memory_gap_test'

        cmd = [
            compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
            f'-I{HERE / "runtime"}',
            str(HERE / 'tests/memory_gap_test.c'),
            str(HERE / 'runtime/memory_gap.c'),
            '-o', str(cls.exe)
        ]
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            raise RuntimeError(f'Compilation failed:\n{build.stderr}')

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_case(self, case_name):
        run = subprocess.run([str(self.exe), case_name], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, f'Case {case_name} failed:\nSTDOUT: {run.stdout}\nSTDERR: {run.stderr}')
        self.assertIn(f'PASS {case_name}', run.stdout)

    def test_ordered_regions(self):
        self.run_case('ordered')

    def test_unordered_regions(self):
        self.run_case('unordered')

    def test_address_between_regions(self):
        self.run_case('between')

    def test_above_all_regions(self):
        self.run_case('above_all')

    def test_below_all_regions(self):
        self.run_case('below_all')

    def test_at_end_of_region(self):
        self.run_case('at_end')


if __name__ == '__main__':
    unittest.main()
