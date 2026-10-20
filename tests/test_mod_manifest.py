"""make_mod_manifest.py: the manifest of a player's RomFS mod, checked against a small fake RomFS (no game data)."""
import hashlib
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'games/totk/scripts/make_mod_manifest.py'
sys.path.insert(0, str(ROOT/'games/totk/scripts'))
import make_mod_manifest      # noqa: E402
FILES = {'Pack/A.pack.zs': b'original a', 'Sound/B.bwav': b'original b' * 100, 'UI/C.bfres': b'c'}


def fake_romfs(folder):
    """romfs.bin and runtime-index.bin in the layout scripts/prepare_romfs_backend.py writes."""
    folder.mkdir(parents=True, exist_ok=True)
    image, rows, strings = bytearray(), bytearray(), bytearray()
    for path in sorted(FILES):
        name = path.encode() + b'\0'
        rows += struct.pack('<QQII', len(image), len(FILES[path]), len(strings), len(name))
        image += FILES[path]
        strings += name
    (folder/'romfs.bin').write_bytes(image)
    (folder/'runtime-index.bin').write_bytes(struct.pack('<8sQQ', b'TOTKRFS1', len(FILES), 24 + len(rows)) + rows + strings)
    return folder


HEAPDEF = 'System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs'


def heapdef_byml(sizes):
    """A minimal BYML v7 ("YB") System/HeapSize table: root hash {"Heaps": hash{name: {"Size": KiB}}}."""
    names = ['Heaps', 'Size', *sizes]
    key_blob = b''.join(name.encode() + b'\0' for name in names)
    positions, at = [], 4 + 4*(len(names) + 1)
    for name in names:
        positions.append(at)
        at += len(name) + 1
    key_table = (struct.pack('<I', len(names) << 8) + b''.join(struct.pack('<I', o) for o in positions)
                 + struct.pack('<I', at) + key_blob)                       # n + 1 offsets, then the strings
    keys_at = 0x10
    root_at = keys_at + len(key_table) + 4                                 # after the (empty) string table
    heaps_at = root_at + 12
    first = heaps_at + 4 + 8*len(sizes)
    body, where = b'', {}
    for name, size in sizes.items():
        where[name] = first + len(body)
        body += struct.pack('<I', (1 << 8) | 0xc1) + (1).to_bytes(3, 'little') + b'\xd1' + struct.pack('<i', size)
    out = bytearray(b'YB' + struct.pack('<H', 7) + struct.pack('<III', keys_at, root_at - 4, root_at))
    out += key_table + struct.pack('<I', 0)
    out += struct.pack('<I', (1 << 8) | 0xc1) + (0).to_bytes(3, 'little') + b'\xc1' + struct.pack('<I', heaps_at)
    out += struct.pack('<I', (len(sizes) << 8) | 0xc1) + b''.join(
        (2 + i).to_bytes(3, 'little') + b'\xc1' + struct.pack('<I', where[name]) for i, name in enumerate(sizes))
    return bytes(out + body)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


class ModManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.romfs = fake_romfs(self.root/'romfs')
        self.mod = self.root/'mods/v143'

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, data):
        (self.mod/path).parent.mkdir(parents=True, exist_ok=True)
        (self.mod/path).write_bytes(data)

    def test_lists_replaced_files_with_both_hashes(self):
        self.put('Sound/B.bwav', b'dubbed')
        self.put('UI/C.bfres', b'c')   # same as the original: left out
        self.put('.DS_Store', b'finder')
        result = run(self.mod, '--romfs', self.romfs)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in (self.mod/'manifest.tsv').read_text().splitlines() if not l.startswith('#')]
        self.assertEqual(lines, ['\t'.join(['Sound/B.bwav', '6', hashlib.sha256(b'dubbed').hexdigest(),
                                            hashlib.sha256(FILES['Sound/B.bwav']).hexdigest()])])
        self.assertIn('(same as the original): UI/C.bfres', result.stdout)

    def fake_app(self, *overlay):
        """A fake .app whose romfs-patches replaces each given path (or path, bytes pair)."""
        app = self.root/'Tears of the Kingdom.app'
        fake_romfs(app/'Contents/Resources/totk/extracted/v143/romfs')
        folder = app/'Contents/Resources/totk/extracted/v143/romfs-patches'
        folder.mkdir(parents=True, exist_ok=True)
        pairs = [(o, b'app version') if isinstance(o, str) else (o[0], o[1]) for o in overlay]
        (folder/'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256\n'
                                          + ''.join(f'{p}\t1\t00\t01\n' for p, _ in pairs))
        for path, data in pairs:
            (folder/path).parent.mkdir(parents=True, exist_ok=True)
            (folder/path).write_bytes(data)
        return app

    def test_a_file_the_app_replaces_is_left_out_by_itself(self):
        self.put('Sound/B.bwav', b'dubbed')
        self.put('UI/C.bfres', b'modded c')          # the app replaces UI/C.bfres itself (romfs-patches)
        app = self.fake_app('UI/C.bfres')
        result = run(self.mod, '--app', app, '--version', 'v143')      # no --exclude needed
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in (self.mod/'manifest.tsv').read_text().splitlines() if not l.startswith('#')]
        self.assertEqual([l.split('\t')[0] for l in lines], ['Sound/B.bwav'])
        self.assertIn('left out (the app replaces it too, so this file would not be used', result.stdout)
        self.assertIn('UI/C.bfres', result.stdout)

    def test_exclude_still_leaves_out_other_files(self):
        self.put('Sound/B.bwav', b'dubbed')
        self.put('UI/C.bfres', b'modded c')
        result = run(self.mod, '--romfs', self.romfs, '--exclude', 'Sound/*')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in (self.mod/'manifest.tsv').read_text().splitlines() if not l.startswith('#')]
        self.assertEqual([l.split('\t')[0] for l in lines], ['UI/C.bfres'])
        self.assertIn('left out (--exclude): Sound/B.bwav', result.stdout)

    def test_the_heap_table_says_whether_the_app_carries_it(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd needs Python 3.14')
        mod_sizes = {'DynamicTextureAllocatorMem': 100, 'Graphics': 200, 'RSDB': 5}
        self.put('System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs', zstd.compress(heapdef_byml(mod_sizes)))
        chained = dict(mod_sizes, DynamicTextureAllocatorMem=150, Graphics=250)     # the 2K delta added to both
        result = run(self.mod, '--app', self.fake_app((HEAPDEF, zstd.compress(heapdef_byml(chained)))), '--version', 'v143')
        self.assertIn('already carries these heap sizes', result.stdout)
        other = self.fake_app((HEAPDEF, zstd.compress(heapdef_byml(dict(mod_sizes, RSDB=7)))))
        self.assertIn('rebuild the app with --mod', run(self.mod, '--app', other, '--version', 'v143').stdout)

    def test_misspelt_path_writes_nothing(self):
        self.put('Sound/b.bwav', b'wrong case')
        result = run(self.mod, '--romfs', self.romfs)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a file of this RomFS: Sound/b.bwav (it has Sound/B.bwav', result.stderr)
        self.assertFalse((self.mod/'manifest.tsv').exists())

    def test_new_file_is_added(self):   # issue #48
        self.put('Sound/B.bwav', b'dubbed')
        self.put('UI/Tex/New/Gold.bntx.zs', b'new texture')
        result = run(self.mod, '--romfs', self.romfs)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = sorted(l for l in (self.mod/'manifest.tsv').read_text().splitlines() if not l.startswith('#'))
        self.assertEqual(lines[1], '\t'.join(['UI/Tex/New/Gold.bntx.zs', '11', hashlib.sha256(b'new texture').hexdigest(), '-']))
        self.assertIn('(1 replaced, 1 added)', result.stdout)

    def test_app_path_takes_the_version_from_the_folder(self):
        app = self.root/'Tears of the Kingdom.app'
        fake_romfs(app/'Contents/Resources/totk/extracted/v143/romfs')
        self.put('Pack/A.pack.zs', b'modded a')
        result = run(self.mod, '--app', app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 files', result.stdout)


class TheWriterToolsShare(unittest.TestCase):
    """make_button_icons.py writes a mod's manifest with write_manifest() - it used to unpack manifest()'s return into
    four names, which stopped working when the record grew. This runs the code that caller runs, on the same fake
    RomFS: no game data and no fontTools needed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.romfs = fake_romfs(self.root/'romfs')
        self.mod = self.root/'mods/v143'

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, data):
        (self.mod/path).parent.mkdir(parents=True, exist_ok=True)
        (self.mod/path).write_bytes(data)

    def test_the_record_is_read_by_name_and_the_manifest_is_written(self):
        self.put('Sound/B.bwav', b'dubbed')
        self.put('UI/Tex/New/Gold.bntx.zs', b'new texture')
        found = make_mod_manifest.write_manifest(self.mod, self.romfs)
        self.assertEqual(found._fields, ('lines', 'same', 'added', 'misspelt', 'excluded', 'taken'))
        self.assertEqual(found.misspelt, [])
        self.assertEqual(found.added, ['UI/Tex/New/Gold.bntx.zs'])
        self.assertEqual([line.split('\t')[0] for line in found.lines], ['Sound/B.bwav', 'UI/Tex/New/Gold.bntx.zs'])
        self.assertEqual((self.mod/'manifest.tsv').read_text(), make_mod_manifest.manifest_text(found))
        self.assertTrue((self.mod/'manifest.tsv').read_text().startswith(
            '# path\tsize\tsha256\toriginal_sha256 (generated by scripts/make_mod_manifest.py)\n'))

    def test_a_misspelt_path_writes_no_manifest(self):
        self.put('Sound/b.bwav', b'wrong case')
        found = make_mod_manifest.write_manifest(self.mod, self.romfs)
        self.assertEqual(found.misspelt, [('Sound/b.bwav', 'Sound/B.bwav')])   # the caller names it, as before
        self.assertFalse((self.mod/'manifest.tsv').exists())


if __name__ == '__main__':
    unittest.main()
