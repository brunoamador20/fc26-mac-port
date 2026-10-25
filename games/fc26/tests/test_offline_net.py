"""FC 26 without the EA servers (story F1, Kick-Off offline): the host's network answers never leave the game waiting.
bsd:u fails every descriptor command at once (a connect to an EA server, a recv, ... EBADF: no socket is ever made,
Socket itself fails with ENETDOWN); nn::nifm says no network and nothing to retry (HandleNetworkRequestErrorResult is a
bool in SDK 19); nn::socket::GetAddrInfo resolves nothing (EAI_AGAIN) at once; nn::friends answers as a console whose
user never went online, so the friend:u service FC 26 would open is never needed. Built from the portable runtime
sources (ipc.c, missing.c, system_services.c, offline_applets.c) with tests/offline_net_test.c; runs on Linux and on
the Mac."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SOURCES = ['tests/offline_net_test.c', 'runtime/ipc.c', 'runtime/missing.c', 'runtime/system_services.c', 'runtime/time_probe.c',
           'runtime/offline_applets.c']


class OfflineNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'offline_net_test'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        build = subprocess.run([compiler, *flags, f'-I{HERE / "runtime"}', *(str(HERE / s) for s in SOURCES), '-lpthread',
                                '-o', str(cls.exe)], capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, *args):
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, timeout=30)

    def test_every_socket_command_fails_at_once(self):
        run = self.run_case('bsd')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)
        for line in ['bsd:u Socket = -1, ENETDOWN', 'bsd:u Connect (14) = -1, EBADF at once', 'bsd:u Recv (8) = -1, EBADF at once',
                     'bsd:u RecvFrom (9) = -1, EBADF at once (ret -1 errno 9, length field 1', 'bsd:u Close (26) = -1, EBADF',
                     'bsd:u ShutdownAllSockets = 0', 'ok: 0 failed']:
            self.assertIn(line, run.stdout)
        self.assertIn('[totk-net] connect(7) refused: no socket exists offline', run.stderr)

    def test_network_functions_answer_offline_by_name(self):
        run = self.run_case('names')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)
        for line in ['HandleNetworkRequestErrorResult false (bool, no retry) (0 0 0)', 'address 0.0.0.0',
                     'nn::socket::GetAddrInfo(EA redirector) = EAI_AGAIN, no list',
                     '_ZN2nn7friends13GetFriendListEPiPNS0_6FriendERKNS_7account3UidEiiRKNS0_12FriendFilterE = 0, 0 entries',
                     '_ZN2nn7friends25EnsureFriendListAvailableEPNS0_12AsyncContextERKNS_7account3UidE fails at once',
                     '_ZN2nn7friends14ShowFriendListERKNS_7account3UidE: closed at once, Result 0', 'ok: 0 failed']:
            self.assertIn(line, run.stdout)
        self.assertIn('[totk-net] getaddrinfo(spring18.gosredirector.ea.com) refused: offline', run.stderr)

    def test_unknown_bsd_command_still_stops_with_name_and_number(self):
        for command in ['4', '28', '77']:
            with self.subTest(command=command):
                run = self.run_case('command', command)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f'[fc26-missing] ipc command: service "bsd:u" command {command}', run.stderr)


if __name__ == '__main__':
    unittest.main()
