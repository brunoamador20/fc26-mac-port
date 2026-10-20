"""build_app.py's mod/overlay helpers: the build merges a mod's main patches, chains its heap table into the 2K overlay,
and refuses a mod file the app replaces itself (the game would stop with "two overlays replace the same file")."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_app             # noqa: E402

HEAPDEF = build_app.HEAPDEF


class ModOverlays(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = self.root/'work/totk'
        self.mod = self.root/'The Second Quest 1.4.3'
        (self.mod/'exefs').mkdir(parents=True)
        (self.mod/'romfs').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def overlay(self, folder, *paths):
        directory = self.tree/f'extracted/v143/{folder}'
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256\n'
                                              + ''.join(f'{p}\t1\t00\t01\n' for p in paths))

    def mod_romfs(self, *paths):
        for path in paths:
            file = self.mod/'romfs'/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'x')

    def test_a_mod_without_a_heap_table_has_nothing_to_chain(self):
        self.assertIsNone(build_app.mod_heapdef(None))
        self.assertIsNone(build_app.mod_heapdef(self.mod))

    def test_the_mods_heap_table_is_found(self):
        self.mod_romfs(HEAPDEF)
        self.assertEqual(build_app.mod_heapdef(self.mod), self.mod/'romfs'/HEAPDEF)

    def test_the_heap_table_is_chained_not_a_clash(self):
        self.mod_romfs(HEAPDEF, 'Banc/MainField/A-1_Dynamic.bcett.byml.zs')
        self.overlay('romfs-patches', 'UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs')
        self.overlay('romfs-patches-out/2560x1440', HEAPDEF)
        build_app.check_mod_overlays(self.tree, self.mod, 'v143')      # no exception

    def test_a_mod_file_the_app_replaces_is_named_not_refused(self):
        self.mod_romfs('UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs')
        self.overlay('romfs-patches', 'UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs')
        sayings = []
        build_app.say = sayings.append
        clashes = build_app.check_mod_overlays(self.tree, self.mod, 'v143')
        self.assertEqual(clashes, ['UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs'])
        self.assertIn('a player\'s manifest leaves it out', sayings[0])

    def test_a_mod_without_romfs_is_not_checked(self):
        build_app.check_mod_overlays(self.tree, None, 'v143')
        (self.mod/'romfs').rmdir()
        build_app.check_mod_overlays(self.tree, self.mod, 'v143')


if __name__ == '__main__':
    unittest.main()
