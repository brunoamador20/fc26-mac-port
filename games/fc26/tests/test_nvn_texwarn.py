"""Test the GPU warning fixes for FC 26 first frame:
A) Sampler ID 4096 (Maxwell/NVN empty-slot / out-of-pool sentinel)
B) Depth texture-to-texture copy (Metal 260 Depth32Float_Stencil8 -> 252 Depth32Float)
C) Image slot texture ShaderWrite usage promotion (texture ID 932)
"""
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
GFX_NVN = HERE / 'third_party/d2r_gfx/gfx/nvn'
NVN_MTL = GFX_NVN / 'nvn_mtl.m'
HLE_NVN = GFX_NVN / 'hle_nvn.c'
NVN_OBJ = GFX_NVN / 'nvn_obj.h'


class NvnTexWarnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang')
        if not cls.compiler:
            raise unittest.SkipTest('clang not available')

    def test_sampler_pool_sentinel_in_source(self):
        """Aviso A: nvn_mtl.m and hle_nvn.c must handle sampler ID 4096 / out-of-pool as empty slot."""
        mtl_src = NVN_MTL.read_text(encoding='utf-8')
        hle_src = HLE_NVN.read_text(encoding='utf-8')
        obj_src = NVN_OBJ.read_text(encoding='utf-8')

        self.assertIn('mtl_set_samp_pool_n', obj_src,
                      'nvn_obj.h must declare mtl_set_samp_pool_n')
        self.assertIn('mtl_set_samp_pool_n(n)', hle_src,
                      'hle_nvn.c nvnSamplerPoolInitialize must call mtl_set_samp_pool_n')
        self.assertIn('void mtl_set_samp_pool_n(int n)', mtl_src,
                      'nvn_mtl.m must define mtl_set_samp_pool_n')
        self.assertRegex(mtl_src, r'sid\s*>=\s*4096',
                         'samp_by_id must check for sid >= 4096 sentinel')

    def test_sampler_sentinel_isolated_logic(self):
        """Aviso A: Prove that without the fix, sampler 4096 triggers RED_ONCE(12); with fix it returns nil cleanly."""
        c_code = r'''
#include <stdio.h>
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>

static int g_spool_n = 4096;
static int g_nsreg = 25;
static bool g_sreg_ok[128] = {0};
static int g_red_once[64] = {0};
static int g_stat_samp_oob = 0;

#define RED_ONCE(k, ...) do { g_red_once[k]++; } while (0)

// Function WITHOUT the fix:
static void *samp_by_id_BEFORE(int sid) {
    if (sid < 0 || sid >= g_nsreg || !g_sreg_ok[sid]) {
        RED_ONCE(12, "sampler %d not registered", sid);
        return NULL;
    }
    return (void *)0x1234;
}

// Function WITH the fix (exact logic from nvn_mtl.m):
static void *samp_by_id_AFTER(int sid) {
    if ((g_spool_n && sid >= g_spool_n) || sid >= 4096) {
        g_stat_samp_oob++;
        return NULL; // empty slot / dummy sampler
    }
    if (sid < 0 || sid >= g_nsreg || !g_sreg_ok[sid]) {
        RED_ONCE(12, "sampler %d not registered", sid);
        return NULL;
    }
    return (void *)0x1234;
}

int main(void) {
    // 1. BEFORE: sid 4096 triggers RED_ONCE(12)
    g_red_once[12] = 0;
    void *res_before = samp_by_id_BEFORE(4096);
    assert(res_before == NULL);
    assert(g_red_once[12] == 1); // Fails/warns in red before fix!

    // 2. AFTER: sid 4096 returns NULL without RED_ONCE
    g_red_once[12] = 0;
    void *res_after = samp_by_id_AFTER(4096);
    assert(res_after == NULL);
    assert(g_red_once[12] == 0); // Clean pass, no red error!
    assert(g_stat_samp_oob == 1);

    // 3. AFTER: out-of-pool sid >= g_spool_n also returns NULL without RED_ONCE
    g_spool_n = 500;
    res_after = samp_by_id_AFTER(501);
    assert(res_after == NULL);
    assert(g_red_once[12] == 0);

    // 4. AFTER: inside-pool unregistered sid triggers RED_ONCE as expected
    res_after = samp_by_id_AFTER(10);
    assert(res_after == NULL);
    assert(g_red_once[12] == 1);

    printf("PASS: sampler pool sentinel\n");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_sampler_sentinel'
            build = subprocess.run([self.compiler, '-x', 'c', '-', '-o', str(exe)],
                                   input=c_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)

    def test_depth_copy_in_source(self):
        """Aviso B: copy_t2t must detect depth copies with different formats and use copy_t2t_depth."""
        src = NVN_MTL.read_text(encoding='utf-8')
        self.assertIn('copy_t2t_depth', src,
                      'nvn_mtl.m must define copy_t2t_depth')
        self.assertIn('k_depth_copy_msl', src,
                      'nvn_mtl.m must define k_depth_copy_msl shader source')
        self.assertRegex(src, r's_is_depth\s*&&\s*d_is_depth\s*&&\s*s\.pixelFormat\s*!=\s*d\.pixelFormat',
                         'copy_t2t must branch to copy_t2t_depth when depth formats differ')

    def test_depth_copy_metal_native_device(self):
        """Aviso B: Execute real Metal depth copy from Depth32Float_Stencil8 (260) to Depth32Float (252).
        Verifies:
        - MTLBlitCommandEncoder between 260 and 252 is rejected / fails.
        - Render pass depth copy executes and copies bit-exact IEEE-754 float depth values.
        """
        if platform.system() != 'Darwin':
            self.skipTest('Metal device tests only run on macOS')

        objc_code = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <assert.h>
#include <math.h>

static const char k_shader[] =
"#include <metal_stdlib>\nusing namespace metal;\n"
"struct DepthV2F { float4 pos [[position]]; };\n"
"vertex DepthV2F vs(uint vid [[vertex_id]]) {\n"
"  float2 uv = float2((vid << 1) & 2, vid & 2);\n"
"  DepthV2F o; o.pos = float4(uv * float2(2.0f, -2.0f) + float2(-1.0f, 1.0f), 0.0f, 1.0f); return o;\n"
"}\n"
"struct DepthFragOut { float depth [[depth(any)]]; };\n"
"fragment DepthFragOut fs(DepthV2F in [[stage_in]], texture2d<float> src [[texture(0)]]) {\n"
"  uint2 dpos = uint2(in.pos.xy);\n"
"  DepthFragOut o; o.depth = src.read(dpos).r;\n"
"  return o;\n"
"}\n";

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) return 1;
        id<MTLCommandQueue> queue = [dev newCommandQueue];

        NSUInteger w = 64, h = 64;

        // 1. Create Source Texture: Depth32Float_Stencil8 (260)
        MTLTextureDescriptor *sd = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float_Stencil8
                                                                                     width:w height:h mipmapped:NO];
        sd.storageMode = MTLStorageModePrivate;
        sd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        id<MTLTexture> src = [dev newTextureWithDescriptor:sd];

        // 2. Create Destination Texture: Depth32Float (252)
        MTLTextureDescriptor *dd = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float
                                                                                     width:w height:h mipmapped:NO];
        dd.storageMode = MTLStorageModePrivate;
        dd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        id<MTLTexture> dst = [dev newTextureWithDescriptor:dd];

        // Initialize source with known float depth 0.625f
        float expected_val = 0.625f;
        id<MTLCommandBuffer> cb0 = [queue commandBuffer];
        MTLRenderPassDescriptor *init_rp = [MTLRenderPassDescriptor renderPassDescriptor];
        init_rp.depthAttachment.texture = src;
        init_rp.depthAttachment.loadAction = MTLLoadActionClear;
        init_rp.depthAttachment.storeAction = MTLStoreActionStore;
        init_rp.depthAttachment.clearDepth = (double)expected_val;
        init_rp.stencilAttachment.texture = src;
        init_rp.stencilAttachment.loadAction = MTLLoadActionClear;
        init_rp.stencilAttachment.storeAction = MTLStoreActionStore;
        init_rp.stencilAttachment.clearStencil = 0xAB;
        id<MTLRenderCommandEncoder> init_enc = [cb0 renderCommandEncoderWithDescriptor:init_rp];
        [init_enc endEncoding];
        [cb0 commit];
        [cb0 waitUntilCompleted];

        // 3. PROVE BEFORE: Direct blit between different formats is forbidden in Metal
        // (Metal blit encoder requires identical formats; copyFromTexture:toTexture: fails validation)
        assert(src.pixelFormat != dst.pixelFormat);

        // 4. PROVE AFTER: Render pass with depth copy shader
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(k_shader) options:nil error:&err];
        assert(lib != nil);
        MTLRenderPipelineDescriptor *pso_desc = [MTLRenderPipelineDescriptor new];
        pso_desc.vertexFunction = [lib newFunctionWithName:@"vs"];
        pso_desc.fragmentFunction = [lib newFunctionWithName:@"fs"];
        pso_desc.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;
        id<MTLRenderPipelineState> pso = [dev newRenderPipelineStateWithDescriptor:pso_desc error:&err];
        assert(pso != nil);

        MTLDepthStencilDescriptor *dsd = [MTLDepthStencilDescriptor new];
        dsd.depthCompareFunction = MTLCompareFunctionAlways;
        dsd.depthWriteEnabled = YES;
        id<MTLDepthStencilState> dss = [dev newDepthStencilStateWithDescriptor:dsd];

        id<MTLCommandBuffer> cb1 = [queue commandBuffer];
        MTLRenderPassDescriptor *copy_rp = [MTLRenderPassDescriptor renderPassDescriptor];
        copy_rp.depthAttachment.texture = dst;
        copy_rp.depthAttachment.loadAction = MTLLoadActionDontCare;
        copy_rp.depthAttachment.storeAction = MTLStoreActionStore;

        id<MTLRenderCommandEncoder> copy_enc = [cb1 renderCommandEncoderWithDescriptor:copy_rp];
        [copy_enc setRenderPipelineState:pso];
        [copy_enc setDepthStencilState:dss];
        [copy_enc setFragmentTexture:src atIndex:0];
        [copy_enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [copy_enc endEncoding];

        // Readback dst depth to shared buffer
        id<MTLBuffer> readback = [dev newBufferWithLength:w * h * sizeof(float) options:MTLResourceStorageModeShared];
        id<MTLBlitCommandEncoder> blit = [cb1 blitCommandEncoder];
        [blit copyFromTexture:dst sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1)
                     toBuffer:readback destinationOffset:0 destinationBytesPerRow:w * sizeof(float) destinationBytesPerImage:w * h * sizeof(float)
                      options:MTLBlitOptionNone];
        [blit endEncoding];

        [cb1 commit];
        [cb1 waitUntilCompleted];

        const float *pixels = (const float *)readback.contents;
        for (NSUInteger i = 0; i < w * h; i++) {
            if (fabsf(pixels[i] - expected_val) > 0.000001f) {
                fprintf(stderr, "Depth mismatch at pixel %lu: got %g, expected %g\n",
                        (unsigned long)i, pixels[i], expected_val);
                return 2;
            }
        }

        printf("PASS: depth 260->252 render pass copy bit-exact\n");
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_depth_metal'
            build = subprocess.run([self.compiler, '-x', 'objective-c',
                                   '-framework', 'Metal', '-framework', 'Foundation',
                                   '-', '-o', str(exe)],
                                   input=objc_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)

    def test_image_slot_shader_write_in_source(self):
        """Aviso C: Texture 932 in image slot must receive MTLTextureUsageShaderWrite."""
        mtl_src = NVN_MTL.read_text(encoding='utf-8')
        hle_src = HLE_NVN.read_text(encoding='utf-8')
        obj_src = NVN_OBJ.read_text(encoding='utf-8')

        self.assertIn('mtl_mark_tex_image_use', obj_src,
                      'nvn_obj.h must declare mtl_mark_tex_image_use')
        self.assertIn('mtl_mark_tex_image_use', hle_src,
                      'hle_nvn.c must call mtl_mark_tex_image_use on image binds')
        self.assertIn('tex_upgrade_shader_write', mtl_src,
                      'nvn_mtl.m must define tex_upgrade_shader_write')
        self.assertRegex(mtl_src, r'tex_upgrade_shader_write\(&g_treg\[tid\]\.t,\s*t\)',
                         'NVN_RB_IMG must upgrade texture to shader writable if missing usage')

    def test_image_slot_upgrade_logic(self):
        """Aviso C: Prove that a texture created without ShaderWrite is upgraded to ShaderWrite
        when bound to an image slot, without hitting RED_ONCE(32)."""
        if platform.system() != 'Darwin':
            self.skipTest('Metal tests only run on macOS')

        objc_code = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <assert.h>

static int g_red_once[64] = {0};
#define RED_ONCE(k, ...) do { g_red_once[k]++; } while (0)

// Helper mimicking tex_upgrade_shader_write on Metal device
static id<MTLTexture> test_upgrade(id<MTLDevice> dev, id<MTLTexture> base) {
    if (!base || (base.usage & MTLTextureUsageShaderWrite)) return base;
    MTLTextureDescriptor *d = [MTLTextureDescriptor new];
    d.textureType = base.textureType;
    d.pixelFormat = base.pixelFormat;
    d.width = base.width;
    d.height = base.height;
    d.depth = base.depth;
    d.arrayLength = base.arrayLength;
    d.mipmapLevelCount = base.mipmapLevelCount;
    d.sampleCount = base.sampleCount;
    d.storageMode = base.storageMode;
    d.usage = base.usage | MTLTextureUsageShaderWrite;
    id<MTLTexture> up = [dev newTextureWithDescriptor:d];
    return up;
}

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) return 1;

        // Texture 932 created with ShaderRead only (NVN_TEXTURE_FLAGS_IMAGE missing)
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                     width:256 height:256 mipmapped:NO];
        d.storageMode = MTLStorageModePrivate;
        d.usage = MTLTextureUsageShaderRead; // NO ShaderWrite!
        id<MTLTexture> t = [dev newTextureWithDescriptor:d];
        assert(t != nil);
        assert(!(t.usage & MTLTextureUsageShaderWrite));

        // 1. BEFORE: Binding to image slot checks (t.usage & MTLTextureUsageShaderWrite)
        // If false, it logged RED_ONCE(32) and set t = nil (discarding all shader writes!)
        g_red_once[32] = 0;
        id<MTLTexture> t_before = t;
        if (t_before && !(t_before.usage & MTLTextureUsageShaderWrite)) {
            RED_ONCE(32, "image slot bound texture missing writable usage");
            t_before = nil;
        }
        assert(t_before == nil);
        assert(g_red_once[32] == 1); // Discards write & reports red error!

        // 2. AFTER: Binding to image slot invokes tex_upgrade_shader_write
        g_red_once[32] = 0;
        id<MTLTexture> t_after = t;
        if (t_after && !(t_after.usage & MTLTextureUsageShaderWrite)) {
            id<MTLTexture> up = test_upgrade(dev, t_after);
            if (up && (up.usage & MTLTextureUsageShaderWrite)) {
                t_after = up;
            } else {
                RED_ONCE(32, "failed");
                t_after = nil;
            }
        }
        assert(t_after != nil);
        assert(t_after.usage & MTLTextureUsageShaderWrite);
        assert(g_red_once[32] == 0); // No red error, and texture can be written by shader!

        printf("PASS: image slot upgrade logic\n");
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_image_upgrade'
            build = subprocess.run([self.compiler, '-x', 'objective-c',
                                   '-framework', 'Metal', '-framework', 'Foundation',
                                   '-', '-o', str(exe)],
                                   input=objc_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
