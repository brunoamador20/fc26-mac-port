"""Dual-source blending (NVN blend factors SRC1_*, 0x10..0x13) in the match's scene pass.

Boot base2c / d3b logged 12 times "建渲染管线失败：Fragment shader does not write to render target color(0), index(1) that
is required for blending" (vs 2718e27f… / ps fd32c52a…, dfmt 252, cfmt0 92): the fragment shader writes two colour
outputs, the translator declares the second one [[color(1)]], and Metal reads the second blend source only from
[[color(0), index(1)]]. On Maxwell the second source of render target 0 is the shader's colour output 1, so the fix
moves that output (msl_dual_source) for draws whose render target 0 blends with SRC1 factors (pso_dual_source).

Compiles the real blend_src1, pso_dual_source and msl_dual_source cut out of nvn_mtl.m and builds the pipelines on the
real Metal device. FC26_NVN_DIR points the test at another copy of the nvn sources.
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = Path(os.environ.get('FC26_NVN_DIR') or HERE / 'third_party/d2r_gfx/gfx/nvn')

# The shape of the translator's output for fd32c52a… (two float4 outputs, both written).
MSL = r'''#include <metal_stdlib>
using namespace metal;
struct main0_out
{
    float4 m_69 [[color(0)]];
    float4 m_71 [[color(1)]];
};
fragment main0_out main0(float4 gl_FragCoord [[position]])
{
    main0_out out = {};
    out.m_69 = float4(0.25, 0.5, 0.75, 1.0);
    out.m_71 = float4(0.5);
    return out;
}
'''

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>
#include "nvn_obj.h"
%(FUNCS)s
static const char *k_msl = %(MSL)s;
static id<MTLRenderPipelineState> build(id<MTLDevice> d, NSString *src, int two_targets, NSString **err) {
    NSError *e = nil;
    id<MTLLibrary> lib = [d newLibraryWithSource:src options:nil error:&e];
    if (!lib) { *err = e.localizedDescription; return nil; }
    const char *vs = "#include <metal_stdlib>\nusing namespace metal;\nvertex float4 v(uint i [[vertex_id]]) { return float4(float(i & 1), float(i >> 1), 0.0, 1.0); }\n";
    id<MTLLibrary> vl = [d newLibraryWithSource:@(vs) options:nil error:&e];
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [vl newFunctionWithName:@"v"]; pd.fragmentFunction = [lib newFunctionWithName:@"main0"];
    MTLRenderPipelineColorAttachmentDescriptor *c = pd.colorAttachments[0];
    c.pixelFormat = MTLPixelFormatRG11B10Float; c.blendingEnabled = YES;
    c.sourceRGBBlendFactor = MTLBlendFactorOne; c.destinationRGBBlendFactor = MTLBlendFactorSource1Color;
    c.sourceAlphaBlendFactor = MTLBlendFactorOne; c.destinationAlphaBlendFactor = MTLBlendFactorZero;
    if (two_targets) pd.colorAttachments[1].pixelFormat = MTLPixelFormatRGBA8Unorm;
    pd.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;
    id<MTLRenderPipelineState> ps = [d newRenderPipelineStateWithDescriptor:pd error:&e];
    if (!ps) *err = e.localizedDescription;
    return ps;
}
int main(void) { @autoreleasepool {
    id<MTLDevice> d = MTLCreateSystemDefaultDevice(); if (!d) { printf("NODEV\n"); return 0; }
    pso_key k; memset(&k, 0, sizeof k); k.cfmt[0] = 92; k.blend_en = 1;
    k.blend[0].src_rgb = 2; k.blend[0].dst_rgb = 0x10; k.blend[0].src_a = 2; k.blend[0].dst_a = 1;
    int dual = pso_dual_source(&k);
    k.blend[0].dst_rgb = 6; int plain = pso_dual_source(&k);
    k.blend[0].dst_a = 0x13; int alpha = pso_dual_source(&k);
    k.blend_en = 0; int off = pso_dual_source(&k);
    k.blend_en = 2; k.blend[1].dst_rgb = 0x10; k.blend[0].dst_a = 1; int rt1 = pso_dual_source(&k);
    k.blend_en = 1; k.blend[0].dst_rgb = 0x10; k.cfmt[1] = 70; int multi = pso_dual_source(&k);
    printf("KEY dual=%d plain=%d alpha=%d off=%d rt1=%d multi=%d\n", dual, plain, alpha, off, rt1, multi);
    NSString *err = nil, *src = @(k_msl);
    id<MTLRenderPipelineState> before = build(d, src, 0, &err);
    printf("BEFORE ok=%d err=%s\n", before != nil, err ? err.UTF8String : "-");
    NSString *patched = msl_dual_source(src); err = nil;
    printf("PATCHED has=%d\n", patched && [patched rangeOfString:@"[[color(0), index(1)]]"].location != NSNotFound && [patched rangeOfString:@"[[color(1)]]"].location == NSNotFound);
    id<MTLRenderPipelineState> after = patched ? build(d, patched, 0, &err) : nil;
    printf("AFTER ok=%d err=%s\n", after != nil, err ? err.UTF8String : "-");
    NSString *none = msl_dual_source([src stringByReplacingOccurrencesOfString:@"[[color(1)]]" withString:@"[[user(locn1)]]"]);
    printf("NONE nil=%d\n", none == nil);
    return 0;
} }
'''


def _cut(src, pattern, what):
    m = re.search(pattern, src, re.M | re.S)
    if not m:
        raise AssertionError(f'{what} not found in nvn_mtl.m')
    return m.group(0)


@unittest.skipUnless(platform.system() == 'Darwin', 'needs Metal')
class NvnDualSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('clang not available')
        src = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        cls.missing = None
        try:
            skey = (NVN_DIR / 'nvn_pso_skey.h').read_text(encoding='utf-8')
            funcs = [_cut(skey, r'^typedef struct \{\n    const void \*vs, \*fs;.*?\} pso_key;\n', 'pso_key'),
                     _cut(src, r'^static int blend_src1\(int f\).*?\n', 'blend_src1'),
                     _cut(src, r'^static int pso_dual_source\(const pso_key \*k\) \{.*?\n}\n', 'pso_dual_source'),
                     _cut(src, r'^static NSString \*msl_dual_source\(NSString \*src\) \{.*?\n}\n', 'msl_dual_source')]
        except AssertionError as e:
            cls.missing = str(e)
            return
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        msl_c = '"' + MSL.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n"\n"') + '"'
        (t / 'h.m').write_text(HARNESS.replace('%(FUNCS)s', '\n'.join(funcs)).replace('%(MSL)s', msl_c), encoding='utf-8')
        cls.exe = t / 'h'
        r = subprocess.run([cc, '-fobjc-arc', '-w', f'-I{NVN_DIR}', f'-I{NVN_DIR / "include"}', '-framework', 'Foundation', '-framework', 'Metal',
                            str(t / 'h.m'), '-o', str(cls.exe)], capture_output=True, text=True)
        if r.returncode:
            raise AssertionError('harness does not compile:\n' + r.stderr[-3000:])
        r = subprocess.run([str(cls.exe)], capture_output=True, text=True, timeout=120)
        cls.out = r.stdout + r.stderr
        if 'NODEV' in cls.out:
            raise unittest.SkipTest('no Metal device')

    def setUp(self):
        if self.missing:
            self.fail(self.missing)

    def test_metal_refuses_the_translator_output(self):
        # the boot's error, reproduced: without the fix the pipeline is refused (draws dropped)
        self.assertIn('BEFORE ok=0', self.out)
        self.assertIn('index(1)', self.out.split('BEFORE ok=0', 1)[1].split('\n', 1)[0])

    def test_output_1_moved_to_the_second_blend_source(self):
        self.assertIn('PATCHED has=1', self.out)
        self.assertIn('AFTER ok=1', self.out)
        self.assertIn('NONE nil=1', self.out)

    def test_key_selects_only_src1_blends_of_target_0(self):
        self.assertIn('KEY dual=1 plain=0 alpha=1 off=0 rt1=0 multi=0', self.out)   # Metal: one colour attachment with dual source

    def test_pso_get_uses_the_variant(self):
        src = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        body = _cut(src, r'^static __unsafe_unretained id<MTLRenderPipelineState> pso_get\(.*?\n}\n', 'pso_get')
        self.assertRegex(body, r'pso_dual_source\(&k\)\) bfn = fs_fn_dual\(fs, k\.dfmt == 0\)')


if __name__ == '__main__':
    unittest.main()
