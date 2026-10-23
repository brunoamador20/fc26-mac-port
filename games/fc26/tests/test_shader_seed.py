"""Offline shader pre-translation (scripts/shader_seed.py, docs/SHADER_SEED.md): the key, file and variant names must be
the runtime's own, or the cache never hits. Checked against the real code: runtime/shader_cache.c (the key and the
journal file, through tests/shader_cache_check.c), Foundation's NSJSONSerialization (what totk_rt_variant names variants
with), runtime/oodle_tool.c (the decoder pipe, with a stand-in decoder at the offset). Synthetic data only."""
from pathlib import Path
import hashlib
import json
import os
import platform
import random
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import shader_seed  # noqa: E402

CONTROL_LEN = 0x880


def make_shader(seed, stage=1, code_len=0x200, c1=0x100, key_len_word=0):
    """A control section and code as Frostbite stores them: GLSLC magic, version 1, the words the runtime reads."""
    rnd = random.Random(seed)
    control = bytearray(rnd.randbytes(CONTROL_LEN))
    struct.pack_into('<II', control, 0, 0x98761234, 1)
    struct.pack_into('<I', control, 0x20, key_len_word)
    struct.pack_into('<II', control, 0x700, c1, code_len)
    struct.pack_into('<I', control, 0x714, stage)
    struct.pack_into('<3I', control, 0x748, 8, 4, 1)
    code = bytearray(rnd.randbytes(code_len))
    struct.pack_into('<I', code, 0, 0x12345679 if stage == 5 else 0x12345678)
    return bytes(control), bytes(code)


def compiler():
    return shutil.which('clang') or shutil.which('cc')


class Build:
    """tests/shader_cache_check.c over runtime/shader_cache.c, built once."""
    dir = exe = None

    @classmethod
    def get(cls):
        if cls.exe:
            return cls.exe
        cc = compiler()
        if not cc:
            raise unittest.SkipTest('A C compiler is required')
        cls.dir = tempfile.mkdtemp()
        cls.exe = Path(cls.dir) / 'shader_cache_check'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        run = subprocess.run([cc, *flags, f'-I{HERE / "runtime"}', str(HERE / 'tests/shader_cache_check.c'),
                              str(HERE / 'runtime/shader_cache.c'), '-o', str(cls.exe)], capture_output=True, text=True)
        if run.returncode:
            raise AssertionError(run.stdout + run.stderr)
        return cls.exe


class KeyAndFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, *args):
        run = subprocess.run([str(Build.get()), *map(str, args)], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout

    def test_key_is_the_runtimes(self):
        for i, case in enumerate([dict(), dict(key_len_word=0x7d1), dict(key_len_word=0x848), dict(key_len_word=0x900),
                                  dict(stage=5, c1=0), dict(stage=0, code_len=0x3700)]):
            control, code = make_shader(i, **case)
            (self.dir / 'c').write_bytes(control); (self.dir / 'k').write_bytes(code + b'past the code')
            with self.subTest(case=case):
                self.assertEqual(shader_seed.shader_key(control, code + b'past the code'), self.check('key', self.dir / 'c', self.dir / 'k').split()[1])

    def test_extracted_file_is_the_journals(self):
        control, code = make_shader(7, stage=0)
        key = shader_seed.shader_key(control, code)
        (self.dir / 'c').write_bytes(control); (self.dir / 'k').write_bytes(code)
        self.assertEqual(self.check('put', self.dir / 'j', key, 0, self.dir / 'c', self.dir / 'k').strip(), '1')
        self.assertEqual(shader_seed.journal_bytes(0, control, code), (self.dir / 'j' / f'{key}.shader').read_bytes())
        self.assertEqual(shader_seed.read_journal_shader(self.dir / 'j' / f'{key}.shader'), (0, control, code))


class VariantNames(unittest.TestCase):
    ANSWERS = [shader_seed.DEFAULT_ANSWERS,
               {'attr': {str(i): 'float' for i in range(12)}, 'fout': {'0': 'float', '1': 'uint'}, 'img': {'0': {'fmt': 'R11G11B10Float', 'type': '2darray'}},
                'tex': {'0': 'cube', '2': '2d', '10': '2d_depth', '9': 'cubearray', '100': 'buffer'}},
               {'variant': 'k-1', 'stage': 'cs', 'code': '/a/b c/k-1.code', 'c1': '00ff', 'local': [8, 8, 1], 'depth_minus_w': False,
                'tex': {}, 'img': {}, 'attr': {}, 'fout': {}}]

    def test_json_is_foundations(self):
        """totk_rt_variant names a variant by SHA-256 of NSJSONSerialization(answers, NSJSONWritingSortedKeys)."""
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            self.skipTest('Foundation is on the Mac')
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'j.m'
            src.write_text('''#import <Foundation/Foundation.h>
int main(int argc, char **argv) { @autoreleasepool {
    id o = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[1])] options:0 error:nil];
    NSData *d = [NSJSONSerialization dataWithJSONObject:o options:NSJSONWritingSortedKeys error:nil];
    fwrite(d.bytes, 1, d.length, stdout); } return 0; }''')
            run = subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-framework', 'Foundation', str(src), '-o', str(Path(d) / 'j')],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            for a in self.ANSWERS:
                (Path(d) / 'in.json').write_text(json.dumps(a))
                want = subprocess.run([str(Path(d) / 'j'), str(Path(d) / 'in.json')], capture_output=True, text=True).stdout
                self.assertEqual(shader_seed.ns_json(a), want)

    def test_variant_name(self):
        a = self.ANSWERS[1]
        self.assertEqual(shader_seed.variant_name('k' * 64, a), 'k' * 64 + '-' + hashlib.sha256(shader_seed.ns_json(a).encode()).hexdigest()[:12])
        self.assertEqual(shader_seed.ns_json({'tex': {'10': 'a', '9': 'b', '1': 'c'}}), '{"tex":{"1":"c","9":"b","10":"a"}}')

    def test_request_is_totk_rt_variants(self):
        control, code = make_shader(3, stage=1, code_len=0x400, c1=0x300)
        rq, body = shader_seed.request('v', 1, control, code, shader_seed.DEFAULT_ANSWERS, '/c/v.code')
        self.assertEqual(rq, dict(variant='v', stage='ps', code='/c/v.code', c1=code[0x300:0x400].hex(), tex={}, img={}, attr={}, fout={},
                                  depth_minus_w=False))
        self.assertEqual(body, code[0x30:0x400])   # graphics code without its 0x30-byte NVN header
        control, code = make_shader(4, stage=5, code_len=0x200, c1=0x180)
        rq, body = shader_seed.request('v', 5, control, code, shader_seed.DEFAULT_ANSWERS, '/c/v.code', depth_minus_w=True)
        self.assertEqual((rq['stage'], rq['local'], rq['depth_minus_w'], body), ('cs', [8, 4, 1], True, code[:0x200]))
        with self.assertRaises(ValueError):
            shader_seed.request('v', 3, *make_shader(5, stage=3), shader_seed.DEFAULT_ANSWERS, '/c/v.code')   # tessellation


def block(raw, kind):
    """A Frostbite block: big-endian raw size, kind, 0x70 | size bits 16-19, size bits 0-15, payload."""
    return struct.pack('>IBBH', len(raw) if kind == 0 else raw[0], kind, 0x70 | len(raw[1]) >> 16 if kind else 0x70 | len(raw) >> 16,
                       (len(raw[1]) if kind else len(raw)) & 0xffff) + (raw[1] if kind else raw)


class FakeOodle:
    """Payload b'\\x8c\\x0c' + n: the n-th registered raw block."""
    def __init__(self):
        self.blocks = []

    def add(self, raw):
        self.blocks.append(raw)
        return (len(raw), b'\x8c\x0c' + struct.pack('<I', len(self.blocks) - 1))

    def __call__(self, payload, size):
        raw = self.blocks[struct.unpack_from('<I', payload, 2)[0]]
        return raw if len(raw) == size else None


class Scan(unittest.TestCase):
    def test_shaders_found_across_blocks_and_noise(self):
        oodle, shaders, stream = FakeOodle(), [], bytearray()
        for i, stage in enumerate([0, 1, 5, 4]):
            control, code = make_shader(10 + i, stage=stage, code_len=0x300 + 0x100 * i)
            shaders.append((stage, control, code))
            stream += b'NVNV' + bytes(0x41) + code + control
        stream += make_shader(20)[0][:0x400]                 # a control section cut short: not a shader
        fake = bytearray(make_shader(21)[0]); fake[4] = 2     # GLSLC magic, other version
        stream += bytes(0x200) + fake
        cas = bytearray(struct.pack('>I', 0x20) + bytes(0x20))   # the catalogue at the start of a .cas
        parts = [bytes(stream[i:i + 0x1000]) for i in range(0, len(stream), 0x1000)]
        for n, part in enumerate(parts):
            cas += block(part, 0) if n % 3 == 0 else block(oodle.add(part), 0x19)
            if n == 2:
                cas += b'\x00\x01\x02 not a block'
        found = []
        stats = shader_seed.scan_buffer(memoryview(bytes(cas)), oodle, lambda *s: found.append(s), window=0x1800, tail=0x1000)
        self.assertEqual(stats['blocks'], len(parts))
        self.assertEqual(found, shaders)

    def test_block_header(self):
        self.assertEqual(shader_seed.block_header(block(b'abc', 0), 0, 11), (3, 0, 3))
        b = block((0x40000, b'\x8c\x0c' + bytes(0x10000)), 0x19)
        self.assertEqual(shader_seed.block_header(b, 0, len(b)), (0x40000, 0x19, 0x10002))
        bad = bytearray(b); bad[8] = 0x8b
        self.assertIsNone(shader_seed.block_header(bad, 0, len(bad)))       # not an Oodle stream header
        self.assertIsNone(shader_seed.block_header(b, 0, len(b) - 1))       # payload past the end
        self.assertIsNone(shader_seed.block_header(struct.pack('>IBBH', 4, 0, 0x70, 3) + b'abcd', 0, 12))   # raw sizes differ

    def test_find_oodle_decompress(self):
        image = bytearray(0x3000)
        name_at = 0x2010
        image[name_at - 1:name_at + 19] = b'\0OodleLZ_Decompress\0'
        struct.pack_into('<I', image, 0x400, 0xa9ba7bfd)                    # stp x29, x30, [sp, #-0x60]!
        pc, page = 0x440, (name_at & ~0xfff) - (0x440 & ~0xfff)
        imm = page >> 12
        struct.pack_into('<I', image, pc, 0x90000000 | (imm & 3) << 29 | (imm >> 2) << 5 | 0)   # adrp x0
        struct.pack_into('<I', image, pc + 4, 0x91000000 | (name_at & 0xfff) << 10)              # add x0, x0, #lo12
        self.assertEqual(shader_seed.find_oodle_decompress(bytes(image), 0x1000), 0x400)


@unittest.skipUnless(platform.machine() in ('arm64', 'aarch64'), 'the stand-in decoder is AArch64 code')
class Version(unittest.TestCase):
    """The scan reads the RomFS of the version the port runs (assets/game.json): since story H1 the update's merged image
    (extracted/v1638400/romfs, base Data/ + Patch/ in one romfs.bin), with its own extraction next to the base's."""

    def test_defaults_follow_game_json(self):
        version = json.loads((HERE / 'assets/game.json').read_text())['version_dir']
        self.assertEqual(version, 'v1638400')
        work = Path('/w')
        scan = shader_seed.parser(work).parse_args(['scan'])
        self.assertEqual(scan.romfs, work / 'extracted/v1638400/romfs')
        self.assertEqual(scan.rewritten, work / 'rewritten/v1638400')
        self.assertEqual(scan.out, work / 'shader-seed-fc26/v1638400')
        self.assertEqual(shader_seed.parser(work).parse_args(['coverage']).out, scan.out)

    def test_cas_files_from_the_index_of_that_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            romfs = Path(tmp)
            (romfs / 'romfs.bin').write_bytes(bytes(0x300))
            files = [{'path': 'Data/NX/a/cas_01.cas', 'offset': 0x100, 'size': 0x80},
                     {'path': 'Patch/NX/a/cas_01.cas', 'offset': 0x200, 'size': 0x40},
                     {'path': 'Patch/layout.toc', 'offset': 0x280, 'size': 0x10}]
            (romfs / 'index.json').write_text(json.dumps({'romfs_size': 0x300, 'files': files}))
            self.assertEqual(shader_seed.cas_files(romfs), [('Data/NX/a/cas_01.cas', 0x100, 0x80),
                                                            ('Patch/NX/a/cas_01.cas', 0x200, 0x40)])
            (romfs / 'index.json').write_text(json.dumps({'romfs_size': 0x400, 'files': files}))   # another image's index
            with self.assertRaises(SystemExit):
                shader_seed.cas_files(romfs)


class OodlePipe(unittest.TestCase):
    """runtime/oodle_tool.c with the Python client, a stand-in decoder at the offset (raw[i] = comp[i % n] ^ 0x5a; the
    stand-in fails a 7-byte request, as Oodle stops on bad data, to check the restart)."""
    STUB = r'''
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
extern uint8_t fake_decode[];
uint8_t *runtime_module_base(const char *name) { return (uint8_t *)fake_decode - 0x13d0 + 0 * (name != 0); }
void runtime_thread_init(void) {}
_Noreturn void runtime_fail(const char *m) { fprintf(stderr, "FAIL %s\n", m); exit(3); }
int main(void) { runtime_oodle_tool(); return 0; }
'''
    ASM = r'''
    .text
    .globl _fake_decode
    .globl fake_decode
    .p2align 2
_fake_decode:
fake_decode:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x1, #7
    b.ne 1f
    brk #0
1:  mov x8, #0
2:  cmp x8, x3
    b.ge 3f
    udiv x9, x8, x1
    msub x9, x9, x1, x8
    ldrb w10, [x0, x9]
    mov w11, #0x5a
    eor w10, w10, w11
    strb w10, [x2, x8]
    add x8, x8, #1
    b 2b
3:  mov x0, x3
    ldp x29, x30, [sp], #16
    ret
'''

    def test_round_trip_and_restart(self):
        cc = compiler()
        if not cc:
            self.skipTest('A C compiler is required')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'stub.c').write_text(self.STUB); (d / 'fake.S').write_text(self.ASM)
            exe = d / 'work/build/fc26-native'; exe.parent.mkdir(parents=True)
            run = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', f'-I{HERE / "runtime"}', str(d / 'stub.c'), str(d / 'fake.S'),
                                  str(HERE / 'runtime/oodle_tool.c'), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            (d / 'work/rewritten/v100').mkdir(parents=True)
            with open(d / 'log', 'wb') as log:
                o = shader_seed.Oodle(exe, d / 'work/rewritten/v100', 0x13d0, log)
                comp = bytes(range(1, 40))
                self.assertEqual(o.decompress(comp, 100), bytes(comp[i % len(comp)] ^ 0x5a for i in range(100)))
                self.assertIsNone(o.decompress(b'1234567', 10))
                self.assertEqual(o.restarts, 1)
                self.assertEqual(o.decompress(b'\x01\x02', 4), bytes([0x5b, 0x58, 0x5b, 0x58]))
                o.close()


