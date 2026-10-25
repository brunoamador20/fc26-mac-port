"""Verification and behavioral tests for Story 5 host overrides:
OpenUser, ShowUserSelector, GetSupportedNpadStyleSet, InitializeGesture,
GetGestureStates, IsMounted, GetSaveDataSize, GetSaveDataSizeMax, ExtendSaveData,
ListAudioIns, and audin:u service.
"""
from pathlib import Path
import json
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
        if name and section == 0:  # st_shndx == 0 -> imported symbol
            imports.add(name)
    return imports


class TestHostOverridesE5(unittest.TestCase):
    def test_main_imported_symbols(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        # 1. OpenUser
        self.assertIn('_ZN2nn7account8OpenUserEPNS0_10UserHandleERKNS0_3UidE', imports)

        # 2. IsMounted
        self.assertIn('_ZN2nn2fs9IsMountedEPKc', imports)

        # 3. GetSaveDataSize / GetSaveDataSizeMax / ExtendSaveData
        self.assertIn('_ZN2nn2fs15GetSaveDataSizeEPlS1_RKNS_7account3UidE', imports)
        self.assertIn('_ZN2nn2fs18GetSaveDataSizeMaxEPlS1_', imports)
        self.assertIn('_ZN2nn2fs14ExtendSaveDataERKNS_7account3UidEll', imports)

        # 4. GetSupportedNpadStyleSet:
        # Notice: report had length 20 which was wrong; actual imported symbol has length 24
        self.assertNotIn('_ZN2nn3hid20GetSupportedNpadStyleSetEv', imports)
        self.assertIn('_ZN2nn3hid24GetSupportedNpadStyleSetEv', imports)

        # 5. ShowUserSelector
        self.assertIn('_ZN2nn7account16ShowUserSelectorEPNS0_3UidERKNS0_21UserSelectionSettingsE', imports)

        # 6. InitializeGesture / GetGestureStates
        self.assertIn('_ZN2nn3hid17InitializeGestureEv', imports)
        self.assertIn('_ZN2nn3hid16GetGestureStatesEPNS0_12GestureStateEi', imports)

        # 7. Audio input
        self.assertIn('_ZN2nn5audio12ListAudioInsEPNS0_11AudioInInfoEi', imports)
        self.assertIn('_ZN2nn5audio38AcquireAudioDeviceNotificationForInputEPNS_2os11SystemEventE', imports)

    def test_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'host_overrides_test'
            cmd = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                   f'-I{HERE / "runtime"}',
                   str(HERE / 'tests/host_overrides_e5.c'),
                   str(HERE / 'runtime/account.c'),
                   str(HERE / 'runtime/input.c'),
                   str(HERE / 'runtime/fs_host.c'),
                   str(HERE / 'runtime/system_services.c'), str(HERE / 'runtime/time_probe.c'),
                   str(HERE / 'runtime/ipc.c'),
                   str(HERE / 'runtime/missing.c'),
                   '-lpthread',
                   '-o', str(exe)]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'profile'
            prof.mkdir()
            env = dict(platform.os.environ, TOTK_PROFILE_DIR=str(prof))
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Execution failed:\n{run.stderr}')
            self.assertIn('ALL_OVERRIDES_OK', run.stdout)

    def test_no_host_override_for_audio_notification(self):
        # AcquireAudioDeviceNotificationForInput must not be overridden in host
        # so SDK routes through audin:u IPC command 4
        src = (HERE / 'runtime/system_services.c').read_text()
        self.assertNotIn('acquire_audio_device_notification_input', src)
        self.assertNotIn('_ZN2nn5audio38AcquireAudioDeviceNotificationForInputEPNS_2os11SystemEventE', src)

    def test_gesture_states_does_not_touch_buffer(self):
        # GestureState size is unproven: get_gesture_states must not write to output buffer
        src = (HERE / 'runtime/input.c').read_text()
        self.assertIn('get_gesture_states(void *out,int count){(void)out;(void)count;return 0;}', src)

    def test_audin_ipc_service(self):
        if platform.system() != 'Darwin':
            self.skipTest('Core Audio / AudioToolbox is macOS only')
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'audin_ipc_test'
            cmd = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                   f'-I{HERE / "runtime"}',
                   str(HERE / 'tests/ipc_audin_test.c'),
                   str(HERE / 'runtime/audio_out.c'),
                   str(HERE / 'runtime/ipc.c'),
                   str(HERE / 'runtime/missing.c'),
                   '-lpthread', '-framework', 'AudioToolbox', '-framework', 'CoreFoundation',
                   '-o', str(exe)]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'profile'
            prof.mkdir()
            env = dict(platform.os.environ, TOTK_PROFILE_DIR=str(prof))
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Execution failed:\n{run.stderr}')
            self.assertIn('AUDIN_IPC_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
