"""Synthetic tests for the 9 nn::oe overrides in FC 26 runtime:
GetDefaultDisplayResolution, GetDefaultDisplayResolutionChangeEvent,
GetPerformanceConfiguration, GetPseudoDeviceId, GetDisplayVersion,
DisableScreenShot, EnterExitRequestHandlingSection,
LeaveExitRequestHandlingSection, GetNotificationMessageEvent.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import lz4.block

HERE = Path(__file__).resolve().parents[1]
MAIN_NSO = (Path.home() / 'fc26-switch/work/extracted/v100/exefs/main')
PLATFORM_NVN = (Path.home() / 'fc26-switch/work/nro/Engine.Render.Core2.PlatformNvn.nro')


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


class TestOeOverrides(unittest.TestCase):
    def test_main_imported_symbols_oe(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        expected_oe_symbols = [
            '_ZN2nn2oe17DisableScreenShotEv',
            '_ZN2nn2oe17GetDisplayVersionEPNS0_14DisplayVersionE',
            '_ZN2nn2oe17GetPseudoDeviceIdEPNS_4util4UuidE',
            '_ZN2nn2oe27GetDefaultDisplayResolutionEPiS1_',
            '_ZN2nn2oe27GetNotificationMessageEventEv',
            '_ZN2nn2oe27GetPerformanceConfigurationENS0_15PerformanceModeE',
            '_ZN2nn2oe31EnterExitRequestHandlingSectionEv',
            '_ZN2nn2oe31LeaveExitRequestHandlingSectionEv',
            '_ZN2nn2oe38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE',
        ]
        for sym in expected_oe_symbols:
            self.assertIn(sym, imports)

    def test_platform_nvn_imported_oe_symbols(self):
        if not PLATFORM_NVN.exists():
            self.skipTest(f'{PLATFORM_NVN} does not exist')
        sys.path.insert(0, str(HERE / 'scripts'))
        import nro_to_nso

        data = PLATFORM_NVN.read_bytes()
        syms = nro_to_nso.module_symbols(data)
        imports = set(syms.get('imports', []))

        self.assertIn('_ZN2nn2oe10InitializeEv', imports)
        self.assertIn('_ZN2nn2oe27GetDefaultDisplayResolutionEPiS1_', imports)
        self.assertIn('_ZN2nn2oe38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE', imports)

    def test_oe_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'oe_overrides_test'
            cmd = [
                compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                f'-I{HERE / "runtime"}',
                f'-I{HERE / "third_party/d2r_gfx/gfx/nvn/include"}',
                str(HERE / 'tests/oe_overrides_test.c'),
                str(HERE / 'runtime/services.c'),
                str(HERE / 'runtime/applet_host.c'),
                str(HERE / 'runtime/threads.c'),
                str(HERE / 'runtime/missing.c'),
                '-lpthread',
                '-framework', 'CoreFoundation',
                '-o', str(exe)
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            # 1. Run docked mode (default)
            prof1 = tmp_path / 'profile1'
            prof1.mkdir()
            env1 = dict(os.environ, TOTK_PROFILE_DIR=str(prof1), TOTK_OPERATION_MODE='docked')
            run1 = subprocess.run([str(exe)], capture_output=True, text=True, env=env1)
            self.assertEqual(run1.returncode, 0, f'Docked run failed:\n{run1.stderr}\n{run1.stdout}')
            self.assertIn('ALL_OE_OVERRIDES_OK', run1.stdout)

            # Check that uuid was written
            uuid_file = prof1 / 'pseudo_device.uuid'
            self.assertTrue(uuid_file.exists())
            uuid_bytes_run1 = uuid_file.read_bytes()
            self.assertEqual(len(uuid_bytes_run1), 16)

            # 2. Run a second "execution" with same profile: UUID must remain identical
            run1_again = subprocess.run([str(exe)], capture_output=True, text=True, env=env1)
            self.assertEqual(run1_again.returncode, 0)
            self.assertEqual(uuid_file.read_bytes(), uuid_bytes_run1)

            # 3. Run a third execution with a DIFFERENT profile: must get a new UUID
            prof2 = tmp_path / 'profile2'
            prof2.mkdir()
            env2 = dict(os.environ, TOTK_PROFILE_DIR=str(prof2), TOTK_OPERATION_MODE='docked')
            run2 = subprocess.run([str(exe)], capture_output=True, text=True, env=env2)
            self.assertEqual(run2.returncode, 0)
            uuid_bytes_run2 = (prof2 / 'pseudo_device.uuid').read_bytes()
            self.assertEqual(len(uuid_bytes_run2), 16)
            self.assertNotEqual(uuid_bytes_run1, uuid_bytes_run2)

            # 4. Run handheld mode
            prof3 = tmp_path / 'profile3'
            prof3.mkdir()
            env3 = dict(os.environ, TOTK_PROFILE_DIR=str(prof3), TOTK_OPERATION_MODE='handheld')
            run3 = subprocess.run([str(exe), '--handheld'], capture_output=True, text=True, env=env3)
            self.assertEqual(run3.returncode, 0, f'Handheld run failed:\n{run3.stderr}\n{run3.stdout}')
            self.assertIn('ALL_OE_OVERRIDES_OK', run3.stdout)


if __name__ == '__main__':
    unittest.main()
