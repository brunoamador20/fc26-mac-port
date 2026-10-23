"""assets/game.json is the one place the module list and the game's identity come from, and the rest agrees with it:
runtime/game_version.h, the extractor's title checks, the pinned-hash file and the Makefile."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import game_config  # noqa: E402


class GameConfig(unittest.TestCase):
    def test_config_and_header_agree(self):
        self.assertEqual(game_config.check_config(), [])
        self.assertEqual(game_config.check_game_version_h(), [])

    def test_runtime_takes_the_version_from_game_version_h(self):
        # Story H1: the display version (nn::oe::GetDisplayVersion) and the rewritten folder (runtime/ro) follow
        # TOTK_GAME_VERSION / TOTK_GAME_DIR; a literal copy elsewhere stays behind when the version changes.
        literals = [json.dumps(v) for v in ('1.0.0', '1.89.6e65')] + ['"rewritten/v']
        found = [f'{path.relative_to(HERE)}: {lit}' for path in sorted((HERE / 'runtime').rglob('*'))
                 if path.suffix in ('.c', '.m', '.h') and path.name != 'game_version.h'
                 for lit in literals if lit in path.read_text(errors='replace')]
        self.assertEqual(found, [])

    def test_fc26_modules(self):
        # BRIEFING: main + sdk (+ rtld) and no subsdk0; the loader maps main first.
        self.assertEqual(game_config.MODULES, ['main', 'sdk'])
        self.assertEqual(game_config.CONFIG['analysis_modules'], ['rtld', 'main', 'sdk'])
        self.assertNotIn('subsdk0', json.dumps(game_config.CONFIG['modules']))

    def test_identity(self):
        c = game_config.CONFIG
        self.assertEqual((c['title_id'], c['update_title_id'], c['display_version'], c['version_dir']),
                         ('01004FF021942000', '01004FF021942800', '1.89.6e65', 'v1638400'))
        self.assertEqual(c['rewrite_env'], {'DM_RULESET': 'native', 'DM_PRIVATE_GATES': '0'})

    def test_extractor_checks_the_same_title(self):
        text = (HERE / 'scripts/extract_exefs.py').read_text()
        ids = set(re.findall(r'0100[0-9A-F]{12}', text))
        self.assertEqual(ids, {game_config.CONFIG['title_id'], game_config.CONFIG['update_title_id']})

    def test_pins_file(self):
        pins = json.loads(game_config.EXPECTED_PATH.read_text())
        self.assertEqual(pins['title_id'], game_config.CONFIG['title_id'])
        self.assertEqual(pins['display_version'], game_config.CONFIG['display_version'])
        # every module's patched.bin; a <module>.pre.bin pin appears once --record measured a rewrite with a pre-island
        rewritten = set(pins['rewritten_sha256'])
        self.assertLessEqual({f'{m}.patched.bin' for m in game_config.MODULES}, rewritten)
        self.assertLessEqual(rewritten, {f'{m}.{p}' for m in game_config.MODULES for p in ('patched.bin', 'pre.bin')})
        self.assertEqual(set(pins['exefs_sha256']), set(game_config.CONFIG['analysis_modules']) | {'main.npdm'})

    def test_makefile_reads_the_config(self):
        if not shutil.which('make'):
            self.skipTest('make is required')
        run = subprocess.run(['make', '-n', '-C', str(HERE), 'probe', 'boot', 'rewrite', 'WORK=/nonexistent/work', f'PY={sys.executable}'],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('./build/fc26-native rewritten/v1638400 probe', run.stdout)
        self.assertIn('./build/fc26-native rewritten/v1638400 boot', run.stdout)
        self.assertIn('for m in main sdk;', run.stdout)
        self.assertIn('rewrite-env', run.stdout)
        check = subprocess.run(['make', '-s', '-C', str(HERE), 'check-config', f'PY={sys.executable}'], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_makefile_propagates_runtime_failure(self):
        if not shutil.which('make'):
            self.skipTest('make is required')
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            build_dir = work / 'build'
            build_dir.mkdir(parents=True)
            fake_bin = build_dir / 'fc26-native'
            fake_bin.write_text('#!/bin/sh\nexit 37\n')
            fake_bin.chmod(0o755)
            make_cmd = shutil.which('make') or 'make'
            for target in ('probe', 'boot', 'boot-nnmain'):
                cmd = [make_cmd, '-C', str(HERE), '-o', 'runtime', target, f'WORK={work}', f'PY={sys.executable}']
                if target == 'boot-nnmain':
                    cmd.append(f'MAKE={make_cmd} -o runtime')
                run = subprocess.run(cmd, capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0, f'{target} succeeded unexpectedly: {run.stdout} {run.stderr}')


if __name__ == '__main__':
    unittest.main()
