"""Packaging-time Metal warm-up (build_app.step_warm_metal, games/totk/tools/warm_metal_cache.m)."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import build_app

TOOL_SOURCE = Path(build_app.GAME) / 'tools/warm_metal_cache.m'


class StepWarmMetalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.tree, self.out, self.logs = root / 'tree', root / 'Game.app', root / 'logs'
        self.logs.mkdir()
        (self.tree / 'build').mkdir(parents=True)
        (self.tree / 'build/warm-metal-cache').write_text('tool')
        self.app_build = self.out / 'Contents/Resources/totk/build'
        self.app_build.mkdir(parents=True)
        self.app_tool = self.app_build / 'warm-metal-cache'
        self.said = []

    def tearDown(self):
        self.folder.cleanup()

    def step(self, game_running=False, reports=None, fail=False):
        """Run the step with pgrep and the tool replaced; reports: {log name: JSON object} the tool would print."""
        calls = []

        def run(cmd, log, **_kwargs):
            calls.append([str(c) for c in cmd])
            self.assertTrue(self.app_tool.is_file(), 'the tool runs from the game binary\'s folder')
            if fail:
                raise build_app.BuildError('warm-metal-cache failed (exit 2)')
            log.write_text('warm_metal_cache: 1000 / 8290 after 20 s\n' + json.dumps((reports or {}).get(log.name, {})) + '\n')

        def system(cmd, **_kwargs):
            if cmd[0] == 'pgrep':
                return mock.Mock(returncode=0 if game_running else 1)
            raise AssertionError(f'unexpected command {cmd}')

        with mock.patch.object(build_app.subprocess, 'run', side_effect=system), mock.patch.object(build_app, 'run', side_effect=run), \
             mock.patch.object(build_app, 'clone', side_effect=lambda src, dst: shutil.copyfile(src, dst)), \
             mock.patch.object(build_app, 'say', side_effect=self.said.append):
            build_app.step_warm_metal(self.tree, self.out, self.logs)
        return calls

    def test_skipped_while_a_game_is_running(self):
        self.assertEqual(self.step(game_running=True), [])
        self.assertIn('a game is running', self.said[-1])

    def test_runs_from_the_game_binarys_folder_and_leaves_nothing_there(self):
        calls = self.step(reports={
            'warm-metal-cache.log': {'files': 8290, 'compiled': 8290, 'skipped': 0, 'failed': 0, 'threads': 8, 'seconds': 170.0},
            'warm-metal-cache-verify.log': {'sampled': 64, 'hits': 64, 'median_ms': 0.3, 'max_ms': 0.9}})
        seed = str(self.app_build / 'shader-seed')
        self.assertEqual(calls, [[str(self.app_tool), seed], [str(self.app_tool), seed, '--verify', '64']])
        self.assertFalse(self.app_tool.exists(), 'the tool must not stay inside the signed app')
        self.assertIn("finds them in Metal's cache (64 of 64", self.said[-1])

    def test_says_so_when_metal_did_not_keep_them(self):
        self.step(reports={
            'warm-metal-cache.log': {'files': 8290, 'compiled': 8290, 'skipped': 0, 'failed': 0},
            'warm-metal-cache-verify.log': {'sampled': 64, 'hits': 3, 'median_ms': 61.0, 'max_ms': 95.0}})
        self.assertIn('Metal did not keep them (3 of 64', self.said[-1])

    def test_a_failing_tool_does_not_fail_the_build_and_is_removed(self):
        self.step(fail=True)
        self.assertIn('the first start compiles them instead', self.said[-1])
        self.assertFalse(self.app_tool.exists())

    def test_a_tool_left_by_an_interrupted_build_is_removed(self):
        self.app_tool.write_text('left over')
        self.step(game_running=True)
        self.assertFalse(self.app_tool.exists())

    def test_last_json_takes_the_report_line(self):
        log = self.logs / 'x.log'
        log.write_text('{"old": 1}\nnoise {\n{"compiled": 2}\nwarm_metal_cache: done\n')
        self.assertEqual(build_app.last_json(log), {'compiled': 2})
        log.write_text('nothing\n')
        self.assertIsNone(build_app.last_json(log))


@unittest.skipUnless(shutil.which('xcrun'), 'needs the Xcode command line tools')
class WarmMetalToolTests(unittest.TestCase):
    """The real tool on three small sources: one compiles, one the game skips (double), one does not compile."""

    def test_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tool = root / 'warm-metal-cache'
            built = subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror', str(TOOL_SOURCE),
                                    '-framework', 'Metal', '-framework', 'Foundation', '-o', str(tool)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            seed = root / 'seed'
            seed.mkdir()
            (seed / 'a_b.metal').write_text('#include <metal_stdlib>\nusing namespace metal;\n'
                                            'kernel void mng_test_warm(device float *a [[buffer(0)]], uint i [[thread_position_in_grid]]) { a[i] = a[i] * 2.0f; }\n')
            (seed / 'b_b.metal').write_text('kernel void k(device double *a [[buffer(0)]]) {}\n')
            (seed / 'c_b.metal').write_text('this is not metal\n')
            (seed / 'a_b.json').write_text('{}')   # not a source: ignored
            r = subprocess.run([str(tool), str(seed), '2'], capture_output=True, text=True)
            if r.returncode == 2 and 'no Metal device' in r.stderr:
                self.skipTest('no Metal device')
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual((report['files'], report['compiled'], report['skipped'], report['failed']), (3, 1, 1, 1))
            v = subprocess.run([str(tool), str(seed), '--verify', '3'], capture_output=True, text=True)
            self.assertEqual(v.returncode, 0, v.stderr)
            self.assertEqual(json.loads(v.stdout.strip().splitlines()[-1])['sampled'], 1)


if __name__ == '__main__':
    unittest.main()
