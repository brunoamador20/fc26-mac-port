"""Verification and round-trip behavioral tests for save data in FC 26 (Story E4):
- Main NSO symbol verification: MountSaveData, EnsureSaveData, Commit, GetSaveDataSize,
  GetSaveDataSizeMax, ExtendSaveData, IsSaveDataExisting.
- Full round-trip test:
  * MountSaveData("save")
  * CreateDirectory, CreateFile, WriteFile, CloseFile
  * CommitSaveData, Commit
  * Unmount
  * Fresh process execution with persistent profile directory
  * Account UID persistence
  * MountSaveData, OpenFile, ReadFile, byte-for-byte content verification
  * ExtendSaveData within NACP bounds, bounds validation
  * GetFreeSpaceSize
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


class TestSaveRoundtrip(unittest.TestCase):
    def test_main_imported_save_symbols(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        # 1. MountSaveData / MountSaveDataReadOnly
        self.assertIn('_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE', imports)
        self.assertIn('_ZN2nn2fs21MountSaveDataReadOnlyEPKcNS_13ApplicationIdERKNS_7account3UidE', imports)

        # 2. EnsureSaveData
        self.assertIn('_ZN2nn2fs14EnsureSaveDataERKNS_7account3UidE', imports)

        # 3. Commit
        self.assertIn('_ZN2nn2fs6CommitEPKc', imports)

        # 4. GetSaveDataSize / GetSaveDataSizeMax
        self.assertIn('_ZN2nn2fs15GetSaveDataSizeEPlS1_RKNS_7account3UidE', imports)
        self.assertIn('_ZN2nn2fs18GetSaveDataSizeMaxEPlS1_', imports)

        # 5. ExtendSaveData
        self.assertIn('_ZN2nn2fs14ExtendSaveDataERKNS_7account3UidEll', imports)

        # 6. IsSaveDataExisting
        self.assertIn('_ZN2nn2fs18IsSaveDataExistingENS_13ApplicationIdERKNS_7account3UidE', imports)

        # 7. Account symbols used for save data identity
        self.assertIn('_ZN2nn7account10InitializeEv', imports)
        self.assertIn('_ZN2nn7account8OpenUserEPNS0_10UserHandleERKNS0_3UidE', imports)
        self.assertIn('_ZN2nn7account9GetUserIdEPNS0_3UidERKNS0_10UserHandleE', imports)
        self.assertIn('_ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE', imports)

    def test_save_roundtrip_across_boots(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'save_roundtrip_test'
            cmd = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                   f'-I{HERE / "runtime"}',
                   str(HERE / 'tests/save_roundtrip_test.c'),
                   str(HERE / 'runtime/account.c'),
                   str(HERE / 'runtime/fs_host.c'),
                   str(HERE / 'runtime/missing.c'),
                   '-lpthread',
                   '-o', str(exe)]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'user_profile'
            prof.mkdir()
            env = dict(platform.os.environ, TOTK_PROFILE_DIR=str(prof))

            # Boot 1: Write save data, commit, unmount, exit
            run1 = subprocess.run([str(exe), '1'], capture_output=True, text=True, env=env)
            self.assertEqual(run1.returncode, 0, f'Boot 1 (write) failed:\n{run1.stderr}\n{run1.stdout}')
            self.assertIn('PHASE_1_WRITE_OK', run1.stdout)

            # Boot 2: Fresh process, load persistent UID, mount save, verify byte integrity, extend save
            run2 = subprocess.run([str(exe), '2'], capture_output=True, text=True, env=env)
            self.assertEqual(run2.returncode, 0, f'Boot 2 (read & verify) failed:\n{run2.stderr}\n{run2.stdout}')
            self.assertIn('PHASE_2_READ_VERIFY_OK', run2.stdout)


if __name__ == '__main__':
    unittest.main()
