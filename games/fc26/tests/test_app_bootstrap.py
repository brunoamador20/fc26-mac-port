"""App-only setup compiled from the same header called first by loader.c; no game and no window."""
from pathlib import Path
import json
import os
import platform
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]

def compile_objc(sources, output):
    return subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-fobjc-arc',
                           *map(str, sources), '-framework', 'Cocoa', '-o', str(output)], capture_output=True, text=True)

@unittest.skipUnless(platform.system() == 'Darwin', 'macOS')
class AppBootstrap(unittest.TestCase):
    def test_bootstrap_logs_rotation_environment_and_absent_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = compile_objc([HERE / 'tests/app_bootstrap_test.m'], root / 'runtime')
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ, KEEP='old', TOTK_HEADLESS='1')
            env.pop('FC26_APP_BOOTSTRAP', None)
            plain = subprocess.run([str(root / 'runtime')], env=env, capture_output=True, text=True)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn(':old:1', plain.stdout)
            log, previous = root / 'fc26.log', root / 'fc26.previous.log'
            log.write_text('old log')
            previous.write_text('older log')
            env['FC26_APP_BOOTSTRAP'] = json.dumps(dict(work=str(root), log=str(log), previousLog=str(previous), environment={'KEEP':'new'}))
            run = subprocess.run([str(root / 'runtime')], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout + run.stderr, '')
            self.assertEqual(previous.read_text(), 'old log')
            self.assertIn(f'stdout:{root.resolve()}:new:absent', log.read_text())
            self.assertIn('stderr:consumed', log.read_text())
            self.assertTrue(log.read_text().startswith(f'[launcher] work {root}, present ? Hz, display ?, fullscreen no, window ?, drawable scale 1, MetalFX off, sound on\n'))
            env['FC26_APP_BOOTSTRAP'] = '{}'
            bad = subprocess.run([str(root / 'runtime')], env=env, capture_output=True)
            self.assertEqual(bad.returncode, 7)
            self.assertIn(b'fc26-bootstrap-error.log', bad.stderr)
            error_path = Path(bad.stderr.decode().split('Veja ', 1)[1].strip())
            self.assertIn('não conseguiu preparar', error_path.read_text())


if __name__ == '__main__':
    unittest.main()
