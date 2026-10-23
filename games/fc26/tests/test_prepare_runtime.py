"""scripts/prepare_runtime.py on synthetic inputs (no game data):
- the RomFS from scripts/extract_romfs.py (romfs.bin + index.json, no update merge) becomes the runtime index;
- hash pins: a null pin stops the run unless --record, which writes the measured value; a known value that differs stops it;
- the probe's PLT stub is found in a PLT larger than the 64 KiB the earlier fork searched."""
from pathlib import Path
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import prepare_runtime  # noqa: E402

NONE = 0xffffffff


def named(head, name):
    """A RomFS table entry: its fixed fields, then the name padded to 4 bytes."""
    raw = name.encode()
    return head + raw + bytes(-len(raw) % 4)


def make_romfs(root_files, folder, folder_files):
    """A RomFS image in the Switch layout scripts/extract_romfs.py indexes: files in the root and one folder with files."""
    data, placed = bytearray(), {}
    for name, payload in list(root_files.items()) + list(folder_files.items()):
        data.extend(bytes(-len(data) % 16))
        placed[name] = (len(data), len(payload)); data.extend(payload)
    chains = [(0, list(root_files)), (24, list(folder_files))]   # (parent folder entry, its files in order)
    offsets, at = {}, 0
    for _, names in chains:
        for n in names:
            offsets[n] = at; at += len(named(bytes(32), n))
    files = bytearray()
    for parent, names in chains:
        for i, n in enumerate(names):
            following = offsets[names[i + 1]] if i + 1 < len(names) else NONE
            files += named(struct.pack('<IIQQII', parent, following, *placed[n], NONE, len(n.encode())), n)
    root_dir = struct.pack('<6I', 0, NONE, 24, offsets[chains[0][1][0]], NONE, 0)          # at 0: the root, child at 24
    sub_dir = named(struct.pack('<6I', 0, NONE, NONE, offsets[chains[1][1][0]], NONE, len(folder.encode())), folder)
    dirs = root_dir + sub_dir
    dir_hash, file_hash = 0x50, 0x54
    dir_meta = 0x58
    file_meta = dir_meta + len(dirs)
    data_off = (file_meta + len(files) + 15) & ~15
    header = struct.pack('<10Q', 0x50, dir_hash, 4, dir_meta, len(dirs), file_hash, 4, file_meta, len(files), data_off)
    image = bytearray(header + struct.pack('<II', NONE, NONE) + dirs + files)
    image += bytes(data_off - len(image)) + data
    return bytes(image)


