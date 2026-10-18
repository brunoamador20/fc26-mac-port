"""Desktop alias and save migration contracts; synthetic user data only."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'games/totk/tools/install_desktop_entry.py'
spec=importlib.util.spec_from_file_location('desktop_entry_installer',SCRIPT)
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DesktopEntryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.app=self.root/'output/Game.app'
        binary=self.app/'Contents/MacOS/TOTK';binary.parent.mkdir(parents=True);binary.write_bytes(b'packaged executable')
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier=installer.BUNDLE_ID,CFBundleExecutable='TOTK',CFBundleShortVersionString='1.4.3')))
        self.desktop=self.root/'Desktop/Game.app';(self.desktop/'Contents').mkdir(parents=True)
        self.legacy=self.root/'old-profile';self.legacy.mkdir();(self.legacy/'progress.sav').write_bytes(b'original progress')
        (self.desktop/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(TOTKProfileDirectory=str(self.legacy))))
        self.data=self.root/'user-support'

    def install(self):
        return installer.install(self.app,self.desktop,self.data,register=False)

    def test_migration_preserves_source_and_sealed_app(self):
        before=installer.manifest(self.app);legacy=installer.manifest(self.legacy)
        result=self.install()
        self.assertTrue(self.desktop.is_symlink());self.assertEqual(self.desktop.resolve(),self.app.resolve())
        self.assertEqual(installer.manifest(self.legacy),legacy)
        self.assertEqual(installer.manifest(self.data/'profile'),legacy)
        self.assertEqual(installer.manifest(self.data/'profile-before-1.4.3'),legacy)
        self.assertEqual(installer.manifest(self.app),before)
        self.assertTrue((Path(result['previous_entry_backup'])/'Contents/Info.plist').is_file())
        self.assertFalse(Path(result['previous_entry_backup']).name.endswith('.app'))

    def test_reinstall_keeps_new_progress_and_one_entry(self):
        self.install();(self.data/'profile/progress.sav').write_bytes(b'new game progress')
        backups=list((self.data/'desktop-entry-backups').iterdir())
        result=self.install()
        self.assertEqual(result['status'],'already-linked')
        self.assertEqual((self.data/'profile/progress.sav').read_bytes(),b'new game progress')
        self.assertEqual(list((self.data/'desktop-entry-backups').iterdir()),backups)
        self.assertEqual(list(self.desktop.parent.iterdir()),[self.desktop])

    def test_conflicting_profile_preserves_both_and_old_entry(self):
        (self.data/'profile').mkdir(parents=True);(self.data/'profile/progress.sav').write_bytes(b'other progress')
        before=installer.manifest(self.desktop)
        with self.assertRaisesRegex(ValueError,'neither was overwritten'):self.install()
        self.assertFalse(self.desktop.is_symlink());self.assertEqual(installer.manifest(self.desktop),before)
        self.assertEqual((self.legacy/'progress.sav').read_bytes(),b'original progress')
        self.assertEqual((self.data/'profile/progress.sav').read_bytes(),b'other progress')

    def test_app_already_on_desktop_is_not_replaced_by_self_link(self):
        result=installer.install(self.app,self.app,self.data,register=False)
        self.assertEqual(result['status'],'already-app');self.assertFalse(self.app.is_symlink())
        self.assertEqual((self.app/'Contents/MacOS/TOTK').read_bytes(),b'packaged executable')


if __name__=='__main__':unittest.main()
