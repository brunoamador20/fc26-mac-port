"""Test the offline configuration generator (scripts/make_offline_config.py) with synthetic files."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import make_offline_config  # noqa: E402


SYNTHETIC_NXCERT = (
    "; EA SPORTS FC 26 Network Certification Profile (Synthetic test fixture)\r\n"
    "[ONLINE]\r\n"
    "BLAZEENV=PROD\r\n"
)

SYNTHETIC_MEMORY_INIT = (
    "# FIFA Memory Configuration File (Synthetic test fixture)\r\n"
    "AddArena.final.ps4.!Stomp.!asan\tRainyDayPP\t[default=DefaultHeap, coreSize=500M, allowGrow=0]\r\n"
    "AddArena.debug|release.nx.!Stomp.!asan\tRainyDayPP\t[default=DefaultHeap, coreSize=15M, coreReservationSize=0M, allowGrow=0]\r\n"
    "AddArena.otp.nx.!Stomp.!asan\tRainyDayPP\t[default=DefaultHeap, coreSize=53M coreReservationSize=0M, allowGrow=0]\r\n"
    "AddArena.final.nx.!Stomp.!asan\tRainyDayPP\t[default=DefaultHeap, coreSize=169M coreReservationSize=0M, allowGrow=0]\r\n"
    "AddArena.final.pc64.!Stomp.!asan\tRainyDayPP\t[default=DefaultHeap, coreSize=4M, allowGrow=0]\r\n"
    "AddArena.nx\tOnlinePP\t[default=DefaultHeap, coreSize=22M, allowGrow=1]\r\n"
    "AddArena.!nx\tOnlinePP\t[default=DefaultHeap, coreSize=16M, allowGrow=1]\r\n"
    "AddArena\tClientPP\t[default=DefaultHeap, coreSize=62M, allowGrow=0]\r\n"
)


class TestOfflineConfig(unittest.TestCase):

    def test_patch_nxcert_adds_confirmed_keys(self):
        mod_text, changes = make_offline_config.patch_nxcert(SYNTHETIC_NXCERT)
        self.assertIn('\r\n', mod_text)
        self.assertIn('BLAZEENV=PROD', mod_text)

        # Every confirmed key must be present in modified text
        for key, val, _ in make_offline_config.CONFIRMED_ONLINE_KEYS:
            self.assertIn(f'{key}={val}', mod_text)

        # 12 keys added
        self.assertEqual(len(changes), 12)
        added_keys = [c['key'] for c in changes]
        self.assertIn('KICKOFF_FORCE_OFFLINE', added_keys)
        self.assertIn('SINGLEMACHINE', added_keys)
        self.assertIn('USE_LOCALSERVER', added_keys)
        self.assertIn('NO_AUTO_SQUAD', added_keys)
        self.assertIn('PERFORM_PRE_LOGIN', added_keys)

    def test_patch_nxcert_updates_existing_keys(self):
        existing = (
            "[ONLINE]\r\n"
            "BLAZEENV=PROD\r\n"
            "KICKOFF_FORCE_OFFLINE=0\r\n"
            "PERFORM_PRE_LOGIN=1\r\n"
        )
        mod_text, changes = make_offline_config.patch_nxcert(existing)
        self.assertIn('KICKOFF_FORCE_OFFLINE=1', mod_text)
        self.assertNotIn('KICKOFF_FORCE_OFFLINE=0', mod_text)
        self.assertIn('PERFORM_PRE_LOGIN=0', mod_text)
        self.assertNotIn('PERFORM_PRE_LOGIN=1', mod_text)

        updated_changes = [c for c in changes if c['action'] == 'updated']
        self.assertEqual(len(updated_changes), 2)
        k_change = next(c for c in updated_changes if c['key'] == 'KICKOFF_FORCE_OFFLINE')
        self.assertEqual(k_change['original_value'], '0')
        self.assertEqual(k_change['new_value'], '1')

    def test_patch_nxcert_creates_section_if_missing(self):
        ini_without_online = "[GENERAL]\nVERSION=1\n"
        mod_text, changes = make_offline_config.patch_nxcert(ini_without_online)
        self.assertIn('[ONLINE]', mod_text)
        self.assertIn('KICKOFF_FORCE_OFFLINE=1', mod_text)
        self.assertEqual(len(changes), 12)

    def test_patch_memory_init_conservative_cuts(self):
        mod_text, changes = make_offline_config.patch_memory_init(SYNTHETIC_MEMORY_INIT)
        lines = mod_text.splitlines()

        # Check modified lines
        self.assertTrue(any('RainyDayPP' in l and '.final.nx' in l and 'coreSize=4M' in l for l in lines))
        self.assertTrue(any('RainyDayPP' in l and '.otp.nx' in l and 'coreSize=4M' in l for l in lines))
        self.assertTrue(any('RainyDayPP' in l and '.debug|release.nx' in l and 'coreSize=4M' in l for l in lines))
        self.assertTrue(any('OnlinePP' in l and 'AddArena.nx' in l and 'coreSize=1M' in l for l in lines))

        # Check untouched lines (ps4, pc64, !nx, ClientPP)
        self.assertTrue(any('RainyDayPP' in l and '.final.ps4' in l and 'coreSize=500M' in l for l in lines))
        self.assertTrue(any('RainyDayPP' in l and '.final.pc64' in l and 'coreSize=4M' in l for l in lines))
        self.assertTrue(any('OnlinePP' in l and 'AddArena.!nx' in l and 'coreSize=16M' in l for l in lines))
        self.assertTrue(any('ClientPP' in l and 'coreSize=62M' in l for l in lines))

        # Exactly 4 changes logged (3 RainyDayPP and 1 OnlinePP)
        self.assertEqual(len(changes), 4)
        c_final = next(c for c in changes if c['arena'] == 'RainyDayPP' and c['original_size'] == '169M')
        self.assertEqual(c_final['new_size'], '4M')
        c_online = next(c for c in changes if c['arena'] == 'OnlinePP')
        self.assertEqual(c_online['original_size'], '22M')
        self.assertEqual(c_online['new_size'], '1M')

    def test_generate_offline_package_loose_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            romfs = root / 'romfs'
            out = root / 'patches'

            nxcert_file = romfs / 'Data/nxcert.ini'
            mem_file = romfs / 'Scripts/BootIni/MemoryInit.ini'
            nxcert_file.parent.mkdir(parents=True)
            mem_file.parent.mkdir(parents=True)

            orig_nxcert_bytes = SYNTHETIC_NXCERT.encode('utf-8')
            orig_mem_bytes = SYNTHETIC_MEMORY_INIT.encode('utf-8')
            nxcert_file.write_bytes(orig_nxcert_bytes)
            mem_file.write_bytes(orig_mem_bytes)

            orig_nxcert_sha = hashlib.sha256(orig_nxcert_bytes).hexdigest()
            orig_mem_sha = hashlib.sha256(orig_mem_bytes).hexdigest()

            report = make_offline_config.generate_offline_package(romfs, out)
            self.assertEqual(report['status'], 'pass')

            manifest_path = out / 'manifest.tsv'
            self.assertTrue(manifest_path.is_file())
            manifest_lines = manifest_path.read_text(encoding='utf-8').splitlines()

            # Must have comment header + 2 file entries
            self.assertEqual(len(manifest_lines), 3)
            self.assertTrue(manifest_lines[0].startswith('#'))

            # Parse entries
            entries = {}
            for line in manifest_lines[1:]:
                parts = line.split('\t')
                self.assertEqual(len(parts), 4)
                path, size, sha, orig_sha = parts
                entries[path] = (int(size), sha, orig_sha)

            self.assertIn('Data/nxcert.ini', entries)
            self.assertIn('Scripts/BootIni/MemoryInit.ini', entries)

            # Validate original SHA-256 against actual original input
            self.assertEqual(entries['Data/nxcert.ini'][2], orig_nxcert_sha)
            self.assertEqual(entries['Scripts/BootIni/MemoryInit.ini'][2], orig_mem_sha)

            # Validate modified files on disk match the manifest
            mod_nxcert = (out / 'Data/nxcert.ini').read_bytes()
            self.assertEqual(entries['Data/nxcert.ini'][0], len(mod_nxcert))
            self.assertEqual(entries['Data/nxcert.ini'][1], hashlib.sha256(mod_nxcert).hexdigest())

            mod_mem = (out / 'Scripts/BootIni/MemoryInit.ini').read_bytes()
            self.assertEqual(entries['Scripts/BootIni/MemoryInit.ini'][0], len(mod_mem))
            self.assertEqual(entries['Scripts/BootIni/MemoryInit.ini'][1], hashlib.sha256(mod_mem).hexdigest())

    def test_generate_offline_package_romfs_image(self):
        """Test extraction from synthetic romfs.bin + index.json."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            romfs = root / 'romfs'
            romfs.mkdir(parents=True)
            out = root / 'patches'

            nxcert_data = SYNTHETIC_NXCERT.encode('utf-8')
            mem_data = SYNTHETIC_MEMORY_INIT.encode('utf-8')

            # Build a synthetic romfs.bin
            image_bytes = b'PADDING1234' + nxcert_data + b'PADDING5678' + mem_data
            (romfs / 'romfs.bin').write_bytes(image_bytes)

            nxcert_offset = len(b'PADDING1234')
            mem_offset = nxcert_offset + len(nxcert_data) + len(b'PADDING5678')

            index = {
                'status': 'pass',
                'files': [
                    {'path': 'Data/nxcert.ini', 'offset': nxcert_offset, 'size': len(nxcert_data)},
                    {'path': 'Scripts/BootIni/MemoryInit.ini', 'offset': mem_offset, 'size': len(mem_data)}
                ]
            }
            (romfs / 'index.json').write_text(json.dumps(index))

            report = make_offline_config.generate_offline_package(romfs, out)
            self.assertEqual(report['status'], 'pass')

            manifest_lines = (out / 'manifest.tsv').read_text().splitlines()
            self.assertEqual(len(manifest_lines), 3)

            nxcert_line = next(l for l in manifest_lines if l.startswith('Data/nxcert.ini'))
            _, _, _, orig_sha = nxcert_line.split('\t')
            self.assertEqual(orig_sha, hashlib.sha256(nxcert_data).hexdigest())

    def test_generate_offline_package_runtime_index_bin(self):
        """Test extraction from synthetic romfs.bin + runtime-index.bin (TOTKRFS1)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            romfs = root / 'romfs'
            romfs.mkdir(parents=True)
            out = root / 'patches'

            nxcert_data = SYNTHETIC_NXCERT.encode('utf-8')
            mem_data = SYNTHETIC_MEMORY_INIT.encode('utf-8')

            files = {
                'Data/nxcert.ini': nxcert_data,
                'Scripts/BootIni/MemoryInit.ini': mem_data
            }

            image, rows, strings = bytearray(), bytearray(), bytearray()
            for path in sorted(files):
                name = path.encode('utf-8') + b'\0'
                rows += struct.pack('<QQII', len(image), len(files[path]), len(strings), len(name))
                image += files[path]
                strings += name

            (romfs / 'romfs.bin').write_bytes(image)
            index_bytes = struct.pack('<8sQQ', b'TOTKRFS1', len(files), 24 + len(rows)) + rows + strings
            (romfs / 'runtime-index.bin').write_bytes(index_bytes)

            report = make_offline_config.generate_offline_package(romfs, out)
            self.assertEqual(report['status'], 'pass')
            self.assertTrue((out / 'manifest.tsv').is_file())


if __name__ == '__main__':
    unittest.main()
