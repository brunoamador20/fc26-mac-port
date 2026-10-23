"""Synthetic tests for the 29 nn::audio functions and IPC services (audout:u, audin:u) in FC 26 runtime.
"""
from pathlib import Path
import json
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest
import lz4.block

HERE = Path(__file__).resolve().parents[1]
# the main of the version the port runs (assets/game.json version_dir): the overrides must still match its imports
MAIN_NSO = (Path.home() / 'fc26-switch/work/extracted') / json.loads((HERE / 'assets/game.json').read_text())['version_dir'] / 'exefs/main'


def extract_dynsym_imports(nso_path):
    raw = nso_path.read_bytes()
    if raw[:4] != b'NSO0':
        raise ValueError('Expected NSO0')
    flags = struct.unpack_from('<I', raw, 12)[0]
    compressed = struct.unpack_from('<III', raw, 0x60)
    segments = []
    for i, name in enumerate(['text', 'rodata', 'data']):
        fileoff, address, size, _ = struct.unpack_from('<IIII', raw, 0x10 + 16 * i)
        stored = compressed[i] if flags & (1 << i) else size
        payload = raw[fileoff:fileoff + stored]
        data = lz4.block.decompress(payload, uncompressed_size=size) if flags & (1 << i) else payload
        segments.append({'name': name, 'address': address, 'size': size, 'data': data})

    image = bytearray(max(s['address'] + s['size'] for s in segments))
    for s in segments:
        image[s['address']:s['address'] + s['size']] = s['data']

    def span(address, size):
        return bytes(image[address:address + size])

    modoff = struct.unpack_from('<I', image, 4)[0]
    dynoff = modoff + struct.unpack_from('<i', image, modoff + 4)[0]
    dynamic = []
    for index in range(4096):
        tag, value = struct.unpack('<qQ', span(dynoff + 16 * index, 16))
        dynamic.append((tag, value))
        if tag == 0:
            break
    tags = dict(dynamic)
    strings = span(tags[5], tags[10])

    def string(offset):
        end = strings.find(b'\0', offset)
        return strings[offset:end].decode('utf-8', errors='replace')

    symoff = tags[6]
    if 4 in tags:
        _, nchain = struct.unpack('<II', span(tags[4], 8))
        symcount = nchain
    else:
        _, _, _, syms_size = struct.unpack_from('<IIII', raw, 0x90)
        symcount = syms_size // 24

    imports = set()
    for i in range(symcount):
        no, _, _, section, _, _ = struct.unpack('<IBBHQQ', span(symoff + 24 * i, 24))
        name = string(no)
        if name and section == 0:
            imports.add(name)
    return imports


class TestAudioOverrides(unittest.TestCase):
    def test_main_imported_symbols_audio(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        expected_audio_symbols = [
            # 1 with host override
            '_ZN2nn5audio12ListAudioInsEPNS0_11AudioInInfoEi',
            # 14 AudioIn functions
            '_ZN2nn5audio26InitializeAudioInParameterEPNS0_16AudioInParameterE',
            '_ZN2nn5audio11OpenAudioInEPNS0_7AudioInEPNS_2os11SystemEventEPKcRKNS0_16AudioInParameterE',
            '_ZN2nn5audio12StartAudioInEPNS0_7AudioInE',
            '_ZN2nn5audio11StopAudioInEPNS0_7AudioInE',
            '_ZN2nn5audio12CloseAudioInEPNS0_7AudioInE',
            '_ZN2nn5audio19AppendAudioInBufferEPNS0_7AudioInEPNS0_13AudioInBufferE',
            '_ZN2nn5audio24GetReleasedAudioInBufferEPNS0_7AudioInE',
            '_ZN2nn5audio20GetAudioInSampleRateEPKNS0_7AudioInE',
            '_ZN2nn5audio22GetAudioInChannelCountEPKNS0_7AudioInE',
            '_ZN2nn5audio22GetAudioInSampleFormatEPKNS0_7AudioInE',
            '_ZN2nn5audio20SetAudioInBufferInfoEPNS0_13AudioInBufferEPvmm',
            '_ZN2nn5audio27GetAudioInBufferDataPointerEPKNS0_13AudioInBufferE',
            '_ZN2nn5audio24GetAudioInBufferDataSizeEPKNS0_13AudioInBufferE',
            '_ZN2nn5audio38AcquireAudioDeviceNotificationForInputEPNS_2os11SystemEventE',
            # 14 AudioOut functions
            '_ZN2nn5audio27InitializeAudioOutParameterEPNS0_17AudioOutParameterE',
            '_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE',
            '_ZN2nn5audio13StartAudioOutEPNS0_8AudioOutE',
            '_ZN2nn5audio12StopAudioOutEPNS0_8AudioOutE',
            '_ZN2nn5audio13CloseAudioOutEPNS0_8AudioOutE',
            '_ZN2nn5audio20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE',
            '_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE',
            '_ZN2nn5audio21GetAudioOutSampleRateEPKNS0_8AudioOutE',
            '_ZN2nn5audio23GetAudioOutChannelCountEPKNS0_8AudioOutE',
            '_ZN2nn5audio23GetAudioOutSampleFormatEPKNS0_8AudioOutE',
            '_ZN2nn5audio21SetAudioOutBufferInfoEPNS0_14AudioOutBufferEPvmm',
            '_ZN2nn5audio28GetAudioOutBufferDataPointerEPKNS0_14AudioOutBufferE',
            '_ZN2nn5audio25GetAudioOutBufferDataSizeEPKNS0_14AudioOutBufferE',
            '_ZN2nn5audio17GetSampleByteSizeENS0_12SampleFormatE',
        ]
        self.assertEqual(len(expected_audio_symbols), 29)
        for sym in expected_audio_symbols:
            self.assertIn(sym, imports, f'Symbol {sym} missing from main imports')

    def test_audio_ipc_and_behavior_harness(self):
        if platform.system() != 'Darwin':
            self.skipTest('Core Audio / AudioToolbox is macOS only')
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'audio_overrides_test'
            cmd = [
                compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                f'-I{HERE / "runtime"}',
                str(HERE / 'tests/audio_overrides_test.c'),
                str(HERE / 'runtime/audio_out.c'),
                str(HERE / 'runtime/ipc.c'),
                str(HERE / 'runtime/missing.c'),
                '-lpthread',
                '-framework', 'AudioToolbox',
                '-framework', 'CoreFoundation',
                '-o', str(exe)
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            env = dict(os.environ, FC26_AUDIO='0')
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Audio harness failed:\n{run.stderr}\n{run.stdout}')
            self.assertIn('ALL_AUDIO_TESTS_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
