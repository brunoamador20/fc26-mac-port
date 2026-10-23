"""Pre-island offsets in the runtime's diagnostics (docs/ILHAS_NUVEM.md): a pc in the pre-island is before the module
base, so its offset is negative and must read "main-0x1234", never the wrapped 0xffff... of pc - base.

- runtime/module_offset.h (portable, signal-safe) is compiled and run here: signed hex for every sign and edge;
- scripts/symbolize.py reads "caller main-0x40" lines (it used to drop them) and still names "main+0x..." ones;
- the printers in loader.c (runtime_trace_guest, crash, runtime_describe_address) and the callers of
  runtime_module_offset go through the signed formatting: loader.c needs macOS headers, so on Linux this is a source check.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]

DRIVER = r'''
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "module_offset.h"
int main(void) {
    const uint64_t cases[] = {0x1234, (uint64_t)-0x40, 0, (uint64_t)INT64_MIN, (uint64_t)INT64_MAX, 0xabcdef0, (uint64_t)-1};
    for (unsigned i = 0; i < sizeof cases / sizeof *cases; i++) {
        char b[MODULE_OFFSET_HEX]; memset(b, 'Z', sizeof b);
        size_t n = module_offset_hex(b, cases[i]);
        if (strlen(b) != n) return 2;
        printf("%s\n", b);
    }
    return 0;
}
'''


class SignedHex(unittest.TestCase):
    def test_module_offset_hex(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            self.skipTest('a C compiler is required')
        with tempfile.TemporaryDirectory() as td:
            src, exe = Path(td, 'd.c'), Path(td, 'd')
            src.write_text(DRIVER)
            r = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', f'-I{HERE / "runtime"}', str(src), '-o', str(exe)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.split(), ['+0x1234', '-0x40', '+0x0', '-0x8000000000000000', '+0x7fffffffffffffff',
                                                '+0xabcdef0', '-0x1'])


class Symbolize(unittest.TestCase):
    def test_negative_offsets_are_listed(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'analysis').mkdir()
            sym = lambda name, value, size: dict(name=name, value=value, size=size, defined=True, type=2)
            layout = [dict(name='main', symbols=[sym('fc26_test_func', 0x1000, 0x100)]),
                      dict(name='sdk', symbols=[sym('fc26_sdk_func', 0x20, 0x10)])]
            (Path(td) / 'analysis/runtime-layout.json').write_text(json.dumps(layout))
            log = '[totk] caller main+0x1010\n[totk] caller main-0x40\n[totk] caller sdk+0x24\n'
            r = subprocess.run([sys.executable, str(HERE / 'scripts/symbolize.py')], input=log, capture_output=True,
                               text=True, env={**os.environ, 'FC26_WORK': td})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines(), [
                'main+0x1010  fc26_test_func +0x10',
                'main-0x40  (pre-island: rewriter patch code before the module base)',
                'sdk+0x24  fc26_sdk_func +0x4',
            ])


def body(source, signature):
    """The text of one function in a runtime source: from its signature to the closing brace at column 0."""
    i = source.index(signature)
    return source[i:source.index('\n}', i) + 2]


class Printers(unittest.TestCase):
    def test_loader_prints_signed_offsets(self):
        src = (HERE / 'runtime/loader.c').read_text()
        self.assertTrue('#include "module_offset.h"' in src, 'loader.c does not include module_offset.h')
        self.assertFalse('%+lld' in src, 'a decimal %+lld offset (main-4660) is not signed hex')
        trace = body(src, 'void runtime_trace_guest(')
        self.assertTrue('module_offset_hex(' in trace, 'runtime_trace_guest prints its caller offset unsigned')
        describe = src[src.index('void runtime_describe_address('):].split('\n', 1)[0]
        self.assertTrue('module_offset_hex(' in describe, 'runtime_describe_address prints the offset unsigned')
        crash = body(src, 'static void crash(')
        self.assertEqual(crash.count('signal_offset('), 4, 'the faulting pc and every frame lr go through signal_offset')
        self.assertIsNone(re.search(r'signal_hex\(" offset="', crash), 'crash() prints a module offset unsigned')
        self.assertTrue('module_offset_hex(' in body(src, 'static void signal_offset('))

    def test_runtime_module_offset_callers_print_a_sign(self):
        # every place that prints what runtime_module_offset returned, before the fix: an unsigned "+" offset
        unsigned_prints = {
            'runtime/gfx_bridge.c': r'while\(\*nm\)b\[\(\*n\)\+\+\]=\*nm\+\+;watch_hex\(b,n,"\+",off\);',
            'third_party/d2r_gfx/gfx/nvn/hle_nvn.c': r'" %s\+%#llx", nm, \(unsigned long long\)off\)',
            'third_party/d2r_gfx/gfx/nvn/nvn_mtl.m': r'pc=%s\+%#llx lr=%s\+%#llx',
        }
        for rel, pattern in unsigned_prints.items():
            src = (HERE / rel).read_text()
            self.assertTrue('runtime_module_offset(' in src, f'{rel} no longer calls runtime_module_offset: update this test')
            self.assertIsNone(re.search(pattern, src), f'{rel} prints a runtime_module_offset result without its sign')
            self.assertTrue('(int64_t)' in src and re.search(r'module_offset_hex\(|\? "-" : "\+"', src),
                            f'{rel} has no signed print of the module offset')


if __name__ == '__main__':
    unittest.main()
