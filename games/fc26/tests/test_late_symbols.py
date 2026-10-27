"""Verification of late symbol resolution:
1. prepare_runtime: strong imports of main/sdk not defined by main/sdk but exported by an NRO in
   nro_manifest.tsv are recorded in late_symbols[] in runtime_tables.h and in runtime-layout.json.
   Unexported strong imports stay unresolved and do not become late.
2. runtime/loader.c: when a strong import resolves to a symbol in late_symbols, loader prints
   [rtld] Unresolved symbol: '<name>' (late: exported by <NRO>), sets the slot to 0, records the slot
   in runtime_late_slots(), and proceeds. Any other unresolved strong import aborts.
"""
from pathlib import Path
import hashlib
import json
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
sys.path.insert(0, str(HERE / 'tests'))
import prepare_runtime as pr
import fc26_synth as synth
import nro_to_nso

TEXT_END, RO_OFF, DATA_OFF, KEY, PATCH = 0x10000, 0x10000, 0x20000, 0x30000, 0x34000
FLAG = DATA_OFF + 0x2010
SLOT = DATA_OFF + 0x3000


def adrp(rd, pc, target):
    pages = ((target & ~4095) - (pc & ~4095)) >> 12
    return 0x90000000 | ((pages & 3) << 29) | (((pages >> 2) & 0x7ffff) << 5) | rd


def build_module(symbols, relocs, jmprel, plt_slot=None):
    img = bytearray(PATCH + 0x4000)
    struct.pack_into('<I', img, 4, 0x100)
    img[0x100:0x104] = b'MOD0'
    struct.pack_into('<i', img, 0x104, DATA_OFF - 0x100)
    strtab, offsets = bytearray(b'\0'), []
    for name, _, _ in symbols:
        offsets.append(len(strtab))
        strtab += name.encode() + b'\0'
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


class LateSymbolGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / 'work'
        self.rw = self.work / f'rewritten/{pr.VERSION}'
        self.ex = self.work / f'extracted/{pr.VERSION}/exefs'
        self.rw.mkdir(parents=True)
        self.ex.mkdir(parents=True)
        self.out = self.work / 'build'
        self.out.mkdir()
        self.pins_path = Path(self.tmp.name) / 'expected.json'

        pins = json.loads((HERE / 'assets/expected-v1.0.0.json').read_text())
        pins['main_build_id'] = None
        pins['rewritten_sha256'].pop('main.pre.bin', None)
        for k in pins['exefs_sha256']: pins['exefs_sha256'][k] = None
        for k in pins['rewritten_sha256']: pins['rewritten_sha256'][k] = None
        self.pins_path.write_text(json.dumps(pins, indent=4))

        nso = bytearray(0x100)
        nso[:4] = b'NSO0'
        nso[0x40:0x54] = bytes(range(20))
        for name in ['main', 'sdk', 'rtld', 'main.npdm']:
            (self.ex / name).write_bytes(bytes(nso) + name.encode())
        self.nsp_size = json.loads(self.pins_path.read_text())['source_nsp_size']
        (self.ex.parent / 'extraction-manifest.json').write_text(json.dumps(dict(source_size=self.nsp_size)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_late_symbol_generation_and_unexported_separation(self):
        # 1. Write synthetic NRO exporting 'nro_export_data'
        nro = synth.make_nro()
        nro_name = 'Engine.Render.Core2.PlatformNvn'
        (self.rw / f'{nro_name}.nro').write_bytes(nro)
        h = nro_to_nso.parse_nro(nro)
        manifest_row = f'{hashlib.sha256(nro).hexdigest()}\t{nro_name}\t{hashlib.sha256(nro).hexdigest()}\t{h["size"]}\t{h["bss_size"]}\t{h["module_id"]}\n'
        (self.rw / 'nro_manifest.tsv').write_text(manifest_row)

        # 2. Main imports:
        # - nnMain (defined)
        # - GetSystemTick (imported from sdk)
        # - nro_export_data (strong GLOB_DAT, exported by NRO -> late)
        # - unexported_strong_var (strong GLOB_DAT, NOT exported by NRO -> stays unexported)
        main_syms = [
            ('nnMain', 1, 0x2000),
            ('_ZN2nn2os13GetSystemTickEv', 0, 0),
            ('nro_export_data', 0, 0),
            ('unexported_strong_var', 0, 0)
        ]
        main_relocs = [
            (DATA_OFF + 0x3100, pr.R_GLOB_DAT, 1),
            (DATA_OFF + 0x3200, pr.R_GLOB_DAT, 3),   # nro_export_data
            (DATA_OFF + 0x3208, pr.R_GLOB_DAT, 4),   # unexported_strong_var
        ]
        main = build_module(main_syms, main_relocs, [(SLOT, pr.R_JUMP_SLOT, 2)], plt_slot=SLOT)

        sdk = build_module([
            ('_ZN2nn4init5StartEmmPFvvES2_S2_', 1, 0x3000),
            ('_ZN2nn2os13GetSystemTickEv', 1, 0x3100),
            ('nnMain', 0, 0)
        ], [], [(DATA_OFF + 0x3000, pr.R_JUMP_SLOT, 3)])

        for name, image in [('main', main), ('sdk', sdk)]:
            (self.rw / f'{name}.patched.bin').write_bytes(image)
            (self.rw / f'{name}.fixups.tsv').write_text(
                f'x TEXT_END {TEXT_END:#x}\nx RO_OFF {RO_OFF:#x}\nx DATA_OFF {DATA_OFF:#x}\n'
                f'x KEY_PAGE_OFF {KEY:#x}\nx PATCH_OFF {PATCH:#x}\n'
            )
            (self.rw / f'{name}.gates.tsv').write_text('0x1234 cntpct 0 0xd53be020\n')

        pins = pr.Pins(self.pins_path, record=True)
        pr.exefs_pins(self.work, pins)
        summary = pr.runtime_tables(self.work, self.out, pins)

        # Verified in summary:
        self.assertIn('nro_export_data', summary['late_symbols'])
        self.assertNotIn('unexported_strong_var', summary['late_symbols'])

        # Verified in runtime_tables.h:
        tables = (self.out / 'runtime_tables.h').read_text()
        late_part = tables[tables.find('late_symbols'):tables.find('modules')]
        self.assertIn('{"nro_export_data", "Engine.Render.Core2.PlatformNvn"}', late_part)
        self.assertNotIn('unexported_strong_var', late_part)
        self.assertIn('#define LATE_SYMBOL_COUNT 1ULL', tables)

        # Verified in runtime-layout.json:
        layout = json.loads((self.work / 'analysis/runtime-layout.json').read_text())
        self.assertIn('late_symbols', layout)
        self.assertEqual(layout['late_symbols'], [{'name': 'nro_export_data', 'nro': nro_name}])


class RuntimeLateRelocationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'late_reloc_test'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        build = subprocess.run([
            compiler, *flags, f'-I{HERE / "runtime"}',
            str(HERE / 'tests/late_reloc_test.c'), '-o', str(cls.exe)
        ], capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_late_symbol_warns_zeros_slot_and_records_hook(self):
        run = subprocess.run([str(self.exe), 'test_late'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('LATE_OK', run.stdout)
        self.assertIn("[rtld] Unresolved symbol: '_ZN3nvn27pfncpp_nvnTextureReadTexelsE' (late: exported by Engine.Render.Core2.PlatformNvn)", run.stderr)

    def test_unexported_symbol_fails_relocation(self):
        run = subprocess.run([str(self.exe), 'test_unresolved'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 42, f'Expected exit code 42 (runtime_fail), got {run.returncode}')
        self.assertIn('main unresolved unexported_strong_symbol', run.stderr)
        self.assertIn('runtime_fail: strong import unresolved', run.stderr)


if __name__ == '__main__':
    unittest.main()
