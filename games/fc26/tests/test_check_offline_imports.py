"""scripts/check_offline_imports.py on a synthetic work folder (no game data): it tells, for each nn::ec / ldn / web /
aoc / pctl / codec import, whether the host answers it by name, the sdk defines it, or nobody does (MISSING, exit 1);
and which service names of story 4 the rewritten modules hold and the host registers."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import game_config  # noqa: E402

WEB = '_ZN2nn3web11ShowWebPageEPNS0_18WebPageReturnValueERKNS0_14ShowWebPageArgE'
SHOP = '_ZN2nn2ec22ShowShopProductDetailsENS_13ApplicationIdENS0_5NsUidE'
COUNT = '_ZN2nn3aoc17CountAddOnContentEv'
LDN = '_ZN2nn3ldn10InitializeEv'
PCTL = '_ZN2nn4pctl28IsFreeCommunicationAvailableEv'
PCTL_INIT = '_ZN2nn4pctl10InitializeEv'
OPUS = '_ZN2nn5codec21DecodeOpusInterleavedEPNS0_15OpusDecoderTypeEPmPiPsmPKvm'
ABSENT = '_ZN2nn2ec11NotInTheSdkEv'


def symbol(name, defined, binding=1):
    return dict(name=name, value=0x1000 if defined else 0, size=0, defined=defined, binding=binding, type=2)


class CheckOfflineImports(unittest.TestCase):
    def run_script(self, main_imports, sdk_strings=b''):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        work = Path(folder.name)
        (work / 'analysis').mkdir()
        modules = [dict(name='main', symbols=[symbol('', False)] + [symbol(n, False, b) for n, b in main_imports]),
                   dict(name='sdk', symbols=[symbol(n, True) for n in (LDN, PCTL, PCTL_INIT, OPUS, COUNT, WEB)])]
        (work / 'analysis/runtime-layout.json').write_text(json.dumps(modules))
        rewritten = work / f'rewritten/{game_config.VERSION}'
        rewritten.mkdir(parents=True)
        (rewritten / 'sdk.patched.bin').write_bytes(b'\0junk\0' + sdk_strings)
        return subprocess.run([sys.executable, str(HERE / 'scripts/check_offline_imports.py'), '--work', str(work)],
                              capture_output=True, text=True, timeout=60)

    def line_of(self, out, name):
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if name in line:
                return lines[i - 1] + '\n' + line
        self.fail(f'{name} not listed:\n{out}')

    def test_each_import_gets_who_answers_it(self):
        run = self.run_script([(WEB, 1), (SHOP, 1), (COUNT, 1), (LDN, 1), (PCTL, 1), (PCTL_INIT, 1), (OPUS, 1), ('nnMain', 1)])
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('host (name)', self.line_of(run.stdout, WEB))
        self.assertIn('offline_applets.c prefix _ZN2nn3web11ShowWebPageEPNS0_18WebPageReturnValueE', self.line_of(run.stdout, WEB))
        self.assertIn('offline_applets.c prefix _ZN2nn2ec22ShowShopProductDetailsE', self.line_of(run.stdout, SHOP))
        self.assertIn('exact name in runtime/services.c', self.line_of(run.stdout, COUNT))
        for name in (LDN, PCTL, PCTL_INIT, OPUS):
            self.assertIn('sdk (native)', self.line_of(run.stdout, name))
        self.assertNotIn('nnMain', run.stdout)   # outside the six namespaces
        self.assertIn('nothing MISSING', run.stdout)

    def test_missing_import_fails(self):
        run = self.run_script([(LDN, 1), (ABSENT, 1), ('_ZN2nn2ec8WeakOneEv', 2)])
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('MISSING', self.line_of(run.stdout, ABSENT))
        self.assertIn('weak, stays 0', self.line_of(run.stdout, '_ZN2nn2ec8WeakOneEv'))
        self.assertIn('1 MISSING', run.stdout)

    def test_service_strings_and_registration(self):
        run = self.run_script([(LDN, 1)], sdk_strings=b'ldn:u\0nim:eca\0xhwopus\0')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        section = run.stdout.split('services of story 4')[1].splitlines()[1:]
        rows = {line.split()[0]: line.split()[1:] for line in section if line.startswith('  ')}
        self.assertEqual(rows['ldn:u'], ['sdk', 'registered'])
        self.assertEqual(rows['nim:eca'], ['sdk', 'registered'])
        self.assertEqual(rows['ldn:m'], ['-', 'registered'])
        self.assertEqual(rows['hwopus'], ['-', 'registered'])   # "xhwopus" is not the name on its own
        self.assertEqual(sorted(rows), sorted(['aoc:u', 'pctl', 'pctl:a', 'pctl:s', 'pctl:r', 'ldn:u', 'ldn:s', 'ldn:m',
                                               'nim:eca', 'nim:ecas', 'hwopus']))


if __name__ == '__main__':
    unittest.main()
