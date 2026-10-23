"""Synthetic tests for nn::hid overrides and controller/keyboard support in FC 26 runtime.
Validates all 38 nn::hid symbols imported by main, keyboard mappings, Npad styles,
ControllerSupport result layout, and safe vibration no-op overrides.
"""
from pathlib import Path
import json
import os
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


class TestInputOverrides(unittest.TestCase):
    def test_all_38_main_imported_symbols_hid(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        expected_hid_symbols = [
            '_ZN2nn3hid12GetNpadStateEPNS0_16NpadJoyDualStateERKj',
            '_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj',
            '_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyDualStateEiRKj',
            '_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyLeftStateEiRKj',
            '_ZN2nn3hid13GetNpadStatesEPNS0_17NpadHandheldStateEiRKj',
            '_ZN2nn3hid13GetNpadStatesEPNS0_17NpadJoyRightStateEiRKj',
            '_ZN2nn3hid13VibrationNode30DefaultVibrationSampleIntervalE',
            '_ZN2nn3hid13VibrationNode6UpdateEv',
            '_ZN2nn3hid14InitializeNpadEv',
            '_ZN2nn3hid14VibrationMixer10SetMixModeERKNS0_16VibrationMixModeE',
            '_ZN2nn3hid15GetNpadStyleSetERKj',
            '_ZN2nn3hid15VibrationPlayer4StopEv',
            '_ZN2nn3hid15VibrationPlayer6UnloadEv',
            '_ZN2nn3hid15VibrationPlayerC1Ev',
            '_ZN2nn3hid15VibrationPlayerD1Ev',
            '_ZN2nn3hid15VibrationTarget24SetVibrationDeviceHandleERKNS0_21VibrationDeviceHandleE',
            '_ZN2nn3hid15VibrationTargetC1Ev',
            '_ZN2nn3hid15VibrationTargetD1Ev',
            '_ZN2nn3hid15VibrationWriter5WriteERKNS0_14VibrationValueE',
            '_ZN2nn3hid15VibrationWriterC1Ev',
            '_ZN2nn3hid15VibrationWriterD1Ev',
            '_ZN2nn3hid16GetGestureStatesEPNS0_12GestureStateEi',
            '_ZN2nn3hid17InitializeGestureEv',
            '_ZN2nn3hid18SetNpadJoyHoldTypeENS0_15NpadJoyHoldTypeE',
            '_ZN2nn3hid19GetTouchScreenStateILm16EEEvPNS0_16TouchScreenStateIXT_EEE',
            '_ZN2nn3hid20ControllerSupportArg10SetDefaultEv',
            '_ZN2nn3hid21InitializeTouchScreenEv',
            '_ZN2nn3hid21ShowControllerSupportERKNS0_20ControllerSupportArgE',
            '_ZN2nn3hid22SetSupportedNpadIdTypeEPKjm',
            '_ZN2nn3hid23VibrationNodeConnection7ConnectEPNS0_13VibrationNodeES3_',
            '_ZN2nn3hid23VibrationNodeConnectionC1Ev',
            '_ZN2nn3hid23VibrationNodeConnectionD1Ev',
            '_ZN2nn3hid24GetSupportedNpadStyleSetEv',
            '_ZN2nn3hid24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE',
            '_ZN2nn3hid25GetVibrationDeviceHandlesEPNS0_21VibrationDeviceHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE',
            '_ZN2nn3hid25InitializeVibrationDeviceERKNS0_21VibrationDeviceHandleE',
            '_ZN2nn3hid29SetNpadHandheldActivationModeENS0_26NpadHandheldActivationModeE',
            '_ZNK2nn3hid15VibrationPlayer9IsPlayingEv',
        ]
        self.assertEqual(len(expected_hid_symbols), 38)
        for sym in expected_hid_symbols:
            self.assertIn(sym, imports, f'Symbol {sym} missing from main imports')

    def test_input_and_vibration_overrides_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'input_overrides_test'
            cmd = [
                compiler, '-std=c11', '-Wall', '-Wextra',
                '-Wno-deprecated-declarations',
                f'-I{HERE / "runtime"}',
                str(HERE / 'tests/input_overrides_test.c'),
                str(HERE / 'runtime/input.c'),
                str(HERE / 'runtime/hid_feedback.c'),
                '-lpthread',
                '-lm',
                '-o', str(exe)
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            for rumble_val in ['0', '1']:
                env = dict(os.environ, TOTK_RUMBLE=rumble_val)
                run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
                self.assertEqual(run.returncode, 0, f'Input harness failed (TOTK_RUMBLE={rumble_val}):\n{run.stderr}\n{run.stdout}')
                self.assertIn('ALL_INPUT_OVERRIDES_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
