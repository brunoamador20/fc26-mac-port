"""The FC 26 shader cache layer's plain-C logic (runtime/shader_cache.c, docs/SHADERS_NUVEM.md): SHA-256 and the shader
key as the graphics layer computes it, the identity that empties a cache made by another translator, the journal of the
shaders the game handed NVN, the size limit (least recently used first) and the lock. Built with tests/shader_cache_check.c;
runs on Linux and on the Mac, with synthetic shaders and folders only (no game data)."""
from pathlib import Path
import hashlib
import os
import platform
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
CONTROL_LEN = 0x880


def make_shader(seed, stage=1, code_len=0x200, c1=0x100, key_len_word=0):
    """A synthetic control section and code: random bytes with the words the layer reads set."""
    rnd = random.Random(seed)
    control = bytearray(rnd.randbytes(CONTROL_LEN))
    struct.pack_into('<I', control, 0x20, key_len_word)
    struct.pack_into('<II', control, 0x700, c1, code_len)
    struct.pack_into('<I', control, 0x714, stage)
    return bytes(control), rnd.randbytes(code_len + 64)   # bytes past the length are not the shader's


def expected_key(control, code):
    """nvn_mtl.m prog_get: SHA-256(control[:ctl_key_len] without +0x7d0..+0x7e7 + code[:u32 at control+0x704])."""
    n = struct.unpack_from('<I', control, 0x20)[0]
    n = n if 0x7cc <= n < 0x880 else 0x880
    return hashlib.sha256(control[:min(n, 0x7d0)] + control[0x7e8:n] + code[:struct.unpack_from('<I', control, 0x704)[0]]).hexdigest()


def old_key(control, code):
    """The key before +0x7d0..+0x7e7 was left out (journals written then are named by it)."""
    return hashlib.sha256(control + code[:struct.unpack_from('<I', control, 0x704)[0]]).hexdigest()


class ShaderCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        cls.build = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.build.name) / 'shader_cache_check'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        run = subprocess.run([compiler, *flags, f'-I{HERE / "runtime"}', str(HERE / 'tests/shader_cache_check.c'),
                              str(HERE / 'runtime/shader_cache.c'), '-o', str(cls.exe)], capture_output=True, text=True)
        if run.returncode:
            cls.build.cleanup()
            raise AssertionError(run.stdout + run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, *args, stdin=None):
        run = subprocess.run([str(self.exe), *map(str, args)], capture_output=True, text=True, timeout=60, input=stdin)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout

    def write(self, name, data):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    # ---------- SHA-256 and the key ----------
    def test_sha256_matches_hashlib_at_every_block_boundary(self):
        rnd = random.Random(7)
        for size in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000, 100_003]:
            data = rnd.randbytes(size)
            path = self.write(f'd{size}', data)
            for chunk in [1, 7, 64, 4096]:
                with self.subTest(size=size, chunk=chunk):
                    self.assertEqual(self.run_check('sha256', path, chunk).strip(), hashlib.sha256(data).hexdigest())

    def test_shader_key_is_the_graphics_layers(self):
        cases = [dict(key_len_word=0), dict(key_len_word=0x7d1), dict(key_len_word=0x848), dict(key_len_word=0x7cc),
                 dict(key_len_word=0x7cb), dict(key_len_word=0x880), dict(key_len_word=0x900), dict(stage=5, c1=0)]
        for i, case in enumerate(cases):
            control, code = make_shader(i, **case)
            with self.subTest(case=case):
                out = self.run_check('key', self.write('c', control), self.write('k', code)).split()
                w = case.get('key_len_word', 0)
                self.assertEqual(int(out[0]), w if 0x7cc <= w < 0x880 else 0x880)
                self.assertEqual(out[1], expected_key(control, code))

    def test_bytes_past_the_code_length_do_not_change_the_key(self):
        control, code = make_shader(3)
        a = self.run_check('key', self.write('c', control), self.write('k1', code))
        b = self.run_check('key', self.write('c', control), self.write('k2', code[:0x200] + bytes(64)))
        self.assertEqual(a, b)

    def test_record_identifier_does_not_change_the_key(self):
        """control+0x7d0..+0x7e7: the game binds the section of another record that differs only there."""
        for word in (0, 0x7d1):
            control, code = make_shader(4, key_len_word=word)
            key = self.run_check('key', self.write('c', control), self.write('k', code))
            for at in range(0x7d0, 0x7e8):
                other = bytearray(control); other[at] ^= 0x5a
                with self.subTest(word=word, at=hex(at)):
                    self.assertEqual(self.run_check('key', self.write('c2', bytes(other)), self.write('k', code)), key)
            for at in (0x7cf, 0x7e8):   # the neighbours still count (within the hashed length)
                other = bytearray(control); other[at] ^= 0x5a
                with self.subTest(word=word, at=hex(at)):
                    same = self.run_check('key', self.write('c2', bytes(other)), self.write('k', code)) == key
                    self.assertEqual(same, word == 0x7d1 and at == 0x7e8)

    def test_implausible_code_length_has_no_key(self):
        for length in [0, (16 << 20) + 1]:
            control = bytearray(CONTROL_LEN)
            struct.pack_into('<I', control, 0x704, length)
            with self.subTest(length=length):
                self.assertTrue(self.run_check('key', self.write('c', bytes(control)), self.write('k', b'x')).endswith('invalid\n'))

    def test_names(self):
        key = 'ab' * 32
        self.assertEqual(self.run_check('names', key), f'is_key 1\nvariant -\nfile 0 -\n')
        self.assertEqual(self.run_check('names', key + '-0123456789ab'), f'is_key 0\nvariant {key}\nfile 1 {key}\n')
        self.assertEqual(self.run_check('names', key + '.variants'), f'is_key 0\nvariant -\nfile 1 {key}\n')
        for bad in ['AB' * 32, 'ab' * 31, key + '_b.metal', key + '.', 'pso_collected.tsv']:
            with self.subTest(bad=bad):
                self.assertEqual(self.run_check('names', bad), 'is_key 0\nvariant -\nfile 0 -\n')
        for other in [key + '-0123456789AB', key + '-0123']:   # not a variant name, still one of the shader's files
            with self.subTest(other=other):
                self.assertEqual(self.run_check('names', other), f'is_key 0\nvariant -\nfile 1 {key}\n')

    # ---------- identity ----------
    FIELDS = ['schema', 'chain', 'translator', 'spirv_cross', 'request', 'debug_mode', 'depth_minus_w']
    BASE = ['1', 'totk-native-v4-unverified', 'a' * 64, 'b' * 64, 'kit-1', 'default', '0']

    def identity(self, name, values):
        path = self.dir / name
        self.assertEqual(self.run_check('id-write', path, *values).strip(), '0')
        return path

    def test_identity_round_trip(self):
        path = self.identity('id', self.BASE)
        self.assertEqual(self.run_check('id-read', path).split(), self.BASE)
        self.assertTrue(path.read_text().startswith('fc26-shader-cache-identity 1\n'))

    def test_identity_names_the_first_field_that_differs(self):
        a = self.identity('a', self.BASE)
        self.assertEqual(self.run_check('id-diff', a, a).strip(), 'same')
        changed = ['2', 'totk-native-v5', 'c' * 64, 'd' * 64, 'kit-2', '1', '1']
        for i, name in enumerate(self.FIELDS):
            values = list(self.BASE)
            values[i] = changed[i]
            with self.subTest(field=name):
                self.assertEqual(self.run_check('id-diff', a, self.identity('b', values)).strip(), name)

    def test_identity_missing_or_damaged(self):
        self.assertEqual(self.run_check('id-read', self.dir / 'none').strip(), 'missing')
        good = self.identity('good', self.BASE).read_text()
        for text in ['', 'garbage\n', good.replace('fc26-shader-cache-identity', 'other'), good.replace('chain ', 'chian '),
                     good.replace('depth_minus_w 0', 'depth_minus_w 2'), '\n'.join(good.splitlines()[:-1]) + '\n',
                     good + 'extra field\n']:
            with self.subTest(text=text[:40]):
                self.assertEqual(self.run_check('id-read', self.write('bad', text.encode())).strip(), 'invalid')

    def test_identity_refuses_values_on_two_lines(self):
        values = list(self.BASE)
        values[5] = 'a\nb'
        self.assertEqual(self.run_check('id-write', self.dir / 'id', *values).strip(), '-1')
        self.assertFalse((self.dir / 'id').exists())

    def test_concurrent_atomic_writes_do_not_collide_tmp_names(self):
        path = self.dir / 'concurrent.id'
        self.assertEqual(self.run_check('concurrent-id-write', path, 8, 50).strip(), 'failures 0')
        self.assertTrue(path.exists())
        self.assertEqual(self.run_check('id-read', path).split(),
                         ['1', 'chain', '0123456789abcdef' * 4, '0123456789abcdef' * 4, 'kit-1', 'default', '0'])

    # ---------- discarding a cache of another identity ----------
    def cache_files(self, folder, key, variants=('0123456789ab',)):
        names = [f'{key}.variants'] + [f'{key}-{v}{s}' for v in variants for s in ('.code', '_b.metal', '_b.json', '.spv', '.res.json')]
        for name in names:
            self.write(f'{folder}/{name}', b'x' * 10)
        return names

    def test_discard_keeps_the_warm_list_and_unknown_files(self):
        self.cache_files('rt', 'a' * 64)
        self.cache_files('rt', 'b' * 64, ('0123456789ab', 'ba9876543210'))
        for keep in ['pso_collected.tsv', 'fc26-cache.id', 'notes.txt']:
            self.write(f'rt/{keep}', b'k')
        self.write('rt/seed-installed.json', b'{}')
        (self.dir / 'rt/sub').mkdir()
        self.assertEqual(self.run_check('discard', self.dir / 'rt').strip(), str(6 + 11 + 1))
        self.assertEqual(sorted(p.name for p in (self.dir / 'rt').iterdir()), ['fc26-cache.id', 'notes.txt', 'pso_collected.tsv', 'sub'])
        self.assertEqual(self.run_check('discard', self.dir / 'missing').strip(), '-1')

    def test_hard_linked_variant_handled_by_scan_and_discard(self):
        key = 'c' * 64
        v1 = f'{key}-0123456789ab'
        v2 = f'{key}-ba9876543210'
        metal1 = self.write(f'rt/{v1}_b.metal', b'metal-code')
        metal2 = self.dir / f'rt/{v2}_b.metal'
        os.link(metal1, metal2)
        self.write(f'rt/{key}.variants', b'[]')
        out = self.run_check('scan', self.dir / 'rt', self.dir / 'none').splitlines()
        self.assertTrue(any(line.startswith(key) for line in out))
        self.assertEqual(self.run_check('discard', self.dir / 'rt').strip(), '3')
        self.assertFalse(metal1.exists())
        self.assertFalse(metal2.exists())

    def test_old_chains_go_only_when_stamped_and_free(self):
        def identity(chain):
            return (f'fc26-shader-cache-identity 1\nchain {chain}\ntranslator {"a" * 64}\nspirv_cross {"b" * 64}\n'
                    'request kit-1\ndebug_mode default\ndepth_minus_w 0\n').encode()
        for name in ['rt-current', 'rt-old', 'rt-foreign', 'rt-busy', 'rt-sibling', 'rt-stamp']:
            self.cache_files(name, 'c' * 64)
            self.write(f'{name}/pso_collected.tsv', b'S\tx\t0\n')
        for name in ['rt-current', 'rt-sibling']:
            self.write(f'{name}/fc26-cache.id', identity('cur-chain'))
        for name in ['rt-old', 'rt-busy']:
            self.write(f'{name}/fc26-cache.id', identity('older-chain'))
        self.write('rt-stamp/fc26-cache.id', b'stamp')
        self.write('rt-old-file', b'not a folder')
        holder = subprocess.Popen([str(self.exe), 'lock', str(self.dir / 'rt-busy')], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            # Only a folder stamped with another chain goes. A folder of the same chain under another name (an agent's
            # route with its own TOTK_SHADER_CACHE next to the player's) is a parallel cache, never an older one: on
            # 25/10 such a sibling (rt-carreira) removed the player's rt-update.
            self.assertEqual(self.run_check('old-chains', self.dir, 'rt-current', 'cur-chain').strip(), '1')
        finally:
            holder.stdin.close()
            holder.wait(timeout=30)
        self.assertFalse((self.dir / 'rt-old').exists())
        for name in ['rt-current', 'rt-sibling', 'rt-stamp', 'rt-foreign', 'rt-busy']:
            self.assertTrue((self.dir / name).is_dir(), name)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['rt-busy', 'rt-current', 'rt-foreign', 'rt-old-file', 'rt-sibling', 'rt-stamp'])
        self.assertTrue((self.dir / 'rt-foreign/pso_collected.tsv').exists())

    # ---------- journal ----------
    def put(self, journal, seed, **shape):
        control, code = make_shader(seed, **shape)
        key = expected_key(control, code)
        out = self.run_check('put', journal, key, shape.get('stage', 1), self.write(f'c{seed}', control), self.write(f'k{seed}', code))
        return key, out.strip(), control, code

    def test_journal_keeps_control_and_code_and_checks_them(self):
        journal = self.dir / 'journal'
        key, result, control, code = self.put(journal, 1, stage=0, code_len=0x340, c1=0x300)
        self.assertEqual(result, '1')
        blob = (journal / f'{key}.shader').read_bytes()
        self.assertEqual(blob[:8], b'FC26SHD1')
        self.assertEqual(struct.unpack_from('<4I', blob, 8), (1, 0, CONTROL_LEN, 0x340))
        self.assertEqual(blob[24:24 + CONTROL_LEN], control)
        self.assertEqual(blob[24 + CONTROL_LEN:], code[:0x340])
        self.assertEqual(self.run_check('get', journal, key).strip(), 'ok 0 832 768')
        self.assertEqual(self.put(journal, 1, stage=0, code_len=0x340, c1=0x300)[1], '0')   # already there
        damaged = bytearray(blob)
        damaged[-1] ^= 1
        (journal / f'{key}.shader').write_bytes(bytes(damaged))
        self.assertEqual(self.run_check('get', journal, key).strip(), 'fail bytes do not hash to the key')
        (journal / f'{key}.shader').write_bytes(blob[:-1])
        self.assertEqual(self.run_check('get', journal, key).strip(), 'fail inconsistent lengths or stage')
        self.assertEqual(self.run_check('get', journal, 'f' * 64).strip(), 'fail cannot read')

    def test_journal_refuses_what_the_kit_would_refuse(self):
        journal = self.dir / 'journal'
        self.assertEqual(self.put(journal, 2, stage=3)[1], '-1')                    # tessellation: no translation chain
        self.assertEqual(self.put(journal, 3, stage=1, c1=0x20)[1], '-1')          # graphics code without its 0x30 header
        self.assertEqual(self.put(journal, 4, stage=1, c1=0x300, code_len=0x200)[1], '-1')   # c1 past the code
        self.assertEqual(self.put(journal, 5, stage=5, c1=0)[1], '1')              # compute keeps its header
        control, code = make_shader(6)
        wrong = 'e' * 64   # a key the bytes do not hash to: the key rule differs from nvn_mtl.m's
        self.assertEqual(self.run_check('put', journal, wrong, 1, self.write('c', control), self.write('k', code)).strip(), '-2')
        self.assertFalse((journal / f'{wrong}.shader').exists())

    def test_rekey_moves_old_journal_entries_and_merges_twins(self):
        journal, cache = self.dir / 'journal', self.dir / 'rt'
        control, code = make_shader(8, stage=0, code_len=0x340, c1=0x300)
        twin = bytearray(control); twin[0x7d0:0x7e8] = bytes(range(24))   # the same shader from another record
        shader = lambda c: b'FC26SHD1' + struct.pack('<4I', 1, 0, CONTROL_LEN, 0x340) + c + code[:0x340]
        new = expected_key(control, code)
        olds = [old_key(control, code), old_key(bytes(twin), code)]
        for old, c, sfx, js in [(olds[0], control, '0123456789ab', '{"tex":{}}'), (olds[1], bytes(twin), 'ba9876543210', '{"tex":{"0":"2d"}}')]:
            self.write(f'journal/{old}.shader', shader(c))
            self.write(f'journal/{old}.rows', f'V\t{old}-0123456789ab\t0\t{{"tex":{{}}}}\nV\t{old}-{sfx}\t0\t{js}\n'.encode())
            self.cache_files('rt', old)
        current, _, _, _ = self.put(journal, 9)   # already under the current rule: left alone
        self.cache_files('rt', current)
        self.write('rt/pso_collected.tsv', b'S\tx\t0\n')
        self.assertEqual(self.run_check('get', journal, olds[0]).strip(), 'fail bytes do not hash to the key')
        self.assertEqual(self.run_check('rekey', journal, cache).strip(), '2')
        self.assertEqual(sorted(p.name for p in journal.iterdir()), sorted([f'{new}.shader', f'{new}.rows', f'{current}.shader']))
        self.assertEqual(self.run_check('get', journal, new).strip(), 'ok 0 832 768')
        self.assertEqual(self.run_check('rows', journal, new).splitlines(),
                         [f'{new}-0123456789ab 0 {{"tex":{{}}}}', f'{new}-ba9876543210 0 {{"tex":{{"0":"2d"}}}}', 'rows 2'])
        self.assertEqual(sorted(p.name for p in cache.iterdir()), sorted(self.cache_files('rt', current) + ['pso_collected.tsv']))
        self.assertEqual(self.run_check('rekey', journal, cache).strip(), '0')   # nothing left to move
        self.write(f'journal/{olds[0]}.shader', shader(control)); self.cache_files('rt', olds[0])
        self.assertEqual(self.run_check('rekey', journal, '-').strip(), '1')     # nothing to re-translate: cache kept
        self.assertTrue((cache / f'{olds[0]}.variants').exists())
        self.assertEqual(self.run_check('rekey', self.dir / 'none', '-').strip(), '0')

    def test_journal_rows_once_per_variant(self):
        journal = self.dir / 'journal'
        key = 'a' * 64
        v1, v2 = f'{key}-0123456789ab', f'{key}-ba9876543210'
        self.assertEqual(self.run_check('add-row', journal, key, v1, 1, '{"tex":{"0":"2d"}}').strip(), '1')
        self.assertEqual(self.run_check('add-row', journal, key, v2, 0, '{"tex":{}}').strip(), '1')
        self.assertEqual(self.run_check('add-row', journal, key, v1, 1, '{"tex":{"0":"2d"}}').strip(), '0')
        for variant, json in [(f'{"b" * 64}-0123456789ab', '{}'), (v1 + 'x', '{}'), (v1, 'a\tb'), (v1, ''), (v1, 'a\nb')]:
            with self.subTest(variant=variant, json=json):
                self.assertEqual(self.run_check('add-row', journal, key, variant, 0, json).strip(), '-1')
        with open(journal / f'{key}.rows', 'a') as f:
            f.write('garbage\nV\tnot-a-variant\t0\t{}\nV\t' + v1 + '\t2\t{}\n')
        self.assertEqual(self.run_check('rows', journal, key),
                         f'{v1} 1 {{"tex":{{"0":"2d"}}}}\n{v2} 0 {{"tex":{{}}}}\nrows 2\n')
        self.assertEqual(self.run_check('rows', journal, 'c' * 64), 'rows 0\n')

    def test_journal_recovers_from_truncated_row(self):
        journal = self.dir / 'journal'
        key = 'a' * 64
        v1, v2, v3 = f'{key}-0123456789ab', f'{key}-ba9876543210', f'{key}-cdef01234567'
        self.assertEqual(self.run_check('add-row', journal, key, v1, 1, '{"tex":{"0":"2d"}}').strip(), '1')
        with open(journal / f'{key}.rows', 'a') as f:
            f.write('V\t' + v2 + '\t0\t{"incomplete":')
        self.assertEqual(self.run_check('add-row', journal, key, v3, 0, '{"tex":{"1":"cube"}}').strip(), '1')
        self.assertEqual(self.run_check('rows', journal, key),
                         f'{v1} 1 {{"tex":{{"0":"2d"}}}}\n{v3} 0 {{"tex":{{"1":"cube"}}}}\nrows 2\n')
        key2 = 'b' * 64
        v4 = f'{key2}-0123456789ab'
        self.write(f'journal/{key2}.rows', f'V\t{v4}\t0\t{{"cut":'.encode())
        self.assertEqual(self.run_check('add-row', journal, key2, v4, 0, '{"tex":{}}').strip(), '1')
        self.assertEqual(self.run_check('rows', journal, key2), f'{v4} 0 {{"tex":{{}}}}\nrows 1\n')

    def test_journal_keys_sorted(self):
        journal = self.dir / 'journal'
        keys = sorted(self.put(journal, seed)[0] for seed in range(5))
        self.write('journal/' + 'a' * 64 + '.rows', b'')   # rows without a shader: not a journaled shader
        self.write('journal/readme', b'')
        self.assertEqual(self.run_check('keys', journal), ''.join(k + '\n' for k in keys) + 'keys 5\n')
        self.assertEqual(self.run_check('keys', self.dir / 'none'), 'keys 0\n')

    # ---------- size limit ----------
    def shader_group(self, key, size, at_ns, journal=True):
        files = [(f'rt/{key}.variants', size // 4), (f'rt/{key}-0123456789ab_b.metal', size // 4)]
        if journal:
            files += [(f'journal/{key}.shader', size // 4), (f'journal/{key}.rows', size - 3 * (size // 4))]
        else:
            files += [(f'rt/{key}-0123456789ab_b.json', size - 2 * (size // 4))]
        for name, n in files:
            os.utime(self.write(name, b'x' * n), ns=(at_ns, at_ns))
        return files

    def test_scan_groups_both_folders(self):
        self.shader_group('a' * 64, 400, 1_000_000_000)
        self.shader_group('b' * 64, 100, 3_000_000_000, journal=False)
        os.utime(self.dir / 'rt' / ('a' * 64 + '.variants'), ns=(2_000_000_000, 2_000_000_000))
        self.write('rt/pso_collected.tsv', b'y' * 50)
        out = self.run_check('scan', self.dir / 'rt', self.dir / 'journal').splitlines()
        self.assertEqual(out, ['a' * 64 + ' 400 2000000000', 'b' * 64 + ' 100 3000000000', 'total 550 fixed 50'])
        self.assertEqual(self.run_check('scan', self.dir / 'rt', self.dir / 'none').splitlines()[-1], 'total 350 fixed 50')
        self.assertEqual(self.run_check('scan', self.dir / 'none', '-').strip(), 'fail')

    def test_plan_takes_the_oldest_until_nine_tenths(self):
        groups = [f'{"a" * 64}:300:30', f'{"b" * 64}:300:10', f'{"c" * 64}:300:20', f'{"d" * 64}:300:20']
        self.assertEqual(self.run_check('plan', 1000, 1200, *groups), f'evict {"b" * 64}\nafter 900\n')   # 1200 > 1000: down to <= 900
        self.assertEqual(self.run_check('plan', 1000, 1300, *groups),
                         f'evict {"b" * 64}\nevict {"c" * 64}\nafter 700\n')   # c before d: same age, key order
        self.assertEqual(self.run_check('plan', 1200, 1200, *groups), 'after 1200\n')   # at the limit: nothing
        self.assertEqual(self.run_check('plan', 0, 1200, *groups), 'after 1200\n')      # no limit
        self.assertEqual(self.run_check('plan', 100, 1300, *groups).count('evict'), 4)  # never below what no shader owns

    def test_trim_removes_the_least_recently_used(self):
        keys = [c * 64 for c in 'abcde']
        for i, key in enumerate(keys):
            self.shader_group(key, 1000, (i + 1) * 1_000_000_000, journal=i != 4)
        self.write('rt/pso_collected.tsv', b'z' * 500)
        self.run_check('touch', self.dir / 'rt', self.dir / 'journal', keys[0])   # a used now: the newest
        out = self.run_check('trim', self.dir / 'rt', self.dir / 'journal', 4000)
        self.assertEqual(out.strip(), '0 shaders 5 evicted 2 before 5500 after 3500')
        left = {p.name[:64] for p in (self.dir / 'rt').iterdir() if p.name != 'pso_collected.tsv'}
        self.assertEqual(left, {keys[0], keys[3], keys[4]})
        self.assertEqual({p.name[:64] for p in (self.dir / 'journal').iterdir()}, {keys[0], keys[3]})
        self.assertTrue((self.dir / 'rt/pso_collected.tsv').exists())
        self.assertEqual(self.run_check('trim', self.dir / 'rt', self.dir / 'journal', 4000).strip(),
                         '0 shaders 3 evicted 0 before 3500 after 3500')

    def test_touch_falls_back_to_the_index(self):
        key = 'e' * 64
        self.shader_group(key, 100, 1_000_000_000, journal=False)
        self.run_check('touch', self.dir / 'rt', self.dir / 'journal', key)
        self.assertGreater((self.dir / 'rt' / f'{key}.variants').stat().st_mtime_ns, 1_000_000_000)

    def test_evict_one(self):
        self.shader_group('a' * 64, 400, 1)
        self.shader_group('b' * 64, 400, 1)
        self.assertEqual(self.run_check('evict', self.dir / 'rt', self.dir / 'journal', 'a' * 64).strip(), '4')
        self.assertEqual(len(list((self.dir / 'rt').iterdir())) + len(list((self.dir / 'journal').iterdir())), 4)

    # ---------- lock and settings ----------
    def test_one_run_holds_the_folder(self):
        holder = subprocess.Popen([str(self.exe), 'lock', str(self.dir)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            self.assertEqual(self.run_check('lock', self.dir, stdin='').strip(), 'busy')
        finally:
            holder.stdin.close()
            holder.wait(timeout=30)
        self.assertEqual(self.run_check('lock', self.dir, stdin='').strip(), 'locked')

    def test_settings(self):
        mib = 1 << 20
        cases = {('-', '-', '-'): f'{2048 * mib} 0 1 0 300 0', ('0', 'kit', '1'): '0 0 0 0 1 0',
                 ('512', 'all', '3600'): f'{512 * mib} 0 1 0 3600 0', ('x', 'none', '0'): f'{2048 * mib} 1 1 1 300 1',
                 ('-5', 'ALL', '3601'): f'{2048 * mib} 1 1 1 300 1', ('1048577', '', 'abc'): f'{2048 * mib} 1 1 1 300 1'}
        for args, want in cases.items():
            with self.subTest(args=args):
                self.assertEqual(self.run_check('settings', *args).strip(), want)


if __name__ == '__main__':
    unittest.main()
