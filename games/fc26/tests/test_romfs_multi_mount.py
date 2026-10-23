"""Tests for RomFS multi-mount support in FC 26 runtime.
Proves:
1. Opening "eadpsdk_rom:/X" and "rom:/X" yields identical contents.
2. A third mount name works identically.
3. Unmounted mount name remains outside (owns = 0, open fails).
4. Unmount removes only the target name.
5. Table fullness (8 mounts limit) triggers runtime_fail.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
WORK_ROMFS = (Path.home() / 'fc26-switch/work/extracted/v100/romfs')
WORK_BUILD = (Path.home() / 'fc26-switch/work/build')


class TestRomFsMultiMount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not WORK_ROMFS.exists():
            raise unittest.SkipTest(f'{WORK_ROMFS} does not exist')
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')

        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmp_dir.name) / 'romfs_multi_mount_test'

        cmd = [
            compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
            f'-I{HERE / "runtime"}',
            f'-I{HERE / "third_party/d2r_gfx/gfx/nvn/include"}',
            f'-I{WORK_BUILD}',
            str(HERE / 'tests/romfs_multi_mount_test.c'),
            str(HERE / 'runtime/romfs.c'),
            '-framework', 'CoreFoundation',
            '-lpthread',
            '-o', str(cls.exe)
        ]
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            raise RuntimeError(f'Compilation failed:\n{build.stderr}')

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def test_multi_mount_basic(self):
        env = dict(
            os.environ,
            TOTK_ROMFS=str(WORK_ROMFS),
            TOTK_ROMFS_PATCHES='0',
            TOTK_ROMFS_MODS='0'
        )
        run = subprocess.run([str(self.exe), 'basic'], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, f'Execution failed (rc={run.returncode}):\nSTDOUT: {run.stdout}\nSTDERR: {run.stderr}')
        self.assertIn('ROMFS_MULTI_MOUNT_BASIC_OK', run.stdout)

    def test_multi_mount_table_full(self):
        env = dict(
            os.environ,
            TOTK_ROMFS=str(WORK_ROMFS),
            TOTK_ROMFS_PATCHES='0',
            TOTK_ROMFS_MODS='0'
        )
        run = subprocess.run([str(self.exe), 'full'], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 42, f'Expected rc=42 for table full, got {run.returncode}. Output:\n{run.stderr}')
        self.assertIn('runtime_fail: romfs mount table full', run.stderr)


if __name__ == '__main__':
    unittest.main()
