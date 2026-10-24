"""FC 26 finds its saves again on the next boot (tests/save_mount_twice_test.c, real runtime/fs_host.c and account.c).
EASaveLoad mounts "save" again for every save folder it lists and needs 0 / 0xe02 / 0x7802 back; with 0x402 the
runtime hid every earlier save (boot car2, 2026-10-23: a new Settings save each boot, no career to load)."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class SaveMountTwice(unittest.TestCase):
    def test_an_earlier_save_is_read_back(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            exe = tmp / 'save_mount_twice_test'
            build = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', f'-I{HERE / "runtime"}',
                                    str(HERE / 'tests/save_mount_twice_test.c'), str(HERE / 'runtime/account.c'),
                                    str(HERE / 'runtime/fs_host.c'), str(HERE / 'runtime/missing.c'), '-lpthread',
                                    '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            profile = tmp / 'profile'
            # Boot 1 only makes the profile (account id, save root); the save folder is what an earlier boot left.
            first = subprocess.run([str(exe), str(profile)], capture_output=True, text=True, timeout=60)
            roots = list((profile / 'save').iterdir())
            self.assertEqual(len(roots), 1, first.stdout + first.stderr)
            folder = roots[0] / '7f9bb0a4'
            folder.mkdir()
            (folder / 'name').write_text('CmMgrC20260923225926')
            (folder / 'INDEX').write_bytes(b'body' + bytes(236))
            (folder / 'DATA').write_bytes(bytes(64))
            run = subprocess.run([str(exe), str(profile)], capture_output=True, text=True, timeout=60)
            self.assertIn('MountSaveData("save") while mounted = 0x7802 (the game goes on to read the name)', run.stdout,
                          run.stdout + run.stderr)
            self.assertIn('save found: CmMgrC20260923225926', run.stdout)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
