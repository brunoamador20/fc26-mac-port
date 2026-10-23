"""The shader cache's measuring tools (docs/SHADERS_NUVEM.md): scripts/shader_cache_report.py reads the runtime's log lines
in the exact formats the graphics layer writes them (survey lines, long frames, warm-up, the cache layer) and
scripts/shader_key_check.py tells whether the shader keys repeat between two starts. Synthetic logs and dumps only."""
from pathlib import Path
import hashlib
import io
import json
import random
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import shader_cache_report  # noqa: E402
import shader_key_check  # noqa: E402

FIRST_RUN = '''[totk-gfx] [shader] runtime translation service started (pid 1, native build/shader-service/totk_xlate), cache /w/build/shader-cache/rt-x
[totk-gfx] [survey-shader] frame 10 translated ps aaaa-0123456789ab in 35.20 ms
[totk-gfx] [survey-shader] frame 10 translated vs bbbb-0123456789ab in 14.80 ms (FP64 fallback)
[totk-gfx] [shader] translated 2: vs bbbb-0123456789ab
[dm] [nvn-mtl] [survey-shader] frame 10 Metal library stage 1 aaaa-0123456789ab_b in 60.50 ms
[dm] [nvn-mtl] [survey-shader] frame 10 Metal library stage 0 bbbb-0123456789ab_b in 39.50 ms
[dm] [nvn-mtl] [survey-shader] frame 11 render pipeline 00ff in 12.00 ms
[dm] [nvn-mtl] [survey-shader] frame 12 compute pipeline cccc-0123456789ab_b in 5.00 ms
[totk-gfx] [survey-shader] frame 13 translation FAILED vs dddd-0123456789ab after 3.00 ms: boom
[totk-gfx] [长帧] 帧 10（1.50 s）整帧 120.0 ms，提交+出图 100.0 ms，GPU 5.0 ms；新建管线 1 条 + 着色器库 2 个共 95.5 ms；上传贴图 首传 0 张 + 重传 0 次 0.0 MB / 0.0 ms
[totk-gfx] [长帧] 帧 40（2.50 s）整帧 45.0 ms，提交+出图 30.0 ms，GPU 20.0 ms；新建管线 0 条 + 着色器库 0 个共 0.0 ms；上传贴图 首传 3 张 + 重传 0 次 1.0 MB / 2.0 ms；接读取画面，不可见
'''
SECOND_RUN = '''[fc26-shader-cache] cache /w/build/shader-cache/rt-x: 3 shaders, 0.1 MiB with the journal (limit 2048 MiB); 0 least recently used removed; identity aaaa/bbbb x depth_minus_w=0 (12 ms)
[dm] [nvn-mtl] 启动关键管线已就绪：等待 1234 ms，可用着色器 5 / 渲染管线 3 / 计算管线 1；其余后台继续预热
[fc26-shader-cache] warm-up: the first shader use waited 900 ms for every cached shader and recorded pipeline
[dm] [nvn-mtl] 管线预热完成：着色器 50 个 / 渲染管线 30 个（跳过特化片元 0）/ 计算管线 2 个，后台用时 4567.8 ms（着色器库 6 个线程）
[dm] [nvn-mtl] [survey-shader] frame 300 render pipeline 0a0b in 8.00 ms
[totk-gfx] [nvn] 首次进局等管线预热 15 ms（本帧绘制 2400）
'''


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.dir / name).write_text(text, encoding='utf-8')
        return self.dir / name

    def test_reads_every_line_kind(self):
        r = shader_cache_report.read_log(self.write('1.log', FIRST_RUN))
        self.assertTrue(r['survey'])
        self.assertEqual(r['on_demand']['translations'], dict(count=2, total_ms=50.0, max_ms=35.2, p95_ms=35.2))
        self.assertEqual(r['on_demand']['libraries']['count'], 2)
        self.assertEqual(r['on_demand']['pipelines'], dict(count=2, total_ms=17.0, max_ms=12.0, p95_ms=12.0))
        self.assertEqual(r['failed'], 1)
        self.assertEqual(r['translated_counter'], 2)
        self.assertEqual(r['stall_ms'], 50.0 + 100.0 + 17.0)   # the failed translation took no time worth a stall here
        lf = r['long_frames']
        self.assertEqual((lf['count'], lf['visible'], lf['with_compiles'], lf['visible_with_compiles'], lf['compile_ms']), (2, 1, 1, 1, 95.5))
        self.assertEqual(lf['worst'][0]['frame'], 10)

    def test_warm_up_and_cache_lines(self):
        r = shader_cache_report.read_log(self.write('2.log', SECOND_RUN))
        self.assertEqual(r['warm'], dict(first_list_ms=1234, gate_ms=900, world_ms=15, shaders=50, render_pipelines=30,
                                         compute_pipelines=2, background_ms=4567.8))
        self.assertEqual(len(r['cache']), 2)
        self.assertTrue(r['cache'][0].startswith('cache /w/build/shader-cache/rt-x: 3 shaders'))

    def test_two_runs_print_the_gain(self):
        out = io.StringIO()
        frames1 = self.write('f1.tsv', ''.join(f'{f}\t@frame_ms\t{t}\n' for f, t in enumerate([16.7] * 95 + [120, 50, 40, 16, 16])) +
                             '10\t@lib_new\t2\n10\t@pso_new\t1\n96\t@pso_new\t1\n3\tnvnDrawArrays\t40\n')
        frames2 = self.write('f2.tsv', ''.join(f'{f}\t@frame_ms\t16.7\n' for f in range(100)) + '300\t@pso_new\t1\n')
        with redirect_stdout(out):
            self.assertEqual(shader_cache_report.main([str(self.write('1.log', FIRST_RUN)), str(self.write('2.log', SECOND_RUN)),
                                                       '--frames', str(frames1), str(frames2)]), 0)
        text = out.getvalue()
        self.assertIn('== Rodada 1', text)
        self.assertIn('travadas 167 → 8 ms (-95%)', text)
        self.assertIn('traduções 2 → 0; bibliotecas 2 → 0; pipelines 2 → 1', text)
        self.assertIn('quadros > 33 ms 3 → 0', text)
        r = shader_cache_report.read_frames(frames1)
        self.assertEqual((r['frames'], r['over_33ms'], r['over_100ms'], r['frames_making'], r['slow_frames_making'], r['max_ms']),
                         (100, 3, 1, 2, 1, 120.0))

    def test_json_and_log_without_survey(self):
        out = io.StringIO()
        with redirect_stdout(out):
            shader_cache_report.main([str(self.write('x.log', '[totk-gfx] [shader] translated 300: ps a\n')), '--json'])
        runs = json.loads(out.getvalue())
        self.assertEqual((runs[0]['survey'], runs[0]['translated_counter'], runs[0]['stall_ms']), (False, 300, 0))
        out = io.StringIO()
        with redirect_stdout(out):
            shader_cache_report.main([str(self.dir / 'x.log')])
        self.assertIn('log sem TOTK_SURVEY_SHADER_LOG=1', out.getvalue())


