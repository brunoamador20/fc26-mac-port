"""Update import/packaging regressions. Synthetic bytes only, no game files or keys."""
import io
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_game_containers import (HEADER, AREA, TITLEKEK, CONTENT, SCRIPTS, TITLE,
                                  encrypt, nca, partition, ticket, game_image, romfs)
from cryptography.hazmat.primitives.ciphers import modes
from extract_exefs import decrypt, common_tickets, container_entries
from extract_update_romfs import merge
import build_app


def update_nca(managed=True):
    data = nca(managed)
    header = bytearray(b''.join(decrypt(HEADER, modes.XTS(i.to_bytes(16, 'big')),
                                     data[i*512:(i+1)*512]) for i in range(6)))
    header[0x604] = 4  # BKTR marker in section 1; these tests extract only ExeFS.
    import hashlib
    header[0x2a0:0x2c0] = hashlib.sha256(header[0x600:0x800]).digest()
    return b''.join(encrypt(HEADER, modes.XTS(i.to_bytes(16, 'big')), header[i*512:(i+1)*512])
                    for i in range(6)) + data[0xc00:]


class Updates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.keys = self.root/'prod.keys'
        self.keys.write_text('\n'.join(f'{n} = {k.hex()}' for n, k in
                            [('header_key', HEADER), ('key_area_key_application_00', AREA), ('titlekek_00', TITLEKEK)]))
        self.update = self.root/'update.nsp'
        self.update.write_bytes(partition([('program.nca', update_nca()), ('common.tik', ticket())]))

    def test_real_ticket_signature_byte_order(self):
        self.assertEqual(ticket()[:4], b'\x04\x00\x01\x00')
        raw = partition([('ticket.tik', ticket())])
        self.assertEqual(len(common_tickets(io.BytesIO(raw), container_entries(io.BytesIO(raw), len(raw))[1])), 1)
        bad = bytearray(ticket()); bad[:4] = b'\x00\x01\x00\x04'
        raw = partition([('ticket.tik', bad)])
        with self.assertRaisesRegex(ValueError, 'signature type'):
            common_tickets(io.BytesIO(raw), container_entries(io.BytesIO(raw), len(raw))[1])

    def test_update_exefs_and_base_rejection(self):
        out = self.root/'exefs'
        result = subprocess.run([sys.executable, SCRIPTS/'extract_exefs.py', self.update, '--update',
                                 '--keys', self.keys, '--output', out], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((out/'main').read_bytes(), b'synthetic main')
        base = self.root/'base.nsp'; base.write_bytes(game_image('nsp'))
        result = subprocess.run([sys.executable, SCRIPTS/'extract_exefs.py', base, '--update',
                                 '--keys', self.keys, '--output', self.root/'bad'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Expected a BKTR update', result.stderr)

    def test_wrong_version_stops_before_rewrite(self):
        tree = self.root/'tree'; tree.mkdir()
        (tree/'scripts').symlink_to(SCRIPTS, target_is_directory=True)
        (tree/'.venv').symlink_to(sys.prefix, target_is_directory=True)
        with patch.dict(build_app.UPDATED, {'exefs_sha256': {'main': build_app.UPDATED['exefs_sha256']['main']}}), self.assertRaisesRegex(build_app.BuildError, 'ExeFS main'):
            build_app.step_code(tree, self.update, self.keys, os.environ, self.root/'logs', version='v112')
        self.assertFalse((tree/'rewritten').exists())

    def test_merge_ticket_privacy_and_failure_cleanup(self):
        # A mock hactool verifies plumbing, not BKTR cryptography (covered by the real local build).
        space = patch('extract_update_romfs.shutil.disk_usage')
        space.start().return_value.free = 100 * 2**30
        self.addCleanup(space.stop)
        helper = self.root/'hactool'
        helper.write_text('#!'+sys.executable+'\n'+
            'import os,sys,pathlib,stat\n'
            'key=pathlib.Path(os.environ["MNG_TITLE_KEYS"])\n'
            'assert stat.S_IMODE(key.stat().st_mode)==0o600\n'
            'assert key.read_text() and not any("--titlekey=" in s for s in sys.argv)\n'
            'assert len(list(key.parent.glob("*.nca")))==2\n'
            'if os.environ.get("MNG_MOCK_FAIL"): raise SystemExit(1)\n'
            'out=pathlib.Path(next(s.split("=",1)[1] for s in sys.argv if s.startswith("--section")))\n'
            f'out.write_bytes({romfs()!r})\n'
            'for i in range(6): print(f"Level {i} (GOOD)")\n')
        helper.chmod(0o755)
        for kind in ('xci', 'nsp'):
            base = self.root/f'base.{kind}';base.write_bytes(game_image(kind, managed=kind=='nsp'))
            out = self.root/f'merged-{kind}'
            merge(base, self.update, self.keys, helper, out)
            self.assertEqual((out/'romfs.bin').read_bytes(), romfs())
            self.assertFalse(list(self.root.glob('update-merge-*')))
        with patch.dict(os.environ, MNG_MOCK_FAIL='1'), self.assertRaisesRegex(ValueError, 'BKTR verification failed'):
            merge(base, self.update, self.keys, helper, self.root/'failed')
        self.assertFalse((self.root/'failed').exists())
        self.assertFalse(list(self.root.glob('update-merge-*')))

    def test_bundle_contains_only_selected_game_version(self):
        tree=self.root/'tree';out=self.root/'Tears of the Kingdom.app'
        files=['build/totk-native-v112','build/pso_manifest.tsv','build/spirv-cross/spirv-cross',
               'prebuilt/macos-arm64/totk_xlate','build/app-launcher','extracted/v112/romfs/romfs.bin',
               'extracted/v112/romfs/runtime-index.bin']+[f'rewritten/v112/{n}.patched.bin' for n in ('main','sdk','subsdk0')]
        for rel in files:
            p=tree/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test')
        build_app.step_app(tree,out,self.root/'logs',version='v112')
        info=plistlib.loads((out/'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleShortVersionString'],'1.1.2')
        res=out/'Contents/Resources/totk'
        self.assertFalse((res/'rewritten/v0').exists())
        self.assertFalse((res/'build/totk-native-v112').exists())
        self.assertTrue((res/'build/totk-native').exists())
        self.assertTrue((res/'rewritten/v112/main.patched.bin').exists())


if __name__=='__main__': unittest.main()
