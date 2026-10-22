"""A repackaged app keeps the game data file of the app it replaces when the data is the same: the image keeps its inode
and times, so the runtime's RomFS verification record (runtime/romfs.c) still matches and the first start after a
packaging does not hash 16 GB again."""
import os
from pathlib import Path
import tempfile
import unittest
import build_app

IMAGE = 'Contents/Resources/romfs.bin'


def data_bundle(app, name='GameData-v143.bundle', seal=b'seal', data=b'romfs'):
    bundle = app/'Contents/Helpers'/name
    (bundle/'Contents/_CodeSignature').mkdir(parents=True)
    (bundle/'Contents/_CodeSignature/CodeResources').write_bytes(seal)
    (bundle/'Contents/Info.plist').write_bytes(b'plist')
    (bundle/'Contents/Resources').mkdir()
    (bundle/IMAGE).write_bytes(data)
    return bundle


def identity(path):
    s = os.stat(path)
    return s.st_ino, s.st_mtime_ns, s.st_ctime_ns, s.st_birthtime


class KeepGameData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old, self.new = self.root/'Game.app', self.root/'Game.app.partial'

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_same_data_keeps_the_old_image(self):
        before = identity(data_bundle(self.old)/IMAGE)
        fresh = data_bundle(self.new)
        # When the seal is checked, the app holds the kept bundle and nothing else (a fresh copy set aside inside it is
        # an unsealed resource: codesign --strict refused the first version this way).
        sealed = lambda app: sorted(p.name for p in (app/'Contents/Helpers').iterdir()) == ['GameData-v143.bundle']
        self.assertTrue(build_app.keep_game_data(self.new, self.old, verify=sealed))
        self.assertEqual(identity(fresh/IMAGE), before)
        self.assertEqual(sorted(p.name for p in (self.new/'Contents/Helpers').iterdir()), ['GameData-v143.bundle'])

    def test_other_data_is_not_kept(self):
        for change in [dict(seal=b'another seal'), dict(data=b'romfs, longer')]:
            with self.subTest(change=change):
                old_image = data_bundle(self.old, **change)/IMAGE
                fresh = data_bundle(self.new)
                own = identity(fresh/IMAGE)
                self.assertFalse(build_app.keep_game_data(self.new, self.old, verify=lambda app: True))
                self.assertEqual(identity(fresh/IMAGE), own)
                self.assertTrue(old_image.is_file())
                build_app.remove_tree(self.old); build_app.remove_tree(self.new)

    def test_no_app_to_replace(self):
        data_bundle(self.new)
        self.assertFalse(build_app.keep_game_data(self.new, self.old, verify=lambda app: True))

    def test_a_seal_that_no_longer_verifies_puts_the_fresh_copy_back(self):
        old_image = data_bundle(self.old)/IMAGE
        fresh = data_bundle(self.new, data=b'romfs')
        own = identity(fresh/IMAGE)
        self.assertFalse(build_app.keep_game_data(self.new, self.old, verify=lambda app: False))
        self.assertEqual(identity(fresh/IMAGE), own)
        self.assertTrue(old_image.is_file())


class InstallApp(unittest.TestCase):
    """The new app's seal is checked once (by keep_game_data when it keeps the data, else here), before the installed app
    is touched; the replaced app is renamed aside and removed in the background."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out, self.new = self.root/'Game.app', self.root/'Game.app.partial'
        self.removed, self.checked = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, result=True):
        verify = lambda app: self.checked.append(app) or result
        return build_app.install_app(self.new, self.out, verify=verify, remove=self.removed.append)

    def test_kept_data_checks_the_seal_once(self):
        data_bundle(self.out); data_bundle(self.new)
        self.assertTrue(self.install())
        self.assertEqual(len(self.checked), 1)
        self.assertFalse(self.new.exists())
        self.assertEqual([p.name for p in self.removed], [f'Game.app.replaced-{os.getpid()}'])
        self.assertFalse(self.removed[0].name.endswith('.app'))   # not an app to Launch Services while it is deleted

    def test_other_data_checks_the_seal_once_and_replaces(self):
        data_bundle(self.out, seal=b'another seal'); data_bundle(self.new)
        self.assertFalse(self.install())
        self.assertEqual(len(self.checked), 1)
        self.assertEqual((self.out/'Contents/Helpers/GameData-v143.bundle/Contents/_CodeSignature/CodeResources').read_bytes(), b'seal')

    def test_first_install(self):
        data_bundle(self.new)
        self.assertFalse(self.install())
        self.assertEqual((len(self.checked), self.removed), (1, []))
        self.assertTrue(self.out.is_dir())

    def test_a_seal_that_does_not_verify_leaves_the_installed_app(self):
        old_image = data_bundle(self.out, seal=b'another seal')/IMAGE
        data_bundle(self.new)
        with self.assertRaises(build_app.BuildError):
            self.install(result=False)
        self.assertTrue(old_image.is_file())
        self.assertEqual(self.removed, [])

    def test_the_installed_app_folder_stays_and_takes_the_new_contents(self):
        # macOS keeps its first-run check of an app (Gatekeeper / XProtect, 185-200 s for the 17 GB bundle) with the .app
        # folder: a new folder with the same contents is scanned again, new Contents in the same folder are not
        # (2026-10-22). So the folder stays and only Contents is replaced.
        data_bundle(self.out, seal=b'another seal'); data_bundle(self.new)
        (self.new/'Contents/Info.plist').write_bytes(b'new app')
        folder = os.stat(self.out).st_ino
        self.install()
        self.assertEqual(os.stat(self.out).st_ino, folder)
        self.assertEqual((self.out/'Contents/Info.plist').read_bytes(), b'new app')
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['Contents'])
        old = self.removed[0]
        self.assertEqual((old/'Contents/Helpers/GameData-v143.bundle/Contents/_CodeSignature/CodeResources').read_bytes(),
                         b'another seal')   # the replaced contents, outside the app, are what is removed

    def test_leftovers_of_an_earlier_install_are_removed_too(self):
        (self.root/'Game.app.replaced-1').mkdir()
        data_bundle(self.new)
        self.install()
        self.assertEqual([p.name for p in self.removed], ['Game.app.replaced-1'])


if __name__ == '__main__':
    unittest.main()
