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


if __name__ == '__main__':
    unittest.main()