def control(seed, key_len_word=0):
    rnd = random.Random(seed)
    c = bytearray(rnd.randbytes(0x880))
    struct.pack_into('<I', c, 0x20, key_len_word)
    return c


def dump_line(c, code_hash, header=b''):
    n = shader_key_check.key_len(bytes(c))
    key = hashlib.sha256(bytes(c[:n]) + header + code_hash.encode()).hexdigest()   # stands in for the code bytes
    return f'{key}\t1\t{code_hash}\t{bytes(c).hex()}\n'


class KeyCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.codes = [hashlib.sha256(bytes([i])).hexdigest() for i in range(6)]
        self.controls = [control(i, 0x7d1 if i == 5 else 0) for i in range(6)]

    def tearDown(self):
        self.tmp.cleanup()

    def dump(self, name, lines):
        (self.dir / name).write_text(''.join(lines) + 'garbage line\n')
        return str(self.dir / name)

    def run_check(self, *dumps):
        out = io.StringIO()
        with redirect_stdout(out):
            code = shader_key_check.main([*dumps, '--json'])
        return code, json.loads(out.getvalue())

    def test_same_keys_on_both_starts(self):
        a = self.dump('a', [dump_line(c, h) for c, h in zip(self.controls, self.codes)])
        b = self.dump('b', [dump_line(c, h) for c, h in zip(self.controls[1:], self.codes[1:])])   # one shader not met
        code, r = self.run_check(a, b)
        self.assertEqual(code, 0)
        self.assertTrue(r['stable'])
        c = r['comparisons'][0]
        self.assertEqual((c['common_codes'], c['stable'], c['unstable'], c['only_first'], c['only_other']), (5, 5, 0, 1, 0))
        self.assertEqual(r['starts'][0]['malformed'], 1)

    def test_bytes_that_change_between_starts_are_named(self):
        a = self.dump('a', [dump_line(c, h) for c, h in zip(self.controls, self.codes)])
        changed = []
        for i, (c, h) in enumerate(zip(self.controls, self.codes)):
            c = bytearray(c)
            if i in (1, 2):
                c[0x100:0x104] = bytes(4) if c[0x100:0x104] != bytes(4) else b'\xff' * 4   # a pointer-like field
                c[0x7f0] ^= 0xff                                                        # hashed for 0x880, not for 0x7d1
            if i == 5:
                c[0x7f0] ^= 0xff                                                        # past its 0x7d1-byte key: same key
            changed.append(dump_line(c, h))
        code, r = self.run_check(a, self.dump('b', changed))
        self.assertEqual(code, 1)
        c = r['comparisons'][0]
        self.assertEqual((c['stable'], c['unstable']), (4, 2))
        self.assertEqual(c['differing_hashed_bytes'], ['0x100-0x103', '0x7f0'])
        self.assertEqual(c['differing_unhashed_bytes'], [])

    def test_header_only_difference(self):
        a = self.dump('a', [dump_line(self.controls[0], self.codes[0])])
        b = self.dump('b', [dump_line(self.controls[0], self.codes[0], header=b'other header')])
        code, r = self.run_check(a, b)
        self.assertEqual((code, r['comparisons'][0]['unstable'], r['comparisons'][0]['header_only']), (1, 1, 1))

    def test_nothing_in_common_is_not_stable(self):
        code, r = self.run_check(self.dump('a', [dump_line(self.controls[0], self.codes[0])]),
                                 self.dump('b', [dump_line(self.controls[1], self.codes[1])]))
        self.assertEqual((code, r['stable']), (1, False))


if __name__ == '__main__':
    unittest.main()
