"""scripts/prepare_runtime.py's module path on two synthetic modules (no game data): module_table (MOD0, dynamic table,
symbols, RELA and JMPREL), ctor_flag (adrp + ldr w in DT_INIT), the probe's PLT stub, the symbols the loader needs,
exefs_pins (ExeFS hashes, main's build ID, the NSP size) and the pins recorded then enforced. Built from the synthetic
script of the story-2 review."""
from pathlib import Path
import contextlib
import io
import json
import shutil
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import prepare_runtime as pr  # noqa: E402

TEXT_END, RO_OFF, DATA_OFF, KEY, PATCH = 0x10000, 0x10000, 0x20000, 0x30000, 0x34000
FLAG = DATA_OFF + 0x2010
SLOT = DATA_OFF + 0x3000


def adrp(rd, pc, target):
    pages = ((target & ~4095) - (pc & ~4095)) >> 12
    return 0x90000000 | ((pages & 3) << 29) | (((pages >> 2) & 0x7ffff) << 5) | rd


def build(symbols, relocs, jmprel, plt_slot=None):
    """A rewritten-module image: MOD0 at 0x100, the dynamic table at DATA_OFF, DT_INIT at 0x1000 loading FLAG."""
    img = bytearray(PATCH + 0x4000)
    struct.pack_into('<I', img, 4, 0x100)
    img[0x100:0x104] = b'MOD0'
    struct.pack_into('<i', img, 0x104, DATA_OFF - 0x100)
    strtab, offsets = bytearray(b'\0'), []
    for name, _, _ in symbols:
        offsets.append(len(strtab)); strtab += name.encode() + b'\0'
    symtab_at, strtab_at, hash_at, rela_at, jmp_at = 0x11000, 0x12000, 0x13000, 0x14000, 0x15000
    for i, (_, defined, value) in enumerate([('', 0, 0)] + symbols):
        struct.pack_into('<IBBHQQ', img, symtab_at + 24 * i, offsets[i - 1] if i else 0, (1 << 4) | 2, 0, 1 if defined else 0, value, 0)
    img[strtab_at:strtab_at + len(strtab)] = strtab
    struct.pack_into('<II', img, hash_at, 1, len(symbols) + 1)
    for table, rows in [(rela_at, relocs), (jmp_at, jmprel)]:
        for k, (where, kind, si) in enumerate(rows):
            struct.pack_into('<QQq', img, table + 24 * k, where, (si << 32) | kind, 0)
    struct.pack_into('<II', img, 0x1000, adrp(20, 0x1000, FLAG), 0xb9400000 | (((FLAG & 4095) // 4) << 10) | (20 << 5) | 8)
    tags = [(4, hash_at), (5, strtab_at), (6, symtab_at), (10, len(strtab)), (11, 24), (7, rela_at), (8, 24 * len(relocs)),
            (9, 24), (12, 0x1000), (23, jmp_at), (2, 24 * len(jmprel)), (20, 7), (0, 0)]
    for k, (tag, value) in enumerate(tags):
        struct.pack_into('<qQ', img, DATA_OFF + 16 * k, tag, value)
    if plt_slot is not None:
        stub = TEXT_END - 0x20
        struct.pack_into('<IIII', img, stub, adrp(16, stub, plt_slot), 0xf9400211 | (((plt_slot & 4095) // 8) << 10),
                         0x91000210 | ((plt_slot & 4095) << 10), 0xd61f0220)
    return bytes(img)


class ModulePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / 'work'
        self.rw = self.work / f'rewritten/{pr.VERSION}'
        self.ex = self.work / f'extracted/{pr.VERSION}/exefs'
        self.rw.mkdir(parents=True); self.ex.mkdir(parents=True)
        self.out = self.work / 'build'; self.out.mkdir()
        self.pins_path = Path(self.tmp.name) / 'expected.json'
        shutil.copy(HERE / 'assets/expected-v1.0.0.json', self.pins_path)
        nso = bytearray(0x100); nso[:4] = b'NSO0'; nso[0x40:0x54] = bytes(range(20))
        for name in ['main', 'sdk', 'rtld', 'main.npdm']:
            (self.ex / name).write_bytes(bytes(nso) + name.encode())
        self.nsp_size = json.loads(self.pins_path.read_text())['source_nsp_size']
        self.manifest(self.nsp_size)
        self.write_modules()

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, size):
        (self.ex.parent / 'extraction-manifest.json').write_text(json.dumps(dict(source_size=size)))

    def write_modules(self, main_relocs=None, sdk_jmprel=None, extra=()):
        # main defines nnMain (referenced by GLOB_DAT) and calls GetSystemTick through its PLT; sdk defines Start and the
        # tick and calls nnMain through its PLT, as the SDK's nn::init::Start does.
        main = build([('nnMain', 1, 0x2000), ('_ZN2nn2os13GetSystemTickEv', 0, 0)],
                     [(DATA_OFF + 0x3100, pr.R_GLOB_DAT, 1)] + list(extra) if main_relocs is None else main_relocs,
                     [(SLOT, pr.R_JUMP_SLOT, 2)], plt_slot=SLOT)
        sdk = build([('_ZN2nn4init5StartEmmPFvvES2_S2_', 1, 0x3000), ('_ZN2nn2os13GetSystemTickEv', 1, 0x3100), ('nnMain', 0, 0)],
                    [], [(DATA_OFF + 0x3000, pr.R_JUMP_SLOT, 3)] if sdk_jmprel is None else sdk_jmprel)
        for name, image in [('main', main), ('sdk', sdk)]:
            (self.rw / f'{name}.patched.bin').write_bytes(image)
            (self.rw / f'{name}.fixups.tsv').write_text(f'x TEXT_END {TEXT_END:#x}\nx RO_OFF {RO_OFF:#x}\nx DATA_OFF {DATA_OFF:#x}\n'
                                                        f'x KEY_PAGE_OFF {KEY:#x}\nx PATCH_OFF {PATCH:#x}\n')
            (self.rw / f'{name}.gates.tsv').write_text('0x1234 cntpct 0 0xd53be020\n')

    def run_prepare(self, record):
        pins = pr.Pins(self.pins_path, record=record)
        pr.exefs_pins(self.work, pins)
        summary = pr.runtime_tables(self.work, self.out, pins)
        pins.save()
        return summary

    def test_record_then_enforce(self):
        with self.assertRaises(SystemExit) as stop:
            self.run_prepare(record=False)
        self.assertIn('--record', str(stop.exception))
        summary = self.run_prepare(record=True)
        self.assertEqual(summary['modules'], ['main', 'sdk'])
        self.assertEqual(summary['main_plt'], hex(TEXT_END - 0x20))
        self.assertEqual(summary['nnmain_references'], [('main', 'R_AARCH64_GLOB_DAT')])
        self.assertEqual(summary['nnmain_plt_callers'], ['sdk'])
        pins = json.loads(self.pins_path.read_text())
        self.assertEqual(pins['main_build_id'], bytes(range(20)).hex().upper())
        self.assertTrue(all(pins['exefs_sha256'].values()) and all(pins['rewritten_sha256'].values()))
        tables = (self.out / 'runtime_tables.h').read_text()
        self.assertIn(f'#define PROBE_PLT {TEXT_END - 0x20}ULL', tables)
        self.assertIn(f'#define PROBE_SLOT {SLOT}ULL', tables)
        self.assertIn(f'.ctor_flag={FLAG}ULL', tables)
        self.assertEqual(tables.count('.name="'), 2)
        self.run_prepare(record=False)   # pinned now: passes without --record
        (self.rw / 'sdk.patched.bin').write_bytes((self.rw / 'sdk.patched.bin').read_bytes() + b'x')
        with self.assertRaises(SystemExit) as stop:
            self.run_prepare(record=False)
        self.assertIn('differs from the pinned', str(stop.exception))

    def test_nsp_size_is_checked(self):
        self.manifest(self.nsp_size + 1)
        with self.assertRaises(SystemExit) as stop:
            self.run_prepare(record=True)
        self.assertIn('pinned NSP', str(stop.exception))

    def test_unsupported_relocation_is_named(self):
        self.write_modules(extra=[(DATA_OFF + 0x3200, 1031, 1)])
        with self.assertRaises(SystemExit) as stop:
            self.run_prepare(record=True)
        self.assertIn('R_AARCH64_TLSDESC', str(stop.exception))

    def test_nnmain_identity_reference_is_required(self):
        self.write_modules(main_relocs=[])
        with self.assertRaises(SystemExit) as stop:
            self.run_prepare(record=True)
        self.assertIn('verify_identity', str(stop.exception))

    def test_a_run_that_stops_leaves_no_mixed_outputs(self):
        # Headers of an earlier run are removed, and the RomFS index (checked by hash by a built runtime) is not touched.
        romfs = self.work / f'extracted/{pr.VERSION}/romfs'; romfs.mkdir(parents=True)
        (romfs / 'runtime-index.bin').write_bytes(b'old index')
        for name in ('runtime_tables.h', 'romfs_config.h', 'shared_fonts_config.h'):
            (self.out / name).write_text('/* an earlier run */')
        self.manifest(self.nsp_size + 1)   # exefs_pins stops
        saved, argv = pr.game_config.EXPECTED_PATH, sys.argv
        pr.game_config.EXPECTED_PATH, sys.argv = self.pins_path, ['prepare_runtime.py', '--work', str(self.work), '--record']
        try:
            with self.assertRaises(SystemExit):
                pr.main()
        finally:
            pr.game_config.EXPECTED_PATH, sys.argv = saved, argv
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [])
        self.assertEqual((romfs / 'runtime-index.bin').read_bytes(), b'old index')

    def test_no_plt_call_of_nnmain_warns(self):
        self.write_modules(sdk_jmprel=[])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            summary = self.run_prepare(record=True)
        self.assertEqual(summary['nnmain_plt_callers'], [])
        self.assertIn('TOTK_VERIFY_STARTUP=nnmain will not fire', err.getvalue())


if __name__ == '__main__':
    unittest.main()
