"""Shader preparation uses local game containers; seed import preserves user variants."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'games/totk/scripts/prepare_shader_seed.py'
spec = importlib.util.spec_from_file_location('prepare_shader_seed', SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def bnsh():
    b = bytearray(0x3000)
    b[:4] = b'BNSH'; b[12:14] = b'\xff\xfe'; b[96:100] = b'grsc'
    struct.pack_into('<I', b, 28, len(b))
    struct.pack_into('<IQ', b, 124, 1, 0xc0)
    struct.pack_into('<Q', b, 0xc0+16, 0x100)
    for i, (stage, rel) in enumerate([(0, 8), (1, 40), (5, 48)]):
        header, control, code = 0x200+i*64, 0x400+i*0x880, 0x2000+i*0x100
        struct.pack_into('<Q', b, 0x100+rel, header)
        struct.pack_into('<QQII', b, header+8, control, code, 0x100, 0x880)
        struct.pack_into('<II', b, control+0x700, 0x80, 0x100)
        struct.pack_into('<I', b, control+0x714, stage)
        struct.pack_into('<III', b, control+0x748, 8, 8, 1)
        b[code:code+0x100] = bytes([i+1])*0x100
    return b


class ShaderInventory(unittest.TestCase):
    def test_actual_stage_offsets_and_runtime_hash_contract(self):
        rows = list(seed.bnsh_shaders(bnsh()))
        self.assertEqual([r[1] for r in rows], ['vs', 'ps', 'cs'])
        for key, _, control, code in rows:
            self.assertEqual(key, hashlib.sha256(control+code).hexdigest())

    def test_truncated_and_out_of_range_container_is_rejected(self):
        for data in [bnsh()[:-1], bnsh()]:
            if len(data) == 0x3000:
                struct.pack_into('<Q', data, 0xc0+16, 0x2fff)
            with self.assertRaises(ValueError):
                list(seed.bnsh_shaders(data))


@unittest.skipUnless(shutil.which('xcrun'), 'native Foundation importer is Mac-only')
class ShaderImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        source = cls.root/'probe.m'
        source.write_text('''#import "totk_shader_seed.h"
int main(int argc, const char **argv) { @autoreleasepool {
 NSError *error = nil; NSDictionary *r = nil;
 if (argc == 4 && !strcmp(argv[1], "--fill")) r = totk_fill_import(@(argv[2]), @(argv[3]));
 else if (argc == 3) r = totk_seed_import(@(argv[1]), @(argv[2]), &error);
 else return 2;
 if (!r) { fprintf(stderr, "%s\\n", error.localizedDescription.UTF8String); return 1; }
 NSData *d = [NSJSONSerialization dataWithJSONObject:r options:0 error:nil];
 puts([[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding].UTF8String); return 0;
} }
''')
        cls.binary = cls.root/'probe'
        subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                        '-Wno-deprecated-declarations', '-I'+str(ROOT/'games/totk/third_party/d2r_gfx/gfx/nvn'),
                        str(source), '-framework', 'Foundation', '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, root):
        source, cache = root/'seed', root/'cache'
        source.mkdir(); cache.mkdir()
        key, variant = 'a'*64, 'a'*64+'-'+'b'*12
        files = {variant+'_b.metal': b'// synthetic shader', variant+'_b.json': b'{}',
                 key+'.variants': json.dumps([dict(variant=variant, deps={})]).encode(),
                 'pso_manifest.tsv': ('S\t'+variant+'_b\t0\n').encode()}
        for name, data in files.items():
            (source/name).write_bytes(data)
        manifest = dict(schema=1, chain=seed.CHAIN, shaders=1,
                        files={n: hashlib.sha256(d).hexdigest() for n, d in files.items()})
        (source/'seed-manifest.json').write_text(json.dumps(manifest))
        return source, cache, key, variant

    def run_probe(self, source, cache, good=True, fill=False):
        r = subprocess.run([str(self.binary)]+(['--fill'] if fill else [])+[str(source), str(cache)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0 if good else 1, r.stderr)
        return json.loads(r.stdout) if good else r.stderr

    def test_first_import_reuse_and_preservation_of_user_variants(self):
        with tempfile.TemporaryDirectory() as folder:
            source, cache, key, variant = self.fixture(Path(folder))
            user = dict(variant=key+'-'+'c'*12, deps={'tex': {'0': '2d_array'}})
            (cache/(key+'.variants')).write_text(json.dumps([user]))
            (cache/'unrelated.txt').write_text('keep')
            r = self.run_probe(source, cache)
            self.assertGreater(r['imported_files'], 0)
            self.assertEqual(json.loads((cache/(key+'.variants')).read_text()), [user, dict(variant=variant, deps={})])
            self.assertEqual(self.run_probe(source, cache)['imported_files'], 0)
            (cache/(variant+'_b.metal')).unlink()
            self.assertGreater(self.run_probe(source, cache)['imported_files'], 0)
            self.assertEqual((cache/'unrelated.txt').read_text(), 'keep')

    def test_reprepared_seed_with_the_same_files_is_not_checked_again(self):
        # Packaging again writes a new preparation time and script hash into the manifest; the files stay the same.
        with tempfile.TemporaryDirectory() as folder:
            source, cache, key, variant = self.fixture(Path(folder))
            self.run_probe(source, cache)
            p = source/'seed-manifest.json'; m = json.loads(p.read_text())
            m['seconds'] = 12.5; m['preparation_sha256'] = 'f'*64
            p.write_text(json.dumps(m))
            (source/(variant+'_b.metal')).write_text('corrupt')   # only a check of the sources would notice
            self.assertEqual(self.run_probe(source, cache)['imported_files'], 0)

    def test_a_changed_file_table_is_checked_again(self):
        with tempfile.TemporaryDirectory() as folder:
            source, cache, key, variant = self.fixture(Path(folder))
            self.run_probe(source, cache)
            p = source/'seed-manifest.json'; m = json.loads(p.read_text())
            extra = key+'-'+'e'*12+'_b.metal'
            (source/extra).write_bytes(b'// new shader')
            m['files'][extra] = hashlib.sha256(b'// new shader').hexdigest(); m['shaders'] = 2
            p.write_text(json.dumps(m))
            (source/(variant+'_b.metal')).write_text('corrupt')   # caught because every source is checked again
            self.run_probe(source, cache, good=False)

    def test_wrong_chain_corruption_and_path_traversal_are_rejected(self):
        for mutation in ['chain', 'hash', 'path']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                source, cache, key, variant = self.fixture(Path(folder))
                p = source/'seed-manifest.json'; m = json.loads(p.read_text())
                if mutation == 'chain': m['chain'] = 'other-chain'
                elif mutation == 'hash': (source/(variant+'_b.metal')).write_text('corrupt')
                else: m['files']['../escape'] = '0'*64
                p.write_text(json.dumps(m))
                self.run_probe(source, cache, good=False)
                self.assertEqual(list(cache.iterdir()), [])

    def test_fill_packs_merge_without_touching_the_seed_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, cache, key, variant = self.fixture(root)
            self.run_probe(source, cache)
            receipt = (cache/'seed-installed.json').read_text()
            fills = root/'fills'; fills.mkdir()
            pack = fills/'20261018-1'; pack.mkdir()
            filled = key+'-'+'d'*12
            files = {filled+'_b.metal': b'// filled', filled+'_b.json': b'{}', filled+'_b.metallib': b'lib',
                     key+'.variants': json.dumps([dict(variant=filled, deps={'tex': {'1': 'cube'}})]).encode()}
            for name, data in files.items():
                (pack/name).write_bytes(data)
            (pack/'seed-manifest.json').write_text(json.dumps(dict(schema=1, chain=seed.CHAIN, shaders=1,
                files={n: hashlib.sha256(d).hexdigest() for n, d in files.items()})))
            r = self.run_probe(fills, cache, fill=True)
            self.assertEqual((r['packs'], r['rejected']), (1, []))
            self.assertEqual([v['variant'] for v in json.loads((cache/(key+'.variants')).read_text())], [variant, filled])
            self.assertEqual((cache/(filled+'_b.metallib')).read_bytes(), b'lib')
            self.assertEqual((cache/'seed-installed.json').read_text(), receipt)
            self.assertEqual(list(fills.iterdir()), [])

    def test_a_rebuilt_metallib_replaces_the_cached_one(self):
        # iOS metallibs once compiled with Metal's default fast math must be replaced by the safe-math rebuild; the
        # sources next to them are still kept as they are.
        with tempfile.TemporaryDirectory() as folder:
            source, cache, key, variant = self.fixture(Path(folder))
            lib = variant+'_b.metallib'
            (cache/lib).write_bytes(b'fast-math lib'); (cache/(variant+'_b.metal')).write_bytes(b'// collected here')
            (source/lib).write_bytes(b'safe-math lib')
            p = source/'seed-manifest.json'; m = json.loads(p.read_text())
            m['files'][lib] = hashlib.sha256(b'safe-math lib').hexdigest(); p.write_text(json.dumps(m))
            self.run_probe(source, cache)
            self.assertEqual((cache/lib).read_bytes(), b'safe-math lib')
            self.assertEqual((cache/(variant+'_b.metal')).read_bytes(), b'// collected here')

    def test_incomplete_fill_pack_is_dropped_without_changing_the_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, cache, key, variant = self.fixture(root)
            fills = root/'fills'
            shutil.copytree(source, fills/'partial')
            (fills/'partial'/(variant+'_b.json')).unlink()   # an interrupted push
            r = self.run_probe(fills, cache, fill=True)
            self.assertEqual((r['packs'], len(r['rejected'])), (0, 1))
            self.assertEqual(list(cache.iterdir()), [])
            self.assertEqual(list(fills.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
