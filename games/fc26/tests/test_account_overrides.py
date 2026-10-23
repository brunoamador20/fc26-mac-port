"""Synthetic tests for nn::account overrides in FC 26 runtime:
ListAllUsers, ListOpenUsers, IsNetworkServiceAccountAvailable,
LoadNetworkServiceLicenseInfoAsync, ShowLicenseRequirementsForNetworkService,
CreateNintendoAccountAuthorizationRequest, AsyncContext methods,
NintendoAccountAuthorizationRequestContext methods.
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


class TestAccountOverrides(unittest.TestCase):
    def test_main_imported_symbols_account(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        expected_symbols = [
            '_ZN2nn7account12ListAllUsersEPiPNS0_3UidEi',
            '_ZN2nn7account13ListOpenUsersEPiPNS0_3UidEi',
            '_ZN2nn7account32IsNetworkServiceAccountAvailableEPbRKNS0_10UserHandleE',
            '_ZN2nn7account34LoadNetworkServiceLicenseInfoAsyncEPNS0_37AsyncNetworkServiceLicenseInfoContextERKNS0_10UserHandleE',
            '_ZN2nn7account40ShowLicenseRequirementsForNetworkServiceERKNS0_10UserHandleE',
            '_ZN2nn7account41CreateNintendoAccountAuthorizationRequestEPNS0_42NintendoAccountAuthorizationRequestContextERKNS0_10UserHandleERKNS0_45NintendoAccountAuthorizationRequestParametersEPvm',
            '_ZN2nn7account12AsyncContext14GetSystemEventEPNS_2os11SystemEventE',
            '_ZN2nn7account12AsyncContext6CancelEv',
            '_ZN2nn7account12AsyncContext7HasDoneEPb',
            '_ZN2nn7account12AsyncContext9GetResultEv',
            '_ZN2nn7account37AsyncNetworkServiceLicenseInfoContext28GetNetworkServiceLicenseKindEv',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContext14GetSystemEventEPNS_2os11SystemEventE',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContext6CancelEv',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContext34GetResultWithInteractionIfRequiredEv',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContext20GetAuthorizationCodeEPmPcm',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContext8GetStateEPmPcm',
            '_ZN2nn7account12AsyncContextC1Ev',
            '_ZN2nn7account37AsyncNetworkServiceLicenseInfoContextC1Ev',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContextC1Ev',
            '_ZN2nn7account42NintendoAccountAuthorizationRequestContextD1Ev',
        ]
        for sym in expected_symbols:
            self.assertIn(sym, imports)

    def test_account_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'account_overrides_test'
            cmd = [
                compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                f'-I{HERE / "runtime"}',
                f'-I{HERE / "third_party/d2r_gfx/gfx/nvn/include"}',
                str(HERE / 'tests/account_overrides_test.c'),
                str(HERE / 'runtime/account.c'),
                str(HERE / 'runtime/missing.c'),
                '-lpthread',
                '-o', str(exe)
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            prof = tmp_path / 'profile'
            prof.mkdir()
            env = dict(os.environ, TOTK_PROFILE_DIR=str(prof))
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'Run failed:\n{run.stderr}\n{run.stdout}')
            self.assertIn('ALL_ACCOUNT_OVERRIDES_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
