"""build_app.py's mod helpers: the build merges a mod's main patches, chains its heap table into the 2K overlay, names a
mod file the app replaces itself, and at the end copies the mod's RomFS files into the player's mod folder and writes
its manifest (scripts/make_mod_manifest.py, run for real against a small fake RomFS)."""
import struct
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


ROMFS_FILES = {'Pack/A.pack.zs': b'original a', 'Sound/B.bwav': b'original b'}


def fake_romfs(folder):
    """romfs.bin and runtime-index.bin in the layout scripts/prepare_romfs_backend.py writes."""
    image, rows, strings = bytearray(), bytearray(), bytearray()
    for path in sorted(ROMFS_FILES):
        name = path.encode() + b'\0'
        rows += struct.pack('<QQII', len(image), len(ROMFS_FILES[path]), len(strings), len(name))
        image += ROMFS_FILES[path]
        strings += name
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'romfs.bin').write_bytes(image)
    (folder/'runtime-index.bin').write_bytes(
        struct.pack('<8sQQ', b'TOTKRFS1', len(ROMFS_FILES), 24 + len(rows)) + rows + strings)


class ModInstall(unittest.TestCase):
    """The end of a build with --mod: the mod's RomFS files land in <mods>/<version> and its manifest is written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.logs = self.root/'logs'
        self.logs.mkdir()
        self.app = self.root/'Tears of the Kingdom.app'
        fake_romfs(self.app/'Contents/Resources/totk/extracted/v143/romfs')
        self.mods = self.root/'mods'
        self.mod = self.root/'Mod'
        (self.mod/'exefs').mkdir(parents=True)                 # --mod's usual layout
        self.said = []
        self.saved = (build_app.mods_folder, build_app.say)
        build_app.mods_folder = lambda version: self.mods/version     # never touch the real player folder
        build_app.say = self.said.append

    def tearDown(self):
        build_app.mods_folder, build_app.say = self.saved
        self.tmp.cleanup()

    def add(self, relative, data=b'x'):
        file = self.mod/'romfs'/relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        return file

    def install(self):
        return build_app.install_mod_romfs(self.mod, ROOT/'games/totk', 'v143', self.app, sys.executable, self.logs)

    def manifest(self, folder):
        lines = (folder/'manifest.tsv').read_text().splitlines()
        return {line.split('\t')[0]: line.split('\t') for line in lines if not line.startswith('#')}

    def test_the_mods_romfs_files_are_copied_and_its_manifest_written(self):
        self.add('Pack/A.pack.zs', b'replaced a')
        self.add('New/C.dat', b'added c')
        dest = self.install()
        self.assertEqual(dest, self.mods/'v143')
        self.assertEqual((dest/'Pack/A.pack.zs').read_bytes(), b'replaced a')
        self.assertEqual((dest/'New/C.dat').read_bytes(), b'added c')
        entries = self.manifest(dest)
        self.assertEqual(sorted(entries), ['New/C.dat', 'Pack/A.pack.zs'])
        self.assertEqual(entries['New/C.dat'][3], '-')                 # a file the RomFS lacks
        self.assertNotEqual(entries['Pack/A.pack.zs'][3], '-')         # the original's hash is bound
        self.assertTrue(any('files (1 replaced, 1 added)' in line for line in self.said), self.said)

    def test_a_second_build_copies_only_what_changed(self):
        self.add('Pack/A.pack.zs', b'replaced a')
        self.install()
        self.said.clear()
        self.install()
        self.assertTrue(any('0 copied, 1 already there' in line for line in self.said), self.said)

    def test_what_the_mod_dropped_is_removed_and_hand_made_files_stay(self):
        dest = self.mods/'v143'
        (dest/'Old').mkdir(parents=True)
        (dest/'Old/Gone.zs').write_bytes(b'old')
        (dest/'notes.txt').write_bytes(b'mine')                        # not in the manifest: the player's own file
        (dest/'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256\nOld/Gone.zs\t3\t00\t01\n')
        self.add('Pack/A.pack.zs', b'replaced a')
        self.install()
        self.assertFalse((dest/'Old/Gone.zs').exists())
        self.assertFalse((dest/'Old').exists())                        # the empty folder goes too
        self.assertTrue((dest/'notes.txt').exists())
        self.assertTrue(any('1 no longer in the mod removed' in line for line in self.said), self.said)

    def test_a_manifest_path_outside_the_mod_folder_is_not_followed(self):
        dest = self.mods/'v143'
        dest.mkdir(parents=True)
        outside = self.root/'outside.txt'
        outside.write_bytes(b'x')
        (dest/'manifest.tsv').write_text('# path\nsize\tsha256\toriginal_sha256\n../outside.txt\t1\t00\t01\n')
        self.add('Pack/A.pack.zs', b'replaced a')
        self.install()
        self.assertTrue(outside.exists())

    def test_a_mod_file_the_app_replaces_is_copied_but_left_out_of_the_manifest(self):
        overlays = self.app/'Contents/Resources/totk/extracted/v143/romfs-patches'
        overlays.mkdir(parents=True)
        (overlays/'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256\nUI/C.bfres\t1\t00\t01\n')
        self.add('UI/C.bfres', b'the mod version')
        self.add('Pack/A.pack.zs', b'replaced a')
        dest = self.install()
        self.assertTrue((dest/'UI/C.bfres').is_file())                 # copied with the rest
        self.assertNotIn('UI/C.bfres', self.manifest(dest))             # but the app's own version is the one loaded
        self.assertTrue(any('left out (the app replaces it too' in line for line in self.said), self.said)

    def test_a_mod_without_romfs_leaves_the_mod_folder_alone(self):
        self.assertIsNone(self.install())
        self.assertFalse((self.mods/'v143').exists())
        self.assertIn('has no romfs/', self.said[0])

    def test_a_misspelt_path_stops_with_the_app_itself_built(self):
        self.add('pack/a.pack.zs', b'replaced a')                      # the RomFS has Pack/A.pack.zs
        with self.assertRaises(build_app.BuildError) as raised:
            self.install()
        self.assertIn('would stop the game', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
