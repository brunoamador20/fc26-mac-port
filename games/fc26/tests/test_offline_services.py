"""Story 4's offline services answer as docs/SERVICOS_NUVEM.md says, without the game: aoc:u (no DLC), pctl* (no
restriction), ldn:* (no network around; creating or joining one fails), nim:eca/ecas (shop requests fail as offline),
hwopus (real Opus decoding with libopus), and the web / eShop applets answered by name (closed at once).
Built from the portable runtime sources (ipc.c, missing.c, offline_services.c, offline_applets.c, hwopus.c) with
tests/offline_ipc.c and libopus (pkg-config, or Homebrew's as the Makefile links it); runs on Linux and on the Mac."""
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SOURCES = ['tests/offline_ipc.c', 'runtime/ipc.c', 'runtime/missing.c', 'runtime/offline_services.c', 'runtime/offline_applets.c',
           'runtime/hwopus.c']
HOMEBREW_OPUS = Path('/opt/homebrew/opt/opus')


def opus_flags():
    if shutil.which('pkg-config'):
        run = subprocess.run(['pkg-config', '--cflags', '--libs', 'opus'], capture_output=True, text=True)
        if run.returncode == 0:
            return run.stdout.split()
    if (HOMEBREW_OPUS / 'include/opus/opus.h').exists():
        return [f'-I{HOMEBREW_OPUS}/include/opus', str(HOMEBREW_OPUS / 'lib/libopus.a')]
    return None


class OfflineServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        opus = opus_flags()
        if opus is None:
            raise unittest.SkipTest('libopus is required (Linux: libopus-dev; Mac: brew install opus)')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'offline_ipc'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        build = subprocess.run([compiler, *flags, f'-I{HERE / "runtime"}', *(str(HERE / s) for s in SOURCES), *opus,
                                '-lpthread', '-lm', '-o', str(cls.exe)], capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, *args):
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, timeout=60)

    def test_every_offline_answer(self):
        run = self.run_case('all')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)
        for line in ['aoc:u CountAddOnContent = 0', 'pctl:a IsRestrictionEnabled = false', 'ldn:u Scan (B buffer): no network',
                     'ldn:u Connect = 2203-0022 (no wireless)', 'ldn:u CreateNetwork = 2203-0022 (no wireless)',
                     'nim:eca GetSize = 2164-0056 (internet request not accepted)', 'nn::web::ShowWebPage: Result 0',
                     'hwopus DecodeInterleaved (cmd 8)', 'hwopus: the decoded tone has the encoded tone\'s level',
                     'hwopus DecodeInterleavedForMultiStream (cmd 9): 4 channels decoded', 'ok: 0 failed']:
            self.assertIn(line, run.stdout)

    def test_unknown_commands_still_stop_with_name_and_number(self):
        cases = [(('command', 'aoc:u', '7'), 'aoc:u', 7), (('command', 'nim:eca', '1'), 'nim:eca', 1),
                 (('command', 'hwopus', '100'), 'hwopus', 100), (('command', 'pctl', '9'), 'pctl', 9),
                 (('ldn-command', '500'), 'IUserLocalCommunicationService', 500)]
        for args, service, command in cases:
            with self.subTest(service=service, command=command):
                run = self.run_case(*args)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f'[fc26-missing] ipc command: service "{service}" command {command}', run.stderr)

    def test_a_wrong_final_range_stops(self):
        run = self.run_case('hwopus-range')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('FAIL: Opus stream integrity', run.stderr)

    def test_applet_names_are_what_a_compiler_mangles(self):
        # The names tests/offline_ipc.c feeds runtime_offline_applet_override are compiler output, not typed by hand.
        compiler = shutil.which('clang++') or shutil.which('c++')
        if not compiler:
            self.skipTest('A C++ compiler is required')
        source = '''namespace nn { struct ApplicationId { unsigned long long v; };
        namespace web { struct WebPageReturnValue; struct ShowWebPageArg { void SetCallbackUrl(const char *); };
          int ShowWebPage(WebPageReturnValue *, const ShowWebPageArg &); int ShowWebPage(const ShowWebPageArg &);
          void RequestExitWebPage(); }
        namespace ec { struct NsUid { unsigned long long v; }; void ShowShopProductList(ApplicationId);
          void ShowShopProductDetails(ApplicationId, NsUid); void ShowShopAddOnContentList(ApplicationId);
          void ShowShopConsumableItemDetail(ApplicationId, NsUid); void ShowShopEnterCodeScene(); NsUid MakeNsUid(unsigned long); } }
        void *use[] = {(void *)(int (*)(nn::web::WebPageReturnValue *, const nn::web::ShowWebPageArg &))nn::web::ShowWebPage,
          (void *)(int (*)(const nn::web::ShowWebPageArg &))nn::web::ShowWebPage, (void *)nn::web::RequestExitWebPage,
          (void *)nn::ec::ShowShopProductList, (void *)nn::ec::ShowShopProductDetails, (void *)nn::ec::ShowShopAddOnContentList,
          (void *)nn::ec::ShowShopConsumableItemDetail, (void *)nn::ec::ShowShopEnterCodeScene, (void *)nn::ec::MakeNsUid};
        void f(nn::web::ShowWebPageArg &a) { a.SetCallbackUrl(""); }
        '''
        with tempfile.TemporaryDirectory() as folder:
            cpp, obj = Path(folder) / 'names.cpp', Path(folder) / 'names.o'
            cpp.write_text(source)
            build = subprocess.run([compiler, '-c', str(cpp), '-o', str(obj)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            nm = shutil.which('nm')
            if not nm:
                self.skipTest('nm is required')
            listed = subprocess.run([nm, '-u', str(obj)], capture_output=True, text=True).stdout
        names = {re.sub(r'^_(?=_Z)', '', n) for n in re.findall(r'_+Z\w+', listed)}   # the Mac adds one leading _
        harness = (HERE / 'tests/offline_ipc.c').read_text()
        self.assertEqual(len(names), 10, names)
        for name in names:
            self.assertIn(f'"{name}"', harness, f'{name} is not what tests/offline_ipc.c uses')


if __name__ == '__main__':
    unittest.main()
