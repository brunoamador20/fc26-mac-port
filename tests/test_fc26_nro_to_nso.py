"""FC 26 nn::ro module wrapper (games/fc26/scripts/nro_to_nso.py) on synthetic NROs (tests/fc26_synth.py)."""
from pathlib import Path
import hashlib
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'games/fc26/scripts'))
sys.path.insert(0, str(ROOT / 'games/fc26/third_party/d2r'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc26_synth as synth
import nro_to_nso as tool
from relr import decode_relr

HAVE_LZ4 = importlib.util.find_spec('lz4') is not None
HAVE_REWRITER = HAVE_LZ4 and importlib.util.find_spec('capstone') is not None


class Wrap(unittest.TestCase):
    def setUp(self):
        self.nro = synth.make_nro()
        self.nso = tool.wrap(self.nro)

    def test_header_fields(self):
        nso = self.nso
        self.assertEqual(nso[:4], b'NSO0')
        self.assertEqual(struct.unpack_from('<I', nso, 0xc)[0], 0x38)   # hashes, no compression
        segs = [struct.unpack_from('<III', nso, 0x10 + 0x10 * i) for i in range(3)]
        self.assertEqual(segs, [(0x100, 0, 0x4000), (0x4100, 0x4000, 0x4000), (0x8100, 0x8000, 0x1000)])
        self.assertEqual(struct.unpack_from('<I', nso, 0x3c)[0], synth.BSS_SIZE)
        self.assertEqual(struct.unpack_from('<III', nso, 0x60), (0x4000, 0x4000, 0x1000))
        self.assertEqual(nso[0x40:0x60], self.nro[0x40:0x60])                              # module id
        for i, (_, memory, size) in enumerate(segs):
            self.assertEqual(nso[0xa0 + 0x20 * i:0xc0 + 0x20 * i], hashlib.sha256(self.nro[memory:memory + size]).digest())
        dynstr, strsz, dynsym, symsz = struct.unpack_from('<4I', nso, 0x90)
        self.assertEqual((synth.RO + dynstr, synth.RO + dynsym, symsz), (0x4000, 0x4400, 24 * (len(synth.SYMBOLS) + 1)))
        self.assertEqual(len(nso), 0x100 + synth.NRO_SIZE)

    def test_round_trip_byte_for_byte(self):
        self.assertEqual(tool.unwrap(self.nso), self.nro)
        image, _, bss = tool.nso_image(self.nso)
        self.assertEqual(image, self.nro + bytes(bss))
        for start, end in ((0, 0x4000), (0x4000, 0x8000), (0x8000, synth.NRO_SIZE)):   # text, ro, data
            self.assertEqual(image[start:end], self.nro[start:end])
        self.assertEqual(image[tool.parse_nro(self.nro)['mod0']:][:4], b'MOD0')

    @unittest.skipUnless(HAVE_LZ4, 'lz4 is needed to import the kit decoder (nsoimg.py)')
    def test_kit_decoder_sees_the_same_image_and_relocations(self):
        import nsoimg
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'm.nso'
            path.write_bytes(self.nso)
            image = nsoimg.load(str(path))
        self.assertEqual(image, self.nro + bytes(synth.BSS_SIZE))
        kinds = sorted(k for _, k, _, _, _ in nsoimg.relocs(image))
        self.assertEqual(kinds, sorted([1027] * 5 + [257] * 2 + [1025] * 2 + [1031] * 2 + [1026] * 2))
        self.assertEqual(nsoimg.func_starts(image, 0x4000), sorted(synth.CODE))

    def test_relocations_through_the_nso_image(self):
        image, _, _ = tool.nso_image(self.nso)
        _, tags, needed = tool.parse_dynamic(image, synth.MOD0)
        self.assertEqual(needed, [])
        self.assertEqual(dict(decode_relr(image, tags, synth.DATA, len(image))), synth.RELR_TARGETS)
        relocs = tool.relocations(image, tags, synth.DATA, len(image))
        by_table = sorted((table, kind, where) for where, kind, _, _, table in relocs if table != 'relr')
        self.assertEqual(by_table, sorted([
            ('rela', 257, synth.G_ABS_IMPORT), ('rela', 257, synth.G_ABS_LOCAL), ('rela', 1025, synth.G_GLOB),
            ('rela', 1025, synth.G_WEAK), ('rela', 1031, synth.G_TLS_LOCAL), ('rela', 1031, synth.G_TLS_SYM),
            ('jmprel', 1026, synth.G_JUMP0), ('jmprel', 1026, synth.G_JUMP1)]))
        addend = {where: a for where, kind, _, a, _ in relocs}
        self.assertEqual((addend[synth.G_ABS_IMPORT], addend[synth.G_TLS_LOCAL]), (16, 0x10))

    def test_info(self):
        info = tool.describe(self.nro)
        self.assertEqual(info['relocations'], {'relr:RELATIVE': 5, 'rela:ABS64': 2, 'rela:GLOB_DAT': 2,
                                               'rela:TLSDESC': 2, 'jmprel:JUMP_SLOT': 2})
        self.assertEqual(info['imports'], sorted(n for n, _, _, v in synth.SYMBOLS if v is None))
        self.assertEqual((info['symbols'], info['exports'], info['needed']), (9, 3, []))
        self.assertEqual((info['header_dynsym'], info['header_dynstr']), ('ro-relative', 'ro-relative'))
        self.assertEqual(info['sha256'], hashlib.sha256(self.nro).hexdigest())
        self.assertEqual(info['mod0']['eh_frame_hdr_start'], 0x4b00)
        self.assertEqual(info['mod0']['sdk19_fields']['full_relro_end'], synth.INIT_ARRAY)

    def test_rejects_what_the_ro_service_rejects(self):
        def broken(offset, fmt, value):
            data = bytearray(self.nro); struct.pack_into(fmt, data, offset, value); return bytes(data)
        cases = {'compressed': broken(0x1c, '<I', 2), 'magic': broken(0x10, '<4s', b'NRO1'),
                 'contiguous': broken(0x28, '<I', 0x5000), 'beyond the file': broken(0x18, '<I', 0xa000),
                 'page aligned': broken(0x38, '<I', 0x2010), 'MOD0': broken(synth.MOD0, '<4s', b'MODX')}
        for what, data in cases.items():
            with self.subTest(what), self.assertRaises(ValueError):
                tool.wrap(data)
        with self.assertRaises(ValueError):
            tool.unwrap(b'NSO0' + bytes(0xfc))


class Register(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.nro = synth.make_nro()
        (self.dir / 'm.nro').write_bytes(self.nro)

    def tearDown(self):
        self.temp.cleanup()

    def test_manifest_row_keyed_by_the_nro_hash(self):
        patched, gates = synth.fake_rewrite(self.nro, self.dir, 'PlatformNvn')
        for _ in range(2):   # registering again replaces the row
            result = tool.register(self.dir / 'm.nro', self.dir, 'PlatformNvn')
        self.assertEqual((result['sites'], result['gates']), (len(synth.SITES), len(gates)))
        rows = [l.split('\t') for l in (self.dir / tool.MANIFEST).read_text().splitlines() if not l.startswith('#')]
        self.assertEqual(rows, [[hashlib.sha256(self.nro).hexdigest(), 'PlatformNvn', hashlib.sha256(patched).hexdigest(),
                                 str(synth.NRO_SIZE), str(synth.BSS_SIZE), self.nro[0x40:0x60].hex()]])

    def test_refuses_a_rewrite_that_changed_what_must_stay(self):
        patched, _ = synth.fake_rewrite(self.nro, self.dir, 'm')
        path = self.dir / 'm.patched.bin'
        for what, offset, value in (('data', synth.EXPORT_DATA, 0x99), ('header', 0x44, 0x99), ('bss', synth.NRO_SIZE, 1),
                                    ('ro', 0x4004, 0x99), ('text not a branch', 0x130, 0x99), ('key page', 0xc000, 1)):
            with self.subTest(what):
                broken = bytearray(patched); broken[offset] ^= value; path.write_bytes(broken)
                with self.assertRaises(ValueError): tool.register(self.dir / 'm.nro', self.dir, 'm')
        path.write_bytes(patched)
        fixups = self.dir / 'm.fixups.tsv'
        fixups.write_text(fixups.read_text().replace('# DATA_OFF\t0x8000', '# DATA_OFF\t0x7000'))
        with self.assertRaises(ValueError): tool.register(self.dir / 'm.nro', self.dir, 'm')


@unittest.skipUnless(HAVE_REWRITER, 'capstone and lz4 are needed to run the kit rewriter')
class RealRewriter(unittest.TestCase):
    """The kit's patch_nso.py, unchanged, rewrites the wrapped NRO; the result registers."""
    def rewrite(self, directory, nro, name):
        (directory / f'{name}.nro').write_bytes(nro)
        (directory / f'{name}.nso').write_bytes(tool.wrap(nro))
        env = dict(os.environ, DM_RULESET='native', DM_PRIVATE_GATES='0')
        return subprocess.run([sys.executable, str(ROOT / 'games/fc26/third_party/d2r/patch_nso.py'),
                               str(directory / f'{name}.nso'), str(directory), name], capture_output=True, text=True, env=env)

    def test_rewrite_and_register(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            run = self.rewrite(directory, synth.make_nro(), 'PlatformNvn')
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            result = tool.register(directory / 'PlatformNvn.nro', directory, 'PlatformNvn')
            self.assertEqual(result['gates'], 2)                     # svc #1 and cntpct
            self.assertGreaterEqual(result['sites'], len(synth.SITES))
            sites = {int(l.split()[0], 0): l.split()[1] for l in (directory / 'PlatformNvn.sites.tsv').read_text().splitlines()}
            self.assertEqual({a: sites.get(a) for a in synth.SITES},
                             {0x100: 'tpidr_r', 0x108: 'svc', 0x110: 'cntpct', 0x11c: 'x18'})

    def test_a_header_word_the_rewriter_touches_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            # The linear scan covers the whole text, header included: a header word that decodes as a rewritable
            # instruction (here mrs x0, tpidr_el0 inside the module id) is rewritten like code.
            run = self.rewrite(directory, synth.make_nro(header_word=synth.MRS_X0_TPIDR), 'm')
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            with self.assertRaisesRegex(ValueError, 'NRO header'):
                tool.register(directory / 'm.nro', directory, 'm')


if __name__ == '__main__':
    unittest.main()