FAKE_TRANSLATOR = r'''#!/usr/bin/env python3
import json, sys
out = sys.argv[sys.argv.index('--out') + 1]
for line in sys.stdin:
    rq = json.loads(line)
    v = rq['variant']
    if rq['stage'] == 'vs' and rq['attr'] == {}:
        print(json.dumps(dict(ok=False, error='no')), flush=True); continue
    open(f'{out}/{v}_b.metal', 'w').write('// ' + json.dumps(rq, sort_keys=True))
    json.dump(dict(deps={'tex': {'0': '2d'}}), open(f'{out}/{v}_b.json', 'w'))
    print(json.dumps(dict(ok=True)), flush=True)
'''


class Translate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        self.xlate = d / 'totk_xlate'; self.xlate.write_text(FAKE_TRANSLATOR); self.xlate.chmod(0o755)
        self.sc = d / 'spirv-cross'; self.sc.write_bytes(b'sc')
        self.cache = d / 'rt-x'; self.cache.mkdir()
        self.out = d / 'seed'; (self.out / 'shaders').mkdir(parents=True)
        self.keys = {}
        for i, stage in enumerate([1, 5, 0, 3]):
            control, code = make_shader(30 + i, stage=stage)
            key = shader_seed.shader_key(control, code); self.keys[stage] = key
            (self.out / 'shaders' / f'{key}.shader').write_bytes(shader_seed.journal_bytes(stage, control, code))

    def tearDown(self):
        self.tmp.cleanup()

    def stamp(self, translator=None):
        h = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        (self.cache / 'fc26-cache.id').write_text(f'fc26-shader-cache-identity 1\nchain x\ntranslator {translator or h(self.xlate)}\n'
                                                  f'spirv_cross {h(self.sc)}\nrequest kit-1\ndebug_mode default\ndepth_minus_w 0\n')

    def run_translate(self, *extra):
        return shader_seed.main(['translate', '--out', str(self.out), '--cache', str(self.cache), '--translator', str(self.xlate),
                                 '--spirv-cross', str(self.sc), '--chain', 'x', '--jobs', '2', *extra])

    def test_fills_cache_like_the_runtime(self):
        self.stamp()
        self.assertEqual(self.run_translate(), 1)                              # the vertex shader failed: exit 1
        for stage in (1, 5):
            key = self.keys[stage]; name = shader_seed.variant_name(key, shader_seed.DEFAULT_ANSWERS)
            self.assertEqual((self.cache / f'{key}.variants').read_text(),
                             '[{"deps":{"tex":{"0":"2d"}},"variant":"' + name + '"}]')
            rq = json.loads((self.cache / f'{name}_b.metal').read_text()[3:])
            self.assertEqual(rq['code'], str(self.cache / f'{name}.code'))
            self.assertTrue((self.cache / f'{name}.code').is_file())
        self.assertFalse(any(self.cache.glob(f'{self.keys[0]}*.variants')))   # the translator failed it: no index
        self.assertFalse(any(self.cache.glob(f'{self.keys[3]}*')))            # tessellation: not translatable
        before = {p.name: p.stat().st_mtime_ns for p in self.cache.iterdir()}
        self.assertEqual(self.run_translate(), 1)                              # nothing left but the failed one
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in self.cache.iterdir() if p.name in before and not p.name.startswith(self.keys[0])},
                         {k: v for k, v in before.items() if not k.startswith(self.keys[0])})

    def test_extraction_under_an_older_key_rule_is_keyed_by_its_bytes(self):
        """Files named by the key before +0x7d0..+0x7e7 was left out, and two records of one shader: one shader, new key."""
        shaders = self.out / 'shaders'
        for f in shaders.iterdir():
            f.unlink()
        control, code = make_shader(40, stage=1)
        twin = bytearray(control); twin[0x7d0:0x7e8] = bytes(0x18)
        for c in (control, bytes(twin)):
            old = hashlib.sha256(c + code[:shader_seed.code_length(c)]).hexdigest()
            (shaders / f'{old}.shader').write_bytes(shader_seed.journal_bytes(1, c, code))
        key = shader_seed.shader_key(control, code)
        self.assertEqual(list(shader_seed.extracted(shaders)), [key])
        self.stamp()
        self.assertEqual(self.run_translate(), 0)
        self.assertEqual(sorted(p.name for p in self.cache.glob('*.variants')), [f'{key}.variants'])
        journal = self.d / 'journal'; journal.mkdir()
        (journal / f'{"0" * 64}.shader').write_bytes(shader_seed.journal_bytes(1, bytes(twin), code))   # bound as the other record
        self.assertEqual(shader_seed.main(['coverage', '--out', str(self.out), '--journal', str(journal)]), 0)
        c2, k2 = make_shader(41, stage=1)
        (journal / f'{"1" * 64}.shader').write_bytes(shader_seed.journal_bytes(1, c2, k2))                 # not extracted
        self.assertEqual(shader_seed.main(['coverage', '--out', str(self.out), '--journal', str(journal)]), 1)

    def test_refuses_a_cache_the_runtime_would_empty(self):
        with self.assertRaises(SystemExit):
            self.run_translate()                                               # no identity
        self.stamp(translator='0' * 64)
        with self.assertRaises(SystemExit):
            self.run_translate()                                               # another translator's
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), ['fc26-cache.id'])

    def test_refuses_while_a_run_holds_the_lock(self):
        self.stamp()
        fd = shader_seed.lock_cache(self.cache)
        try:
            pid = os.fork()
            if pid == 0:
                try:
                    shader_seed.lock_cache(self.cache)
                    os._exit(0)
                except SystemExit:
                    os._exit(7)
            self.assertEqual(os.waitpid(pid, 0)[1] >> 8, 7)
        finally:
            os.close(fd)


if __name__ == '__main__':
    unittest.main()
