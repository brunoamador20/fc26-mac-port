"""Texture / sampler arrays in the B reflection (bindless texture access turned into an indexed array by the translator).

The base game aborted entering the "Encontro Clássico" match (logs/boot_base2b.log): fragment shader b9764ae7..._b declares
`array<texture2d<float>, 32> fp_t2d_cb196610_10570000 [[id(7)]]` and `array<sampler, 32> ..Smplr [[id(39)]]`; the json
has no reg for the texture array, so nvn_refl_from_json_msl failed with "B 绑定 fp_t2d_cb196610_10570000 没解出槽号"
(and then would have failed on its "c2 dynamic index", the array's own handle load).

Compiles the real nvn_refl.m. FC26_NVN_DIR points the test at another copy of the nvn sources (e.g. the previous commit).
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = Path(os.environ.get('FC26_NVN_DIR') or HERE / 'third_party/d2r_gfx/gfx/nvn')

# The reflection of b9764ae7..._b as the translator wrote it (c1 left out).
REAL_JSON = {
    'route': 'B', 'stage': 'ps', 'entry': 'main0',
    'bindings': [
        {'msl_name': 'fp_c2', 'msl_type': 'constant _16*', 'arg_id': 0, 'kind': 'drvcb', 'bank': 2},
        {'msl_name': 'fp_c3', 'msl_type': 'constant _16*', 'arg_id': 1, 'kind': 'cbuf', 'reg': 0},
        {'msl_name': 'fp_c1', 'msl_type': 'constant _16*', 'arg_id': 2, 'kind': 'c1', 'bank': 1},
        {'msl_name': 'fp_t_cb196610_1056805A', 'msl_type': 'texture2d<float>', 'arg_id': 3, 'kind': 'tex', 'reg': 0},
        {'msl_name': 'fp_t_cb196610_1056805ASmplr', 'msl_type': 'sampler', 'arg_id': 4, 'kind': 'samp', 'reg': 0},
        {'msl_name': 'fp_t_cb196610_1056806C', 'msl_type': 'texture2d<float>', 'arg_id': 5, 'kind': 'tex', 'reg': 9},
        {'msl_name': 'fp_t_cb196610_1056806CSmplr', 'msl_type': 'sampler', 'arg_id': 6, 'kind': 'samp', 'reg': 0},
        {'msl_name': 'fp_t2d_cb196610_10570000', 'msl_type': 'array<texture2d<float>, 32>', 'arg_id': 7, 'kind': 'tex', 'reg': None},
        {'msl_name': 'fp_t2d_cb196610_10570000Smplr', 'msl_type': 'array<sampler, 32>', 'arg_id': 39, 'kind': 'samp', 'reg': 1},
    ],
    'drv_reads': {'2': {'vec4_offsets': [], 'dynamic': True}},
    'drv_unfillable': ['c2 dynamic index'],
    'vertex_inputs': [], 'raster': {},
}
# Its argument struct, as spirv-cross wrote it, in a shader Metal can compile here.
ARG_MSL = '''#include <metal_stdlib>
using namespace metal;
struct _16 { float4 _m0[4096]; };
struct spvDescriptorSetBuffer0 {
    constant _16* fp_c2 [[id(0)]];
    constant _16* fp_c3 [[id(1)]];
    constant _16* fp_c1 [[id(2)]];
    texture2d<float> fp_t_cb196610_1056805A [[id(3)]];
    sampler fp_t_cb196610_1056805ASmplr [[id(4)]];
    texture2d<float> fp_t_cb196610_1056806C [[id(5)]];
    sampler fp_t_cb196610_1056806CSmplr [[id(6)]];
    array<texture2d<float>, 32> fp_t2d_cb196610_10570000 [[id(7)]];
    array<sampler, 32> fp_t2d_cb196610_10570000Smplr [[id(39)]];
};
fragment float4 main0(constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]], float4 p [[position]]) {
    uint i = min(uint((*spvDescriptorSet0.fp_c3)._m0[0].y), 31u);
    return spvDescriptorSet0.fp_t2d_cb196610_10570000[i].sample(spvDescriptorSet0.fp_t2d_cb196610_10570000Smplr[i], p.xy)
         + spvDescriptorSet0.fp_t_cb196610_1056805A.sample(spvDescriptorSet0.fp_t_cb196610_1056805ASmplr, p.xy)
         + spvDescriptorSet0.fp_t_cb196610_1056806C.sample(spvDescriptorSet0.fp_t_cb196610_1056806CSmplr, p.xy)
         + (*spvDescriptorSet0.fp_c2)._m0[int(p.x)] + (*spvDescriptorSet0.fp_c1)._m0[0];
}
'''


class NvnTexArrayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('clang not available')
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        runner = t / 'runner.m'
        runner.write_text(f'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import "{NVN_DIR}/nvn_refl.h"
#include <stdio.h>
#include <string.h>
int main(int argc, const char **argv) {{ @autoreleasepool {{
    if (!strcmp(argv[1], "abi")) {{   // encodedLength of the argument struct in argv[2]
        id<MTLDevice> d = MTLCreateSystemDefaultDevice(); if (!d) {{ printf("NODEV\\n"); return 0; }}
        NSError *e = nil; id<MTLLibrary> l = [d newLibraryWithSource:[NSString stringWithContentsOfFile:@(argv[2]) encoding:NSUTF8StringEncoding error:nil] options:nil error:&e];
        if (!l) {{ printf("COMPILE %s\\n", e.localizedDescription.UTF8String); return 1; }}
        id<MTLArgumentEncoder> ae = [[l newFunctionWithName:@"main0"] newArgumentEncoderWithBufferIndex:0];
        printf("LEN=%lu\\n", (unsigned long)ae.encodedLength); return 0;
    }}
    NSDictionary *j = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:nil];
    static nvn_refl rf; char err[256] = {{0}};
    int ret = nvn_refl_from_json_msl(j, @"", &rf, err, sizeof err);
    printf("REFL_RET=%d NB=%d ERR=%s\\n", ret, rf.nb, err);
    for (int i = 0; !ret && i < rf.nb; i++) printf("B aid=%d kind=%d reg=%d\\n", rf.b[i].aid, rf.b[i].kind, rf.b[i].reg);
    return 0;
}} }}
''', encoding='utf-8')
        cls.exe = t / 'runner'
        b = subprocess.run([cc, '-std=c11', '-fobjc-arc', '-framework', 'Foundation', '-framework', 'Metal', f'-I{NVN_DIR}',
                            str(NVN_DIR / 'nvn_refl.m'), str(runner), '-o', str(cls.exe)], capture_output=True, text=True)
        if b.returncode:
            raise AssertionError('runner build failed: ' + b.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def refl(self, js):
        p = Path(self.tmp.name) / 'r.json'
        p.write_text(json.dumps(js), encoding='utf-8')
        out = subprocess.run([str(self.exe), 'refl', str(p)], capture_output=True, text=True).stdout
        binds = {}
        for line in out.splitlines():
            if line.startswith('B '):
                f = dict(kv.split('=') for kv in line[2:].split())
                binds[int(f['aid'])] = (int(f['kind']), int(f['reg']))
        return out, binds

    def test_real_reflection_accepted_with_one_binding_per_element(self):
        out, binds = self.refl(REAL_JSON)
        self.assertIn('REFL_RET=0 NB=71', out, out)
        self.assertEqual(sorted(binds), list(range(71)))   # aids 0..70: 7 single + 32 textures + 32 samplers
        tex = binds[3][0]
        samp = binds[4][0]
        self.assertEqual(binds[3], (tex, 0))
        self.assertEqual(binds[5], (tex, 9))
        # texture element n: handle at c2 byte 8 n (o0 = 0) -> combined slot n - 4 for 4 <= n < 36, else empty
        for n in range(32):
            self.assertEqual(binds[7 + n], (tex, n - 4 if n >= 4 else 0xffff), n)
        # sampler elements: the separate sampler slot of the second handle word (0x15c words = c2 0x570 = slot 1)
        for n in range(32):
            self.assertEqual(binds[39 + n], (samp, 1), n)

    def test_element_offsets_follow_the_handle(self):
        js = json.loads(json.dumps(REAL_JSON))
        js['bindings'][7]['msl_name'] = 'fp_t2d_cb196610_1057005A'   # o0 = 0x5a words = c2 0x168: separate slot 0 onward
        js['bindings'][8]['msl_name'] = 'fp_t2d_cb196610_1057005ASmplr'
        out, binds = self.refl(js)
        self.assertIn('REFL_RET=0', out, out)
        for n in range(32):
            self.assertEqual(binds[7 + n][1], n, n)

    def test_dynamic_c2_still_refused_without_an_array(self):
        js = json.loads(json.dumps(REAL_JSON))
        js['bindings'] = js['bindings'][:7]
        out, _ = self.refl(js)
        self.assertIn('REFL_RET=1', out)
        self.assertIn('c2 dynamic index', out)

    def test_argument_layout_matches_the_element_aids(self):
        p = Path(self.tmp.name) / 'abi.metal'
        p.write_text(ARG_MSL, encoding='utf-8')
        out = subprocess.run([str(self.exe), 'abi', str(p)], capture_output=True, text=True).stdout
        if 'NODEV' in out:
            self.skipTest('no Metal device')
        self.assertIn('LEN=568', out, out)   # 8 * (max aid 70 + 1): what shader_load checks against the bindings


if __name__ == '__main__':
    unittest.main()
