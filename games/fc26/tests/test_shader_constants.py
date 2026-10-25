"""Compile the real reflection reader; no game data or Metal device required."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN = HERE / 'third_party/d2r_gfx/gfx/nvn'

class ShaderConstantsTest(unittest.TestCase):
    def test_large_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'constants.m'
            source.write_text(r'''
#import "nvn_refl.h"
#include <stdio.h>
int main(void) { @autoreleasepool {
    NSMutableString *hex = [NSMutableString string];
    for (unsigned i = 0; i < 8448; i++) [hex appendFormat:@"%02x", i & 255];
    nvn_refl r; char err[512] = {0};
    int rc = nvn_refl_from_json(@{@"route": @"B", @"bindings": @[], @"c1": hex}, &r, err, sizeof err);
    if (rc) { fprintf(stderr, "%s\n", err); return 1; }
    if (!r.has_c1 || r.c1_len != 8448) return 2;
    for (unsigned i = 0; i < 8448; i++) if (r.c1[i] != (i & 255)) return 3;
    nvn_refl_destroy(&r);
    nvn_refl_destroy(&r); // safe after cleanup
    NSDictionary *bad = @{@"route": @"B", @"bindings": @[], @"c1": hex,
        @"vertex_inputs": @[@{@"location": @32}]};
    if (!nvn_refl_from_json(bad, &r, err, sizeof err) || r.c1 || r.has_c1) return 4;
    for (NSString *invalid in @[@"0", [@"00" stringByPaddingToLength:131072 withString:@"00" startingAtIndex:0]]) {
        if (!nvn_refl_from_json(@{@"route": @"B", @"bindings": @[], @"c1": invalid}, &r, err, sizeof err) || r.c1) return 5;
    }
    if (nvn_refl_from_json(@{@"route": @"B", @"bindings": @[]}, &r, err, sizeof err) || r.c1 || r.has_c1) return 6;
    nvn_refl_destroy(&r);
    return 0;
} }
''')
            exe = Path(tmp) / 'constants'
            build = subprocess.run(['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-I'+str(NVN), str(source), str(NVN/'nvn_refl.m'),
                '-framework', 'Foundation', '-framework', 'Metal', '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
