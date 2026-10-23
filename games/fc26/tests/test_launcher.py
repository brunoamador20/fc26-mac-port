"""The app's launcher (app/launcher.m), compiled from the source as the Makefile does: the game it starts gets the
variables the GPU test boots use (tools/boot_gpu.sh), with the sound on, the profile and saves in a fixed place of the
user's and the log in ~/Library/Logs/MacNativeGames; and its dry run (--dry-run, FC26_LAUNCHER_DRYRUN=1) prints that
without starting anything. No game data, no window, no game: the work folder is a temporary one with a stand-in binary."""
from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
LAUNCHER = HERE / 'app/launcher.m'
HARNESS = HERE / 'tests/launcher_plan_test.m'
# what tools/boot_gpu.sh gives every GPU boot that reached the game's first screens (work/logs/boot_all1.log)
BOOT_GPU = {'TOTK_GPU_ALLOW_SUBMIT': '1', 'TOTK_GPU_WIDEN': '1', 'TOTK_GPU_BLOCKRT': '1', 'TOTK_GPU_MIDCLEAR': '1',
            'TOTK_GPU_BUDGET_MB': '5000', 'DM_PRESENT_LINK_FALLBACK': '1'}
# what only the automatic boots set: silent (TOTK_AUDIO_OFF, FC26_AUDIO=0), headless; and what the player's start must not
# inherit from a terminal
CLEARED = ['TOTK_AUDIO_OFF', 'FC26_AUDIO', 'TOTK_HEADLESS', 'FC26_PATCHES', 'TOTK_ROMFS_PROOF_DIR']


def compile_objc(sources, output, defines=()):
    cmd = ['xcrun', 'clang', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-fobjc-arc', *defines, *map(str, sources),
           '-framework', 'Cocoa', '-o', str(output)]
    return subprocess.run(cmd, capture_output=True, text=True)


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('xcrun'), 'macOS with Xcode command line tools')
class Launcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        defines = ['-DFC26_BINARY="fc26-native"', '-DFC26_VERSION_DIR="v100"']
        cls.harness = compile_objc([HARNESS], cls.dir / 'plan', [*defines, '-Wno-unused-function'])
        cls.launcher = compile_objc([LAUNCHER], cls.dir / 'FC 26', defines)
        cls.work = cls.dir / 'work'
        (cls.work / 'build').mkdir(parents=True)
        cls.marker = cls.dir / 'started'
        stand_in = cls.work / 'build/fc26-native'   # it would leave a mark if the launcher started it
        stand_in.write_text(f'#!/bin/sh\ntouch "{cls.marker}"\n')
        stand_in.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, *settings):
        self.assertEqual(self.harness.returncode, 0, self.harness.stderr)
        r = subprocess.run([str(self.dir / 'plan'), str(self.work), '/Users/someone', *settings],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_same_gpu_settings_as_the_test_boots(self):
        p = self.plan()
        for k, v in BOOT_GPU.items():
            self.assertEqual(p['set'].get(k), v, k)
        self.assertEqual(p['set']['TOTK_SLOT_OWNER'], 'user')
        self.assertEqual(p['set']['TOTK_SLOT_PURPOSE'], 'player')
        self.assertEqual(p['cwd'], str(self.work))
        self.assertEqual(p['args'], [str(self.work / 'build/fc26-native'), 'rewritten/v100', 'boot'])
        self.assertEqual(p['slot'], str(self.work / 'analysis/game-slot'))
        self.assertEqual(p['set']['TOTK_GAME_SLOT_DIR'], p['slot'])

    def test_sound_on(self):
        p = self.plan()
        for k in CLEARED:
            self.assertNotIn(k, p['set'], k)
            self.assertIn(k, p['unset'], k)

    def test_profile_saves_and_log_in_the_users_folders(self):
        p = self.plan()
        self.assertEqual(p['profile'], '/Users/someone/Library/Application Support/MacNativeGames/FC26/profile')
        self.assertEqual(p['set']['TOTK_PROFILE_DIR'], p['profile'])
        self.assertEqual(p['log'], '/Users/someone/Library/Logs/MacNativeGames/fc26.log')
        self.assertEqual(p['previous_log'], '/Users/someone/Library/Logs/MacNativeGames/fc26.previous.log')
        self.assertEqual(p['set']['TOTK_INPUT_FILE'], '/Users/someone/Library/Application Support/MacNativeGames/FC26/input.txt')

    def test_metalfx_only_when_chosen(self):
        # the boots that reached the game's screens ran without MetalFX (boot_all1.log: "[mfx-up] ... off")
        fresh = self.plan()
        self.assertNotIn('TOTK_MFX_UPSCALE', fresh['set'])
        self.assertNotIn('TOTK_MFX_OUTPUT', fresh['set'])
        chosen = self.plan('metalfx=1', 'size=0', 'hud=0')
        self.assertEqual(chosen['set']['TOTK_MFX_UPSCALE'], '1')
        self.assertEqual(chosen['set']['TOTK_MFX_OUTPUT'], '1')
        self.assertEqual(chosen['set']['TOTK_WINDOW_SIZE'], '1280x720')
        self.assertEqual(chosen['set']['TOTK_FPS_OVERLAY'], '0')
        self.assertNotIn('DM_HUD_RENDER', chosen['set'])

    def dry_run(self, args, env_extra):
        # only a launcher that has the plan (the harness compiled) has a dry run: an older one would open its window
        self.assertEqual(self.harness.returncode, 0, self.harness.stderr)
        self.assertEqual(self.launcher.returncode, 0, self.launcher.stderr)
        env = {k: v for k, v in os.environ.items() if k not in CLEARED}
        env.update({'FC26_WORK': str(self.work), 'TOTK_AUDIO_OFF': '1', 'FC26_AUDIO': '0', **env_extra})
        return subprocess.run([str(self.dir / 'FC 26'), *args], capture_output=True, text=True, timeout=60, env=env)

    def test_dry_run_prints_and_starts_nothing(self):
        for args, extra in (['--dry-run'], {}), ([], {'FC26_LAUNCHER_DRYRUN': '1'}):
            r = self.dry_run(args, extra)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(self.marker.exists(), 'the dry run started the game')
            lines = r.stdout.splitlines()
            self.assertIn(f"cd '{self.work}'", lines)
            self.assertIn("export TOTK_GPU_ALLOW_SUBMIT='1'", lines)
            self.assertIn("export TOTK_SLOT_OWNER='user'", lines)
            self.assertIn('unset ' + ' '.join(sorted(CLEARED)), lines)
            self.assertNotIn("export TOTK_AUDIO_OFF='1'", lines)
            self.assertTrue(any(line.startswith(f"exec '{self.work}/build/fc26-native' rewritten/v100 boot 2> '")
                                and line.endswith("/Library/Logs/MacNativeGames/fc26.log'") for line in lines), r.stdout)

    def test_dry_run_says_when_the_game_is_missing(self):
        r = self.dry_run(['--dry-run'], {'FC26_WORK': str(self.dir / 'nowhere')})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('nowhere/build/fc26-native', r.stderr)
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