class RomfsAndPins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / 'work'
        self.romfs = self.work / f'extracted/{prepare_runtime.VERSION}/romfs'
        self.romfs.mkdir(parents=True)
        image = make_romfs({'layout.toc': b'toc' * 10, 'nxcert.ini': b'BLAZEENV=TEST\n'}, 'Data', {'cas_01.cas': bytes(range(256)) * 3})
        (self.romfs / 'romfs.bin').write_bytes(image)
        self.sha = hashlib.sha256(image).hexdigest()
        try:
            from extract_romfs import index_romfs   # the extractor's own indexer (needs the requirements' cryptography)
            files = index_romfs(self.romfs / 'romfs.bin')
        except ImportError:
            self.skipTest('scripts/extract_romfs.py needs the packages of requirements.txt')
        self.files = files
        (self.romfs / 'index.json').write_text(json.dumps(dict(status='pass', romfs_size=len(image), romfs_sha256=self.sha, files=files)))
        self.pins_path = Path(self.tmp.name) / 'expected.json'
        pins = json.loads((HERE / 'assets/expected-v1.0.0.json').read_text())
        pins['romfs'].update(size=len(image), files=len(files), sha256_prefix=self.sha[:12], sha256=None)
        self.pins_path.write_text(json.dumps(pins))
        self.out = self.work / 'build'
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_extractor_index_is_what_the_runtime_reads(self):
        self.assertEqual([f['path'] for f in self.files], ['Data/cas_01.cas', 'layout.toc', 'nxcert.ini'])
        pins = prepare_runtime.Pins(self.pins_path, record=True)
        summary = prepare_runtime.romfs_config(self.work, self.out, pins)
        self.assertEqual(summary['files'], 3)
        index = (self.romfs / 'runtime-index.bin').read_bytes()
        magic, count, strings = struct.unpack_from('<8sQQ', index)
        self.assertEqual((magic, count, strings), (b'TOTKRFS1', 3, 24 + 3 * 24))
        image = (self.romfs / 'romfs.bin').read_bytes()
        previous = ''
        for i, item in enumerate(self.files):   # what runtime/romfs.c checks: sorted paths, bounds, the bytes themselves
            offset, size, name, length = struct.unpack_from('<QQII', index, 24 + 24 * i)
            path = index[strings + name:strings + name + length - 1].decode()
            self.assertEqual((path, offset, size), (item['path'], item['offset'], item['size']))
            self.assertLess(previous, path); previous = path
        cas = next(f for f in self.files if f['path'] == 'Data/cas_01.cas')
        self.assertEqual(image[cas['offset']:cas['offset'] + cas['size']], bytes(range(256)) * 3)
        config = (self.out / 'romfs_config.h').read_text()
        self.assertIn(f'#define ROMFS_IMAGE_SIZE {len(image)}ULL', config)
        self.assertIn(f'#define ROMFS_IMAGE_SHA256 "{self.sha}"', config)
        self.assertIn(f'#define ROMFS_INDEX_SHA256 "{hashlib.sha256(index).hexdigest()}"', config)

    def test_null_pin_needs_record_then_is_kept(self):
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.romfs_config(self.work, self.out, prepare_runtime.Pins(self.pins_path, record=False))
        self.assertIn('--record', str(stop.exception))
        pins = prepare_runtime.Pins(self.pins_path, record=True)
        prepare_runtime.romfs_config(self.work, self.out, pins)
        pins.save()
        self.assertEqual(json.loads(self.pins_path.read_text())['romfs']['sha256'], self.sha)
        prepare_runtime.romfs_config(self.work, self.out, prepare_runtime.Pins(self.pins_path, record=False))   # pinned now

    def test_known_values_are_checked_before_recording(self):
        pins = json.loads(self.pins_path.read_text())
        pins['romfs']['sha256_prefix'] = 'b5c10b4bf6b3' if not self.sha.startswith('b5c10b4bf6b3') else '000000000000'
        self.pins_path.write_text(json.dumps(pins))
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.romfs_config(self.work, self.out, prepare_runtime.Pins(self.pins_path, record=True))
        self.assertIn('does not start with', str(stop.exception))
        pins['romfs']['sha256_prefix'] = self.sha[:12]; pins['romfs']['sha256'] = '0' * 64
        self.pins_path.write_text(json.dumps(pins))
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.romfs_config(self.work, self.out, prepare_runtime.Pins(self.pins_path, record=True))
        self.assertIn('differs from the pinned', str(stop.exception))


