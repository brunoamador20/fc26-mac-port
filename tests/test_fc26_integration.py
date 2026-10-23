"""games/fc26/scripts/integrar_estoria3.py: the story-3 hooks applied to a runtime (FC 26's own once story 2 is in,
else games/by3's, which it is a copy of), idempotent, all-or-nothing, and the inserted code compiles against runtime/ro."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'games/fc26/scripts/integrar_estoria3.py'
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import integrar_estoria3 as integration
from test_fc26_ro_runtime import runtime_tree

GAME = ROOT / 'games/fc26' if (ROOT / 'games/fc26/runtime/loader.c').exists() else ROOT / 'games/by3'

# Each fragment inside a function with the signature (and local names) it gets in loader.c / services.c.
HARNESS = r'''#include "runtime.h"
#include "ro/ro_module.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static void signal_hex(const char *label, uint64_t value) { (void)label; (void)value; }
void f_dispatch(uint64_t ret, uint64_t *regs) { @dispatch@ }
uint64_t f_permission(uint64_t address, uint64_t size, unsigned permission) { @permission@ }
uint64_t f_lock(uint64_t address, uint64_t size, unsigned mask, unsigned attribute) { @lock@ }
int f_query(uint64_t address, uint64_t *base, uint64_t *size, unsigned *state, unsigned *permission, unsigned *attribute) { @query@ }
int f_offset(uint64_t pc, const char **name, uint64_t *off) { @offset@ }
void f_describe(uint64_t a, char *out, size_t n) { @describe@ snprintf(out, n, "0x%llx", (unsigned long long)a); }
void f_trace(uint64_t lr) { @trace@ }
void f_crash(uint64_t pc) { uint64_t frame[2] = {0, pc}; @crash_pc@ @crash_frame@ }
int f_main(int argc, char **argv) { (void)argc; @set_dir@ @init_sdk@ @probe@ return 0; }
void f_svc_query(uint64_t addr) { uint64_t base = 0, size = 0; unsigned state = 0, perm = 0, attr = 0; if (!addr) {} @svc_query@
    (void)base; (void)size; (void)state; (void)perm; (void)attr; }
'''


class Integration(unittest.TestCase):
    def tree(self, directory):
        for name in ('runtime/loader.c', 'runtime/services.c', 'Makefile'):
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(GAME / name, directory / name)
        return {n: (directory / n).read_text() for n in ('runtime/loader.c', 'runtime/services.c', 'Makefile')}

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)

    def test_applies_once_and_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            before = self.tree(directory)
            first = self.run_script(directory)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn('runtime/loader.c: 12 edits', first.stdout)
            self.assertIn('runtime/services.c: 2 edits', first.stdout)
            self.assertIn('Makefile: 2 edits', first.stdout)
            after = {n: (directory / n).read_text() for n in before}
            for name, fragment in integration.FRAGMENTS.items():
                where = 'runtime/services.c' if name == 'svc_query' else 'runtime/loader.c'
                self.assertEqual(after[where].count(fragment), 1, name)
            self.assertIn('runtime/ro/*.c', after['Makefile'])
            again = self.run_script(directory)
            self.assertEqual(again.stdout.count('already integrated'), 3, again.stdout)
            self.assertEqual({n: (directory / n).read_text() for n in before}, after)

    def test_check_writes_nothing_and_a_drifted_runtime_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            before = self.tree(directory)
            check = self.run_script(directory, '--check', '--diff')
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn('+#include "ro/ro_module.h"', check.stdout)
            self.assertEqual({n: (directory / n).read_text() for n in before}, before)
            drifted = before['runtime/loader.c'].replace(' runtime_fail("unknown gate return address");\n', '')
            (directory / 'runtime/loader.c').write_text(drifted)
            run = self.run_script(directory)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('anchor found 0 times', run.stderr)
            self.assertEqual((directory / 'runtime/services.c').read_text(), before['runtime/services.c'])
            self.assertEqual((directory / 'Makefile').read_text(), before['Makefile'])

    def test_inserted_code_compiles(self):
        compiler = shutil.which('cc')
        if not compiler: self.skipTest('A C compiler is required')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            tree = runtime_tree(directory)
            source = HARNESS
            for name, fragment in integration.FRAGMENTS.items(): source = source.replace(f'@{name}@', fragment)
            self.assertNotIn('@', source)
            (directory / 'harness.c').write_text(source)
            run = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-D_DEFAULT_SOURCE', f'-I{tree}',
                                  '-c', str(directory / 'harness.c'), '-o', str(directory / 'harness.o')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
