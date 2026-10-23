"""Verification and behavioral tests for the 9 nn::fs host overrides:
nn::fs::DeleteDirectory(const char*)
nn::fs::RenameDirectory(const char*, const char*)
nn::fs::GetFreeSpaceSize(long*, const char*)
nn::fs::MountAddOnContent(const char*, int, void*, unsigned long)
nn::fs::MountCacheStorage(const char*)
nn::fs::GetCacheStorageMax(int*, long*)
nn::fs::GetCacheStorageSize(long*, long*, int)
nn::fs::GetDirectoryEntryCount(long*, nn::fs::DirectoryHandle)
nn::fs::QueryMountAddOnContentCacheSize(unsigned long*, int)
"""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
if str(HERE / 'tests') not in sys.path:
    sys.path.insert(0, str(HERE / 'tests'))
from test_host_overrides_e5 import extract_dynsym_imports, MAIN_NSO


class TestFsOverrides9(unittest.TestCase):
    def test_main_imported_symbols(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        # 1. DeleteDirectory
        self.assertIn('_ZN2nn2fs15DeleteDirectoryEPKc', imports)

        # 2. RenameDirectory
        self.assertIn('_ZN2nn2fs15RenameDirectoryEPKcS2_', imports)

        # 3. GetFreeSpaceSize
        self.assertIn('_ZN2nn2fs16GetFreeSpaceSizeEPlPKc', imports)

        # 4. MountAddOnContent
        self.assertIn('_ZN2nn2fs17MountAddOnContentEPKciPvm', imports)

        # 5. MountCacheStorage (without index)
        self.assertIn('_ZN2nn2fs17MountCacheStorageEPKc', imports)

        # 6. GetCacheStorageMax
        self.assertIn('_ZN2nn2fs18GetCacheStorageMaxEPiPl', imports)

        # 7. GetCacheStorageSize
        self.assertIn('_ZN2nn2fs19GetCacheStorageSizeEPlS1_i', imports)

        # 8. GetDirectoryEntryCount
        self.assertIn('_ZN2nn2fs22GetDirectoryEntryCountEPlNS0_15DirectoryHandleE', imports)

        # 9. QueryMountAddOnContentCacheSize
        self.assertIn('_ZN2nn2fs31QueryMountAddOnContentCacheSizeEPmi', imports)

    def test_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'fs_overrides_9_test'
            cmd = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                   f'-I{HERE / "runtime"}',
                   str(HERE / 'tests/fs_overrides_9_test.c'),
                   str(HERE / 'runtime/account.c'),
                   str(HERE / 'runtime/fs_host.c'),
                   str(HERE / 'runtime/missing.c'),
                   '-lpthread',
                   '-o', str(exe)]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'profile'
            prof.mkdir()
            env = dict(platform.os.environ, TOTK_PROFILE_DIR=str(prof))
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Execution failed:\n{run.stderr}')
            self.assertIn('ALL_FS_OVERRIDES_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
