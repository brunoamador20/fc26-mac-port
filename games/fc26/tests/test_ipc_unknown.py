"""An IPC service, command or named port the runtime does not answer stops it with its name and number (runtime/ipc.c),
which is how stories 3 and 4 find what FC 26 needs (ro, ec, ldn, web, aoc, pctl, codec, ...): each stop also writes
one "[fc26-missing] ..." line, so one grep over a log lists them. Built from the portable
runtime sources (ipc.c, system_services.c, missing.c) with tests/ipc_unknown.c; runs on Linux and on the Mac."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class UnknownIpc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('A C compiler is required')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'ipc_unknown'
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        build = subprocess.run([compiler, *flags, f'-I{HERE / "runtime"}', str(HERE / 'tests/ipc_unknown.c'),
                                str(HERE / 'runtime/ipc.c'), str(HERE / 'runtime/system_services.c'),
                                str(HERE / 'runtime/missing.c'), '-lpthread',
                                '-o', str(cls.exe)], capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, *args):
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, timeout=30)

    def test_known_service_answers(self):
        run = self.run_case('open')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('GetLanguageCode result 0 code en-US', run.stdout)

    def test_unknown_service_is_named(self):
        # Names the full runtime does not answer either (ldn, pctl, hwopus, ... are answered since story 4: offline_services.c).
        for name in ['ldr:ro', 'ro:1', 'nim:shp', 'es', 'friend:u']:
            for mode in ['service', 'tipc-service']:
                with self.subTest(name=name, mode=mode):
                    run = self.run_case(mode, name)
                    self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                    self.assertIn(f'sm: service "{name}" not implemented', run.stderr)
                    self.assertIn(f'[fc26-missing] ipc service: "{name}" (sm GetServiceHandle, command 1)', run.stderr)
                    self.assertIn('FAIL: IPC service not implemented', run.stderr)

    def test_unknown_command_is_named_and_numbered(self):
        for service, command in [('set', '9999'), ('bsd:u', '77')]:
            with self.subTest(service=service, command=command):
                run = self.run_case('command', service, command)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f'{service}: command {command} not implemented', run.stderr)
                self.assertIn(f'[fc26-missing] ipc command: service "{service}" command {command}', run.stderr)
                self.assertIn('FAIL: IPC command not implemented', run.stderr)

    def test_unknown_named_port_is_named(self):
        run = self.run_case('port', 'ro:1')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('named port "ro:1"', run.stderr)
        self.assertIn('[fc26-missing] named port: "ro:1" (svc 0x1f ConnectToNamedPort)', run.stderr)

    def test_one_missing_line_per_stop(self):
        # grep '[fc26-missing]' on a log gives exactly the stop, once (runtime_fail adds no second, generic line).
        run = self.run_case('command', 'set', '42')
        self.assertEqual([l for l in run.stderr.splitlines() if l.startswith('[fc26-missing]')],
                         ['[fc26-missing] ipc command: service "set" command 42'])

    def test_generic_missing_line_from_runtime_fail(self):
        # A stop that names no missing thing itself still gets one generic line when it says "not implemented"; an
        # ordinary failure gets none.
        run = self.run_case('fail', 'guest exited: module finalizers not yet implemented')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual([l for l in run.stderr.splitlines() if l.startswith('[fc26-missing]')],
                         ['[fc26-missing] runtime: guest exited: module finalizers not yet implemented'])
        run = self.run_case('fail', 'image SHA256 differs from verified rewrite')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertNotIn('[fc26-missing]', run.stderr)

    def test_unknown_message_type_is_named(self):
        run = self.run_case('message-type', '3')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual([l for l in run.stderr.splitlines() if l.startswith('[fc26-missing]')],
                         ['[fc26-missing] ipc message type: service "set" type 3'])


if __name__ == '__main__':
    unittest.main()