class PreIslandPin(unittest.TestCase):
    """The pre-island's .pre.bin is pinned like patched.bin: a null pin needs --record, a recorded one is compared, and
    a pin for a module whose rewrite has no island is refused."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / 'work'
        (self.work / f'rewritten/{prepare_runtime.VERSION}').mkdir(parents=True)
        self.pre = bytes(range(256)) * 16 + bytes(0x10000 - 4096)        # 4 KiB of "blocks", then zero padding
        self.path = self.work / f'rewritten/{prepare_runtime.VERSION}/main.pre.bin'
        self.path.write_bytes(self.pre)
        self.layout = dict(PRE_PATCH_OFF=-0x10000, PRE_PATCH_SIZE=0x10000, PRE_PATCH_USED=4096)
        self.pins_path = Path(self.tmp.name) / 'expected.json'
        self.pins_path.write_text((HERE / 'assets/expected-v1.0.0.json').read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def pins(self, record):
        return prepare_runtime.Pins(self.pins_path, record=record)

    def test_null_pin_needs_record_then_is_checked(self):
        self.assertIn('main.pre.bin', json.loads(self.pins_path.read_text())['rewritten_sha256'])
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.pre_island(self.work, 'main', self.layout, self.pins(False))
        self.assertIn('--record', str(stop.exception))
        pins = self.pins(True)
        self.assertEqual(prepare_runtime.pre_island(self.work, 'main', self.layout, pins),
                         (0x10000, hashlib.sha256(self.pre).hexdigest()))
        pins.save()
        self.assertEqual(json.loads(self.pins_path.read_text())['rewritten_sha256']['main.pre.bin'],
                         hashlib.sha256(self.pre).hexdigest())
        prepare_runtime.pre_island(self.work, 'main', self.layout, self.pins(False))      # pinned now
        changed = bytearray(self.pre); changed[100] ^= 1; self.path.write_bytes(changed)  # another rewrite's island
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.pre_island(self.work, 'main', self.layout, self.pins(False))
        self.assertIn('differs from the pinned', str(stop.exception))

    def test_layout_is_checked(self):
        pins = self.pins(True)
        for bad in (dict(self.layout, PRE_PATCH_OFF=-0x8000), dict(self.layout, PRE_PATCH_SIZE=0x20000),
                    {k: v for k, v in self.layout.items() if k != 'PRE_PATCH_USED'}, dict(self.layout, PRE_PATCH_USED=2048)):
            with self.assertRaises(SystemExit):
                prepare_runtime.pre_island(self.work, 'main', bad, pins)

    def test_pin_without_an_island_is_refused(self):
        self.assertEqual(prepare_runtime.pre_island(self.work, 'sdk', {}, self.pins(False)), (0, ''))   # no island, no pin
        data = json.loads(self.pins_path.read_text()); data['rewritten_sha256']['main.pre.bin'] = '0' * 64
        self.pins_path.write_text(json.dumps(data))
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.pre_island(self.work, 'main', {}, self.pins(False))
        self.assertIn('declares no pre-island', str(stop.exception))


def plt_stub(address, slot):
    """adrp x16, slot@page; ldr x17, [x16, slot@pageoff]; add x16, x16, slot@pageoff; br x17"""
    pages = ((slot & ~4095) - (address & ~4095)) >> 12
    adrp = 0x90000010 | ((pages & 3) << 29) | (((pages >> 2) & 0x7ffff) << 5)
    ldr = 0xf9400211 | (((slot & 4095) // 8) << 10)
    add = 0x91000210 | ((slot & 4095) << 10)
    return struct.pack('<IIII', adrp, ldr, add, 0xd61f0220)


class RequiredSymbols(unittest.TestCase):
    def modules(self, names):
        # main defines the names; sdk references nnMain by GLOB_DAT (what loader.c verify_identity checks) and PLT
        sdk_symbols = [dict(name='', defined=0), dict(name='nnMain', defined=0)]
        sdk_relocs = [dict(kind=prepare_runtime.R_GLOB_DAT, symbol=1), dict(kind=prepare_runtime.R_JUMP_SLOT, symbol=1)]
        return [dict(name='main', symbols=[dict(name=n, defined=1) for n in names], relocs=[]),
                dict(name='sdk', symbols=sdk_symbols, relocs=sdk_relocs)]

    def test_all_present(self):
        prepare_runtime.check_required(self.modules(list(prepare_runtime.REQUIRED)))

    def test_missing_start_names_similar_exports(self):
        other = '_ZN2nn4init5StartEmmPFvvES2_S2_PKv'   # a hypothetical other signature
        names = [n for n in prepare_runtime.REQUIRED if 'init5Start' not in n] + [other]
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.check_required(self.modules(names))
        self.assertIn('_ZN2nn4init5StartEmmPFvvES2_S2_ (the SDK startup', str(stop.exception))
        self.assertIn(other, str(stop.exception))


class ProbePlt(unittest.TestCase):
    def test_stub_beyond_the_old_64_kib_window(self):
        njump, text_end, got = 6000, 0x40000, 0x50000
        symbols = [dict(name=f'_import{i}') for i in range(njump)] + [dict(name='_ZN2nn2os13GetSystemTickEv')]
        relocs = [dict(where=got + 8 * i, kind=prepare_runtime.R_JUMP_SLOT, symbol=i, addend=0) for i in range(njump)]
        tick_slot = got + 8 * njump
        relocs.append(dict(where=tick_slot, kind=prepare_runtime.R_JUMP_SLOT, symbol=njump, addend=0))
        image = bytearray(0x60000)
        plt_start = text_end - (0x20 + 16 * (njump + 1))
        stub = plt_start + 0x20 + 16 * 10     # the 11th stub: more than 64 KiB before the end of text
        self.assertGreater(text_end - stub, 0x10000)
        image[stub:stub + 16] = plt_stub(stub, tick_slot)
        main = dict(relocs=relocs, symbols=symbols, layout=dict(TEXT_END=text_end))
        self.assertEqual(prepare_runtime.probe_plt(main, bytes(image)), (stub, tick_slot))

    def test_missing_import_is_named(self):
        main = dict(relocs=[], symbols=[], layout=dict(TEXT_END=0x1000))
        with self.assertRaises(SystemExit) as stop:
            prepare_runtime.probe_plt(main, bytes(0x2000))
        self.assertIn('_ZN2nn2os13GetSystemTickEv', str(stop.exception))


if __name__ == '__main__':
    unittest.main()
