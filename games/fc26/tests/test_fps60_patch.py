"""Real runtime patch application with synthetic original words."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import sys
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import prepare_patches as patches

class FPS60Patch(unittest.TestCase):
    def test_runtime_checks_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'patches').mkdir()
            table = root / 'patches/fps60-render.tsv'
            table.write_text(f'{patches.FPS60_OFFSET:#x}\t{patches.FPS60_REPLACEMENT.hex()}\t' + '55' * 24 + '\n')
            exe = root / 'patch'
            build = subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                '-I' + str(HERE / 'runtime'), str(HERE / 'tests/fps60_patch_test.c'),
                '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode, enabled, code in [('off', '0', 0), ('on', '1', 0), ('mismatch', '1', 42)]:
                run = subprocess.run([str(exe), mode], cwd=root,
                    env={**os.environ, 'FC26_FPS60': enabled}, capture_output=True, text=True)
                self.assertEqual(run.returncode, code, run.stderr)
                if code: self.assertIn('original bytes differ', run.stderr)
            table.unlink()
            run = subprocess.run([str(exe), 'on'], cwd=root,
                env={**os.environ, 'FC26_FPS60': '1'}, capture_output=True, text=True)
            self.assertEqual(run.returncode, 42)
            self.assertIn('missing', run.stderr)

    def test_generation_rejects_changed_or_short_image(self):
        original = bytearray(patches.FPS60_OFFSET + 24)
        original[patches.FPS60_OFFSET:] = b'\x55' * 24
        rewritten = bytearray(original)
        self.assertIn('55' * 24, patches.fps60_table(original, rewritten))
        rewritten[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'rewrite changed'):
            patches.fps60_table(original, rewritten)
        with self.assertRaisesRegex(ValueError, 'too short'):
            patches.fps60_table(b'', b'')
