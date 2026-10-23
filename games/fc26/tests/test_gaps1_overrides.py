"""Synthetic tests for gaps 1 overrides in FC 26 runtime:
- PlatformNvn:
    nn::vi::GetLatestFrameNumber
    nn::vi::ListFrameHistory
- main:
    nn::nifm::SubmitNetworkRequest
    nn::nifm::IsNetworkRequestOnHold
    nn::nifm::GetCurrentPrimaryIpAddress (in_addr)
    nn::err::ShowError (ErrorCode)
"""
from pathlib import Path
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import lz4.block

HERE = Path(__file__).resolve().parents[1]
# the main of the version the port runs (assets/game.json version_dir): the overrides must still match its imports
MAIN_NSO = (Path.home() / 'fc26-switch/work/extracted') / json.loads((HERE / 'assets/game.json').read_text())['version_dir'] / 'exefs/main'
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


class TestGaps1Overrides(unittest.TestCase):
    def test_main_imported_symbols_gaps1(self):
        if not MAIN_NSO.exists():
            self.skipTest(f'{MAIN_NSO} does not exist')
        imports = extract_dynsym_imports(MAIN_NSO)

        expected = [
            '_ZN2nn4nifm20SubmitNetworkRequestEv',
            '_ZN2nn4nifm22IsNetworkRequestOnHoldEv',
            '_ZN2nn4nifm26GetCurrentPrimaryIpAddressEP7in_addr',
            '_ZN2nn3err9ShowErrorENS0_9ErrorCodeE',
        ]
        for sym in expected:
            self.assertIn(sym, imports, f'{sym} not found in main imports')

    def test_platform_nvn_imported_symbols_gaps1(self):
        if not PLATFORM_NVN.exists():
            self.skipTest(f'{PLATFORM_NVN} does not exist')
        sys.path.insert(0, str(HERE / 'scripts'))
        import nro_to_nso

        data = PLATFORM_NVN.read_bytes()
        syms = nro_to_nso.module_symbols(data)
        imports = set(syms.get('imports', []))

        self.assertIn('_ZN2nn2vi16ListFrameHistoryEPNS0_9FrameInfoEiPKNS0_5LayerE', imports)
        self.assertIn('_ZN2nn2vi20GetLatestFrameNumberEPmPKNS0_5LayerE', imports)

    def test_gaps1_overrides_behavior_harness(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            exe = tmp_path / 'gaps1_overrides_test'
            cmd = [
                compiler, '-std=c11', '-Wall', '-Wextra',
                '-Wno-deprecated-declarations',
                '-fobjc-arc',
                f'-I{HERE / "runtime"}',
                f'-I{HERE / "third_party/d2r_gfx/gfx/nvn/include"}',
                str(HERE / 'tests/gaps1_overrides_test.c'),
                str(HERE / 'runtime/frontend.m'),
                str(HERE / 'runtime/system_services.c'),
                str(HERE / 'runtime/applet_host.c'),
                str(HERE / 'runtime/missing.c'),
                '-framework', 'Cocoa',
                '-framework', 'Metal',
                '-framework', 'QuartzCore',
                '-framework', 'CoreVideo',
                '-framework', 'CoreFoundation',
                '-lpthread',
                '-o', str(exe)
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed:\n{build.stderr}')

            env = dict(os.environ, TOTK_TEST_VI='1')
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, f'gaps1 harness failed:\n{run.stderr}\n{run.stdout}')
            self.assertIn('ALL_GAPS1_OVERRIDES_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
