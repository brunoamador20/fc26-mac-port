"""games/fc26/scripts/estoria3_perguntas.py on a synthetic work folder: ExeFS stand-ins for main / sdk / rtld, a RomFS
image with the video module, its NRR and its ELF twin (.nrs), a registered rewrite and a runtime source tree."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest

try:
    import lz4.block
except ImportError:
    lz4 = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'games/fc26/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc26_synth as synth
import nro_to_nso as tool
import estoria3_perguntas as questions

VIDEO = '/Engine.Render.Core2.PlatformNvn'
# Synthetic names only: they stand for whatever the real sdk exports.
RO_API = ['_ZN2nn2ro10InitializeEv', '_ZN2nn2ro10LoadModuleEPNS0_6ModuleEPKvPvmi']
RO_DETAIL = '_ZN2nn2ro6detail17g_pSyntheticListE'


def work_folder(directory, rtld_strings=RO_DETAIL.encode() + b'\0', nrs=True):
    exefs = directory / 'extracted/v100/exefs'; romfs = directory / 'extracted/v100/romfs'
    exefs.mkdir(parents=True); romfs.mkdir(parents=True)
    imports = [n for n, _, _, v in synth.SYMBOLS if v is None and n != 'weak_optional_hook']
    (exefs / 'main').write_bytes(tool.wrap(synth.make_library(['nnMain'], RO_API + ['_ZN2nn2ro9OtherCallEv'])))
    (exefs / 'sdk').write_bytes(tool.wrap(synth.make_library(RO_API + [RO_DETAIL] + imports, [], b'ldr:ro\0sm:\0')))
    (exefs / 'rtld').write_bytes(tool.wrap(synth.make_library([], [], rtld_strings)))
    (exefs / 'main.npdm').write_bytes(b'META')
    nro = synth.make_nro()
    files = {f'{VIDEO}.nro': nro, '/.nrr/Application.nrr': synth.make_nrr(synth.other_hashes(2) + [hashlib.sha256(nro).digest()])}
    if nrs: files[f'{VIDEO}.nrs'] = synth.make_elf(nro)
    blob, index = bytearray(), []
    for path, data in files.items():
        index.append(dict(path=path, offset=len(blob) + 0x200, size=len(data))); blob += bytes(0x200) + data
    (romfs / 'romfs.bin').write_bytes(blob)
    (romfs / 'index.json').write_text(json.dumps(dict(status='pass', files=index)))
    runtime = directory / 'runtime'; runtime.mkdir()
    (runtime / 'host.c').write_text('static const char *const names[] = {"__cxa_guard_acquire", "nnMain"};\n')
    return nro, runtime


def exefs_nso(data, compress=True):
    raw = bytearray(data)
    raw[0x110:0x114] = b'\0\0\0\0'   # ExeFS NSOs do not have NRO0 magic in text
    if not (compress and lz4):
        return bytes(raw)
    out, body = bytearray(raw[:0x100]), bytearray()
    for i in range(3):
        file_offset, memory, size = struct.unpack_from('<III', raw, 0x10 + 0x10 * i)
        packed = lz4.block.compress(raw[file_offset:file_offset + size], store_size=False)
        struct.pack_into('<I', out, 0x10 + 0x10 * i, 0x100 + len(body))
        struct.pack_into('<I', out, 0x60 + 4 * i, len(packed))
        body += packed
    struct.pack_into('<I', out, 0xc, 0x3f)
    return bytes(out + body)


class Questions(unittest.TestCase):
    def test_answers_from_the_files(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            nro, runtime = work_folder(work)
            r = questions.answer(work, 'v100', runtime, extract=True)
            self.assertEqual(r['P1']['main_imports_nn_ro'], sorted(RO_API + ['_ZN2nn2ro9OtherCallEv']))
            self.assertFalse(r['P1']['nn_ro_in_sdk'])
            self.assertEqual(r['P1']['main_nn_ro_not_in_sdk'], ['_ZN2nn2ro9OtherCallEv'])
            self.assertEqual(r['P2']['rtld_nn_ro_names'], [RO_DETAIL])
            self.assertEqual(r['P2']['rtld_names_exported_by_sdk'], [RO_DETAIL])
            self.assertEqual(r['P3']['sdk'], {'ldr:ro': 1, 'ro:1': 0})
            self.assertEqual(r['P4']['nro_tlsdesc_symbols'], ['(local)', 'nro_tls_var'])
            self.assertEqual(r['P4']['nrs']['tls'], dict(vaddr=hex(synth.DATA), filesz=0x10, memsz=0x40, align=0x10))
            self.assertTrue(r['P4']['nrs']['build_id_matches_nro'])
            self.assertEqual([t['symbol'] for t in r['P4']['nrs']['tlsdesc']], ['(local)', 'nro_tls_var'])
            self.assertEqual((r['P5']['not_exported_strong'], r['P5']['not_exported_weak']), ([], ['weak_optional_hook']))
            self.assertEqual(r['P5']['overridden_by_host'], ['__cxa_guard_acquire'])
            nrr = r['P6']['nrr']['/.nrr/Application.nrr']
            self.assertTrue(nrr['program_id_is_fc26'] and nrr['sorted'] and nrr['nros'][f'{VIDEO}.nro']['listed'])
            self.assertEqual(r['P7'], dict(state='not rewritten yet'))
            self.assertFalse(r['briefing_facts']['size']['same'])            # a synthetic module, not the real one
            self.assertEqual(r['briefing_facts']['tlsdesc'], dict(briefing=2, measured=2, same=True))
            self.assertEqual((work / f'nro{VIDEO}.nro').read_bytes(), nro)     # --extract
            text = questions.markdown(r)
            for heading in ('## P1', '## P2', '## P3', '## P4', '## P5', '## P6', '## P7', '**← DIFERENTE**'):
                self.assertIn(heading, text)

    def test_rewrite_state_and_missing_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            nro, runtime = work_folder(work, rtld_strings=b'', nrs=False)
            rewritten = work / 'rewritten/v100'; rewritten.mkdir(parents=True)
            (rewritten / 'PlatformNvn.nro').write_bytes(nro)
            synth.fake_rewrite(nro, rewritten, 'PlatformNvn')
            tool.register(rewritten / 'PlatformNvn.nro', rewritten, 'PlatformNvn')
            r = questions.answer(work, 'v100', runtime)
            self.assertEqual((r['P7']['state'], r['P7']['sites'], r['P7']['gates']), ('registered', len(synth.SITES), 2))
            self.assertEqual((r['P2']['rtld_nn_ro_names'], r['P4']['nrs']), ([], None))
            image = bytearray((rewritten / 'PlatformNvn.patched.bin').read_bytes()); image[0x8008] ^= 1
            (rewritten / 'PlatformNvn.patched.bin').write_bytes(image)
            self.assertEqual(questions.answer(work, 'v100', runtime)['P7']['state'], 'rewrite refused')

    def test_command_line_writes_the_report(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            _, runtime = work_folder(work)
            run = subprocess.run([sys.executable, str(ROOT / 'games/fc26/scripts/estoria3_perguntas.py'), '--work', str(work),
                                  '--runtime', str(runtime)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('# Estória 3', run.stdout)
            report = json.loads((work / 'analysis/estoria3_perguntas.json').read_text())
            self.assertEqual(report['P5']['imports'], 5)
            self.assertEqual(run.stdout, (work / 'analysis/estoria3_perguntas.md').read_text() + '\n')

    def test_answer_with_exefs_nso_file(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            _, runtime = work_folder(work)
            exefs = work / 'extracted/v100/exefs'
            (exefs / 'main').write_bytes(exefs_nso((exefs / 'main').read_bytes()))
            (exefs / 'sdk').write_bytes(exefs_nso((exefs / 'sdk').read_bytes()))
            r = questions.answer(work, 'v100', runtime)
            self.assertEqual(r['P1']['main_imports_nn_ro'], sorted(RO_API + ['_ZN2nn2ro9OtherCallEv']))
            self.assertEqual(r['P1']['main_nn_ro_not_in_sdk'], ['_ZN2nn2ro9OtherCallEv'])
            self.assertEqual(r['P3']['sdk'], {'ldr:ro': 1, 'ro:1': 0})


if __name__ == '__main__':
    unittest.main()
