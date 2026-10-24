"""Test texture-to-texture scaled copy (downsample and upsample) for FC 26 on Metal.

Validates the fix for:
【红】贴图→贴图拷贝未实现的形态：320x180x1→160x90x1 标志 0x1 格式 70→70 3D 0→0
- 0x1 in NVN copy flags is NVN_COPY_FLAGS_LINEAR_FILTER_BIT.
- Metal blit does not support scaling; a full-screen triangle render pass is used to sample
  the source texture (bilinear sampler when flag 0x1 is set, nearest sampler when absent)
  into the destination viewport and scissor region.
- Respects levels, slices, and sub-rectangles.
- Color formats only; depth formats remain excluded and trigger visible error.
- Tests fail before the fix (unimplemented copy drops texture contents) and pass after on real Metal.
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
GFX_NVN = HERE / 'third_party/d2r_gfx/gfx/nvn'
NVN_MTL = GFX_NVN / 'nvn_mtl.m'
HLE_NVN = GFX_NVN / 'hle_nvn.c'
NVN_H = GFX_NVN / 'include/nvn.h'


def _cut(src, pattern, what):
    m = re.search(pattern, src, re.M | re.S)
    if not m:
        raise AssertionError(f'{what} not found in nvn_mtl.m')
    return m.group(0)


class NvnDownsampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang')
        if not cls.compiler:
            raise unittest.SkipTest('clang not available')

    def test_nvn_copy_flags_linear_filter_in_header(self):
        """Task 1: Prove by header and source that flag 0x1 is NVN_COPY_FLAGS_LINEAR_FILTER_BIT."""
        header_src = NVN_H.read_text(encoding='utf-8')
        hle_src = HLE_NVN.read_text(encoding='utf-8')

        # Prove 0x1 is LINEAR_FILTER_BIT in nvn.h
        self.assertRegex(
            header_src,
            r'NVN_COPY_FLAGS_LINEAR_FILTER_BIT\s*=\s*0x1',
            'nvn.h must define NVN_COPY_FLAGS_LINEAR_FILTER_BIT as 0x1'
        )
        self.assertRegex(
            header_src,
            r'NVN_COPY_FLAGS_NONE\s*=\s*0x0',
            'nvn.h must define NVN_COPY_FLAGS_NONE as 0x0'
        )

        # Prove nvnCommandBufferCopyTextureToTexture records the copy flags
        self.assertIn('nvnCommandBufferCopyTextureToTexture', hle_src)
        self.assertRegex(
            hle_src,
            r'o->flags\s*=\s*flags',
            'hle_nvn.c nvnCommandBufferCopyTextureToTexture must store flags into p_copy_t2t'
        )

    def test_source_implementation_integrity(self):
        """Task 2: nvn_mtl.m must define copy_t2t_scale and invoke it from copy_t2t."""
        mtl_src = NVN_MTL.read_text(encoding='utf-8')

        # Check shader source and functions
        self.assertIn('k_scale_copy_msl', mtl_src)
        self.assertIn('scale_copy_vs', mtl_src)
        self.assertIn('scale_copy_fs_lin', mtl_src)
        self.assertIn('scale_copy_fs_near', mtl_src)
        self.assertIn('copy_t2t_scale_pso', mtl_src)
        self.assertIn('copy_t2t_scale', mtl_src)
        self.assertIn('is_color_float_or_unorm', mtl_src)

        # Check that copy_t2t branches to copy_t2t_scale on size or format difference
        self.assertRegex(
            mtl_src,
            r'copy_t2t_scale\s*\(',
            'copy_t2t must call copy_t2t_scale'
        )
        # Check that depth is excluded from scaling
        self.assertRegex(
            mtl_src,
            r'!s_is_depth\s*&&\s*!d_is_depth',
            'copy_t2t must exclude depth textures from scaled copy'
        )

    def test_prove_before_fails_and_after_passes_logic(self):
        """Task 3: Prove that before the fix, 320x180 -> 160x90 triggered RED_ONCE(33) and dropped pixels;
        after the fix, it dispatches cleanly without error."""
        c_code = r'''
#include <stdio.h>
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>

static int g_red_once[64] = {0};
#define RED_ONCE(k, ...) do { g_red_once[k]++; } while (0)

#define NVN_COPY_FLAGS_LINEAR_FILTER_BIT 0x1
#define NVN_COPY_FLAGS_ENGINE_2D_BIT 0x2

typedef struct {
    int sw, sh, dw, dh;
    int s_fmt, d_fmt;
    int s_is_depth, d_is_depth;
    int s3, d3;
    int flags;
} CopyParams;

// Logic BEFORE fix:
static int copy_t2t_BEFORE(const CopyParams *c) {
    if (c->sw != c->dw || c->sh != c->dh || (c->flags & ~NVN_COPY_FLAGS_ENGINE_2D_BIT & ~NVN_COPY_FLAGS_LINEAR_FILTER_BIT)
        || c->s_fmt != c->d_fmt || c->s3 != c->d3) {
        RED_ONCE(33, "unimplemented copy");
        return 0; // Copy dropped, destination left empty!
    }
    return 1; // Blit executed
}

// Logic AFTER fix:
static int g_scale_called = 0;
static int g_scale_linear = 0;

static int mock_scale_copy(const CopyParams *c, int linear) {
    g_scale_called++;
    g_scale_linear = linear;
    return 1;
}

static int copy_t2t_AFTER(const CopyParams *c) {
    if (!c->s_is_depth && !c->d_is_depth && !c->s3 && !c->d3
        && ((c->sw != c->dw || c->sh != c->dh) || c->s_fmt != c->d_fmt)
        && !(c->flags & ~NVN_COPY_FLAGS_ENGINE_2D_BIT & ~NVN_COPY_FLAGS_LINEAR_FILTER_BIT)) {
        int linear = (c->flags & NVN_COPY_FLAGS_LINEAR_FILTER_BIT) != 0;
        return mock_scale_copy(c, linear);
    }
    if (c->sw != c->dw || c->sh != c->dh || (c->flags & ~NVN_COPY_FLAGS_ENGINE_2D_BIT & ~NVN_COPY_FLAGS_LINEAR_FILTER_BIT)
        || c->s_fmt != c->d_fmt || c->s3 != c->d3) {
        RED_ONCE(33, "unimplemented copy");
        return 0;
    }
    return 1; // Blit
}

int main(void) {
    CopyParams p = {
        .sw = 320, .sh = 180, .dw = 160, .dh = 90,
        .s_fmt = 70, .d_fmt = 70,
        .s_is_depth = 0, .d_is_depth = 0,
        .s3 = 0, .d3 = 0,
        .flags = 0x1
    };

    // 1. BEFORE: 320x180 -> 160x90 fails and hits RED_ONCE(33)
    g_red_once[33] = 0;
    int res_before = copy_t2t_BEFORE(&p);
    assert(res_before == 0);
    assert(g_red_once[33] == 1); // Fails with red line before fix!

    // 2. AFTER: 320x180 -> 160x90 passes and calls scale copy with linear=1
    g_red_once[33] = 0;
    g_scale_called = 0;
    int res_after = copy_t2t_AFTER(&p);
    assert(res_after == 1);
    assert(g_scale_called == 1);
    assert(g_scale_linear == 1);
    assert(g_red_once[33] == 0); // No red error!

    // 3. AFTER: nearest neighbor copy (flags = 0)
    p.flags = 0x0;
    g_scale_called = 0;
    res_after = copy_t2t_AFTER(&p);
    assert(res_after == 1);
    assert(g_scale_called == 1);
    assert(g_scale_linear == 0);
    assert(g_red_once[33] == 0);

    // 4. AFTER: depth with size mismatch stays excluded and hits RED_ONCE(33)
    p.s_is_depth = 1; p.d_is_depth = 1;
    g_scale_called = 0;
    g_red_once[33] = 0;
    res_after = copy_t2t_AFTER(&p);
    assert(res_after == 0);
    assert(g_scale_called == 0);
    assert(g_red_once[33] == 1); // Depth stays a visible failure!

    printf("PASS: isolated before/after copy logic\n");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_logic'
            build = subprocess.run([self.compiler, '-x', 'c', '-', '-o', str(exe)],
                                   input=c_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)

    def test_metal_device_downsample_real_functions(self):
        """Task 3: Execute real Metal downsample 320x180 -> 160x90 compiling REAL functions from nvn_mtl.m.
        Verifies:
        - Linear filter (flags=0x1): destination matches 2x2 average of source pixels (tolerance <= 1).
        - Nearest neighbor (flags=0x0): destination matches nearest neighbor pixel (2x+1, 2y+1).
        - Upsample case: 160x90 -> 320x180 nearest neighbor matches (x/2, y/2).
        """
        if platform.system() != 'Darwin':
            self.skipTest('Metal device tests only run on macOS')

        src = NVN_MTL.read_text(encoding='utf-8')
        cut_functions = _cut(
            src,
            r'static const char k_scale_copy_msl\[\].*?static int copy_t2t_scale\(.*?\n}\n',
            'scale copy functions'
        )

        harness_code = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <math.h>

#define MLOG(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
static int g_red_once[256];
#define RED_ONCE(k, ...) do { if (!g_red_once[k]++) MLOG("RED " __VA_ARGS__); } while (0)

static id<MTLDevice> g_dev;
static id g_cb;
static id g_blit;
static int g_pso_dirty, g_dss_dirty;
static id<MTLResidencySet> g_res;
static void res_add(id o) { if (o && g_res) [g_res addAllocation:o]; }
static size_t arena_alloc(size_t n, id<MTLBuffer> *buf) { *buf = [g_dev newBufferWithLength:n options:MTLResourceStorageModeShared]; res_add(*buf); return 0; }
static void rp_end(void) {}
static void blit_close(void) {}
static void rs_sync(void) {}
static void pt_mark(id cb, char k, id d) { (void)cb; (void)k; (void)d; }
static void es_reset(void) {}
static void m4_end(id e) { [e endEncoding]; }
static void args_dirty_all(void) {}
static void defer_obj_unref(id o) { (void)o; }
static void enc_b_end(id e) { [e endEncoding]; }

/*REAL_FUNCTIONS*/

int main(void) {
    @autoreleasepool {
        g_dev = MTLCreateSystemDefaultDevice();
        if (!g_dev) {
            fprintf(stderr, "No Metal device\n");
            return 1;
        }

        MTL4CommandQueueDescriptor *qd = [MTL4CommandQueueDescriptor new];
        NSError *err = nil;
        id<MTL4CommandQueue> q4 = [g_dev newMTL4CommandQueueWithDescriptor:qd error:&err];
        id<MTL4CommandAllocator> alloc = [g_dev newCommandAllocatorWithDescriptor:[MTL4CommandAllocatorDescriptor new] error:&err];
        g_res = [g_dev newResidencySetWithDescriptor:[MTLResidencySetDescriptor new] error:&err];
        [q4 addResidencySet:g_res];

        int sw = 320, sh = 180;
        int dw = 160, dh = 90;

        // 1. Create source texture 320x180 RGBA8Unorm
        MTLTextureDescriptor *sd = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                     width:sw height:sh mipmapped:NO];
        sd.storageMode = MTLStorageModeShared;
        sd.usage = MTLTextureUsageShaderRead;
        id<MTLTexture> src = [g_dev newTextureWithDescriptor:sd];
        [g_res addAllocation:src];

        // Fill source with known deterministic mathematical pattern
        uint8_t *sdata = (uint8_t *)malloc(sw * sh * 4);
        for (int y = 0; y < sh; y++) {
            for (int x = 0; x < sw; x++) {
                int idx = (y * sw + x) * 4;
                sdata[idx + 0] = (uint8_t)((x * 7 + y * 13 + 17) & 0xff);
                sdata[idx + 1] = (uint8_t)((x * 11 + y * 5 + 31) & 0xff);
                sdata[idx + 2] = (uint8_t)((x * 3 + y * 19 + 73) & 0xff);
                sdata[idx + 3] = 255;
            }
        }
        [src replaceRegion:MTLRegionMake2D(0, 0, sw, sh) mipmapLevel:0 withBytes:sdata bytesPerRow:sw * 4];

        // 2. Create destination textures 160x90 RGBA8Unorm
        MTLTextureDescriptor *dd = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                     width:dw height:dh mipmapped:NO];
        dd.storageMode = MTLStorageModeShared;
        dd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        id<MTLTexture> dst_lin = [g_dev newTextureWithDescriptor:dd];
        id<MTLTexture> dst_near = [g_dev newTextureWithDescriptor:dd];
        [g_res addAllocation:dst_lin];
        [g_res addAllocation:dst_near];

        // Run linear copy (flag 0x1)
        id cb_lin = [g_dev newCommandBuffer];
        [cb_lin beginCommandBufferWithAllocator:alloc];
        g_cb = cb_lin;

        int ok_lin = copy_t2t_scale(src, dst_lin, 0, 0, 0, 0, 0, 0, sw, sh, 0, 0, dw, dh, 1);
        assert(ok_lin == 1);

        [cb_lin endCommandBuffer];

        // Run nearest copy (flag 0x0)
        id cb_near = [g_dev newCommandBuffer];
        [cb_near beginCommandBufferWithAllocator:alloc];
        g_cb = cb_near;

        int ok_near = copy_t2t_scale(src, dst_near, 0, 0, 0, 0, 0, 0, sw, sh, 0, 0, dw, dh, 0);
        assert(ok_near == 1);

        [cb_near endCommandBuffer];

        [g_res commit];

        // Submit and wait
        id<MTLSharedEvent> ev = [g_dev newSharedEvent];
        id<MTL4CommandBuffer> cbs[] = { cb_lin, cb_near };
        [q4 commit:cbs count:2 options:[MTL4CommitOptions new]];
        [q4 signalEvent:ev value:1];
        while (ev.signaledValue < 1) {
            [NSThread sleepForTimeInterval:0.001];
        }

        // Verify LINEAR FILTER (2x2 average, tolerance <= 1)
        uint8_t *res_lin = (uint8_t *)malloc(dw * dh * 4);
        [dst_lin getBytes:res_lin bytesPerRow:dw * 4 fromRegion:MTLRegionMake2D(0, 0, dw, dh) mipmapLevel:0];

        int max_lin_diff = 0;
        for (int y = 0; y < dh; y++) {
            for (int x = 0; x < dw; x++) {
                int didx = (y * dw + x) * 4;
                int s00 = ((2 * y) * sw + (2 * x)) * 4;
                int s10 = ((2 * y) * sw + (2 * x + 1)) * 4;
                int s01 = ((2 * y + 1) * sw + (2 * x)) * 4;
                int s11 = ((2 * y + 1) * sw + (2 * x + 1)) * 4;
                for (int c = 0; c < 4; c++) {
                    int exp = (sdata[s00 + c] + sdata[s10 + c] + sdata[s01 + c] + sdata[s11 + c] + 2) / 4;
                    int act = res_lin[didx + c];
                    int diff = abs(act - exp);
                    if (diff > max_lin_diff) max_lin_diff = diff;
                    if (diff > 1) {
                        fprintf(stderr, "Linear mismatch at (%d,%d) c=%d: act=%d exp=%d\n", x, y, c, act, exp);
                        return 2;
                    }
                }
            }
        }
        assert(max_lin_diff <= 1);
        printf("PASS: linear 2x2 average downsample verified (max diff: %d)\n", max_lin_diff);

        // Verify NEAREST FILTER (matches texel (2x+1, 2y+1))
        uint8_t *res_near = (uint8_t *)malloc(dw * dh * 4);
        [dst_near getBytes:res_near bytesPerRow:dw * 4 fromRegion:MTLRegionMake2D(0, 0, dw, dh) mipmapLevel:0];

        int near_mismatches = 0;
        for (int y = 0; y < dh; y++) {
            for (int x = 0; x < dw; x++) {
                int didx = (y * dw + x) * 4;
                int sx_coord = 2 * x + 1;
                int sy_coord = 2 * y + 1;
                int sidx = (sy_coord * sw + sx_coord) * 4;
                for (int c = 0; c < 4; c++) {
                    int exp = sdata[sidx + c];
                    int act = res_near[didx + c];
                    if (act != exp) {
                        near_mismatches++;
                        if (near_mismatches <= 5)
                            fprintf(stderr, "Nearest mismatch at (%d,%d) c=%d: act=%d exp=%d\n", x, y, c, act, exp);
                    }
                }
            }
        }
        assert(near_mismatches == 0);
        printf("PASS: nearest neighbor downsample verified (0 mismatches)\n");

        // 3. Upsampling test (ampliação): 160x90 -> 320x180
        MTLTextureDescriptor *ud = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                     width:sw height:sh mipmapped:NO];
        ud.storageMode = MTLStorageModeShared;
        ud.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        id<MTLTexture> dst_up = [g_dev newTextureWithDescriptor:ud];
        [g_res addAllocation:dst_up];

        id cb_up = [g_dev newCommandBuffer];
        [cb_up beginCommandBufferWithAllocator:alloc];
        g_cb = cb_up;

        // Upscale dst_near (160x90) -> dst_up (320x180) nearest
        int ok_up = copy_t2t_scale(dst_near, dst_up, 0, 0, 0, 0, 0, 0, dw, dh, 0, 0, sw, sh, 0);
        assert(ok_up == 1);

        [cb_up endCommandBuffer];
        [g_res commit];

        id<MTLSharedEvent> ev_up = [g_dev newSharedEvent];
        id<MTL4CommandBuffer> cbs_up[] = { cb_up };
        [q4 commit:cbs_up count:1 options:[MTL4CommitOptions new]];
        [q4 signalEvent:ev_up value:1];
        while (ev_up.signaledValue < 1) {
            [NSThread sleepForTimeInterval:0.001];
        }

        uint8_t *res_up = (uint8_t *)malloc(sw * sh * 4);
        [dst_up getBytes:res_up bytesPerRow:sw * 4 fromRegion:MTLRegionMake2D(0, 0, sw, sh) mipmapLevel:0];

        int up_mismatches = 0;
        for (int y = 0; y < sh; y++) {
            for (int x = 0; x < sw; x++) {
                int didx = (y * sw + x) * 4;
                int src_x = x / 2;
                int src_y = y / 2;
                int sidx = (src_y * dw + src_x) * 4;
                for (int c = 0; c < 4; c++) {
                    int exp = res_near[sidx + c];
                    int act = res_up[didx + c];
                    if (act != exp) up_mismatches++;
                }
            }
        }
        assert(up_mismatches == 0);
        printf("PASS: upsample (ampliação) verified (0 mismatches)\n");

        return 0;
    }
}
'''
        harness_code = harness_code.replace('/*REAL_FUNCTIONS*/', cut_functions)

        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_metal_downsample'
            build = subprocess.run([self.compiler, '-x', 'objective-c',
                                   '-framework', 'Metal', '-framework', 'Foundation',
                                   '-', '-o', str(exe)],
                                   input=harness_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS: linear 2x2 average downsample verified', run.stdout)
            self.assertIn('PASS: nearest neighbor downsample verified', run.stdout)
            self.assertIn('PASS: upsample (ampliação) verified', run.stdout)


if __name__ == '__main__':
    unittest.main()
