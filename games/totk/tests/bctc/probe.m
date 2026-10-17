// probe-gpu-bctc: the GPU transcoder for GPUs without BC (third_party/d2r_gfx/gfx/tex/nvn_bctc.metal): BC2/BC3/BC7 ->
// ASTC 4x4 and BC4/BC5 -> EAC R11/RG11, decoded again by Metal and compared with the reference decode (bcdec).
//  1. the kernel's own BC decoders (written as raw texels) against bcdec: BC7 exact on random blocks of every mode,
//     BC2/BC3 within 1 (palette rounding);
//  2. per format and block kind, PSNR and largest error of Metal's decode of the transcoded blocks against bcdec:
//     smooth blocks (close endpoints) must be close; random blocks are noise and are only reported;
//  3. the dual-plane ASTC mode (varying alpha, endpoints in the 48-level trit range) on blocks it can represent:
//     two alpha levels and colours on a line -> small error (a wrong trit / unquantisation table shows here at once).
// TOTK_PROBE_NEGATIVE=1 flips one bit in every transcoded block: the smooth checks must then fail.
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define BCDEC_IMPLEMENTATION
#define BCDEC_BC4BC5_PRECISE
#include "../../third_party/d2r_gfx/third_party/bcdec/bcdec.h"
#include "../../third_party/d2r_gfx/gfx/tex/nvn_bctc_msl.h"

enum { W = 256, H = 256, BW = W / 4, BH = H / 4, NB = BW * BH };
static uint32_t rng = 777;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static int checks, fails;
static void check(int ok, const char *what, double v) { checks++; if (!ok) { fails++; fprintf(stderr, "FAIL %s (%.3f)\n", what, v); } }

typedef struct { uint8_t b[16]; int bits; } bw_t;   // little-endian bit writer for BC7 blocks
static void wb(bw_t *w, int n, uint32_t v) { for (int i = 0; i < n; i++, w->bits++) if (v >> i & 1) w->b[w->bits >> 3] |= (uint8_t)(1 << (w->bits & 7)); }

// kind 0 smooth, 1 random, 2 two-level alpha with colours on a line (dual plane)
static void gen(int fmt, int kind, uint8_t *b) {
    memset(b, 0, 16);
    if (fmt == 0x4d) {   // BC7
        if (kind == 1) { for (int i = 0; i < 16; i++) b[i] = (uint8_t)rnd(); return; }
        bw_t w = {{0}, 0}; wb(&w, 7, 0x40);   // mode 6: single subset, RGBA 7 bits + p-bit, 4-bit indices
        int base[4], d = kind == 0 ? 8 : 60;
        for (int c = 0; c < 4; c++) base[c] = (int)(rnd() % (128 - d));
        for (int c = 0; c < 4; c++) { wb(&w, 7, (uint32_t)base[c]); wb(&w, 7, (uint32_t)(base[c] + (int)(rnd() % (unsigned)d))); }
        wb(&w, 1, rnd() & 1); wb(&w, 1, rnd() & 1);
        for (int k = 0; k < 16; k++) wb(&w, k ? 4 : 3, rnd() & (k ? 15 : 7));
        memcpy(b, w.b, 16); return;
    }
    if (fmt == 0x49 || fmt == 0x4b) {   // BC4 / BC5
        for (int h = 0; h < (fmt == 0x4b ? 2 : 1); h++) {
            uint8_t *p = b + 8 * h; int a0 = (int)(rnd() & 255), a1 = kind == 0 ? a0 + (int)(rnd() % 24) - 12 : (int)(rnd() & 255);
            a1 = a1 < 0 ? 0 : a1 > 255 ? 255 : a1; p[0] = (uint8_t)a0; p[1] = (uint8_t)a1;
            for (int i = 2; i < 8; i++) p[i] = (uint8_t)rnd();
        }
        return;
    }
    // BC2 / BC3: colour block at +8
    uint16_t c0 = (uint16_t)rnd(), c1 = kind == 1 ? (uint16_t)rnd() : (uint16_t)(c0 ^ (rnd() & 0x0841));
    uint32_t ix = rnd();
    b[8] = c0 & 255; b[9] = c0 >> 8; b[10] = c1 & 255; b[11] = c1 >> 8; memcpy(b + 12, &ix, 4);
    if (fmt == 0x43) { for (int i = 0; i < 8; i++) b[i] = (uint8_t)rnd(); if (kind == 0) for (int i = 0; i < 8; i++) b[i] = (uint8_t)((b[i] & 0x11) * 15); return; }
    if (kind == 2) {   // alpha only 255 / 0 (indices 0, 1), colours from the four-colour palette
        b[0] = 255; b[1] = 0; uint64_t ai = 0; for (int k = 0; k < 16; k++) ai |= (uint64_t)(rnd() & 1) << (3 * k);
        for (int i = 0; i < 6; i++) b[2 + i] = (uint8_t)(ai >> (8 * i)); return;
    }
    int a0 = (int)(rnd() & 255), a1 = kind == 0 ? a0 + (int)(rnd() % 24) - 12 : (int)(rnd() & 255); a1 = a1 < 0 ? 0 : a1 > 255 ? 255 : a1;
    if (kind == 0 && a0 < a1) { int t = a0; a0 = a1; a1 = t; }   // smooth alpha: the eight-level mode (a0 > a1)
    b[0] = (uint8_t)a0; b[1] = (uint8_t)a1; for (int i = 2; i < 8; i++) b[i] = (uint8_t)rnd();
}
static void ref_decode(int fmt, const uint8_t *b, uint8_t px[64]) {   // RGBA8 texels (k = y * 4 + x)
    memset(px, 0, 64);
    if (fmt == 0x4d) bcdec_bc7(b, px, 16);
    else if (fmt == 0x44) bcdec_bc3(b, px, 16);
    else if (fmt == 0x43) bcdec_bc2(b, px, 16);
    else {
        float v[16]; bcdec_bc4_float(b, v, 4, 0);   // precise BC4
        for (int k = 0; k < 16; k++) px[4 * k] = (uint8_t)lrintf(v[k] * 255.0f);
        if (fmt == 0x4b) { bcdec_bc4_float(b + 8, v, 4, 0); for (int k = 0; k < 16; k++) px[4 * k + 1] = (uint8_t)lrintf(v[k] * 255.0f); }
    }
}

int main(void) {
    @autoreleasepool {
        int negative = getenv("TOTK_PROBE_NEGATIVE") != NULL;
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (![dev supportsFamily:MTLGPUFamilyApple7]) { printf("{\"status\":\"skip\",\"reason\":\"no ASTC/EAC\"}\n"); return 0; }
        NSError *e = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(k_bctc_msl) options:nil error:&e];
        id<MTLComputePipelineState> ps = lib ? [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"bctc"] error:&e] : nil;
        if (!ps) { fprintf(stderr, "bctc: %s\n", e.localizedDescription.UTF8String); return 1; }
        id<MTLLibrary> rl = [dev newLibraryWithSource:@"#include <metal_stdlib>\nusing namespace metal;\n"
            "kernel void rd(texture2d<float, access::read> t [[texture(0)]], device uchar4 *o [[buffer(0)]], uint2 g [[thread_position_in_grid]]) {"
            " o[g.y * t.get_width() + g.x] = uchar4(round(saturate(t.read(g)) * 255.0f)); }" options:nil error:&e];
        id<MTLComputePipelineState> rps = [dev newComputePipelineStateWithFunction:[rl newFunctionWithName:@"rd"] error:&e];
        id<MTLCommandQueue> q = [dev newCommandQueue];
        const int fmts[5] = {0x44, 0x43, 0x4d, 0x49, 0x4b};
        const char *names[5] = {"BC3", "BC2", "BC7", "BC4", "BC5"};
        printf("{\"probe\":\"probe-gpu-bctc\",\"results\":[");
        int first = 1;
        for (int fi = 0; fi < 5; fi++) for (int kind = 0; kind < 3; kind++) {
            int fmt = fmts[fi];
            if (kind == 2 && fmt != 0x44) continue;
            int sb = fmt == 0x49 ? 8 : 16, ob = fmt == 0x49 ? 8 : 16, nch = fmt == 0x49 ? 1 : fmt == 0x4b ? 2 : 4;
            uint8_t *src = calloc(NB, 16);
            for (int i = 0; i < NB; i++) gen(fmt, kind, src + (size_t)i * sb);
            id<MTLBuffer> inb = [dev newBufferWithBytes:src length:(NSUInteger)NB * sb options:MTLResourceStorageModeShared];
            id<MTLBuffer> outb = [dev newBufferWithLength:(NSUInteger)NB * 64 options:MTLResourceStorageModeShared];
            id<MTLBuffer> rawb = [dev newBufferWithLength:(NSUInteger)NB * 64 options:MTLResourceStorageModeShared];
            for (int pass = 0; pass < 2; pass++) {   // 0 transcode, 1 raw decoded texels (colour formats)
                if (pass && nch < 4) break;
                uint32_t prm[6] = {0, BW * (uint32_t)sb, W, H, (uint32_t)fmt | (pass ? 0x100u : 0), 0};
                id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
                [ce setComputePipelineState:ps]; [ce setBuffer:inb offset:0 atIndex:0]; [ce setBytes:prm length:sizeof prm atIndex:1]; [ce setBuffer:pass ? rawb : outb offset:0 atIndex:2];
                [ce dispatchThreadgroups:MTLSizeMake(BW / 8, BH / 8, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)]; [ce endEncoding];
                [cb commit]; [cb waitUntilCompleted];
            }
            if (negative) for (int i = 0; i < NB; i++) ((uint8_t *)outb.contents)[(size_t)i * ob + ob - 1] ^= 0x10;
            MTLPixelFormat pf = nch == 1 ? MTLPixelFormatEAC_R11Unorm : nch == 2 ? MTLPixelFormatEAC_RG11Unorm : MTLPixelFormatASTC_4x4_LDR;
            id<MTLTexture> tex = [dev newTextureWithDescriptor:[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pf width:W height:H mipmapped:NO]];
            [tex replaceRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0 withBytes:outb.contents bytesPerRow:(NSUInteger)BW * ob];
            id<MTLBuffer> dec = [dev newBufferWithLength:W * H * 4 options:MTLResourceStorageModeShared];
            id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
            [ce setComputePipelineState:rps]; [ce setTexture:tex atIndex:0]; [ce setBuffer:dec offset:0 atIndex:0];
            [ce dispatchThreads:MTLSizeMake(W, H, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)]; [ce endEncoding]; [cb commit]; [cb waitUntilCompleted];
            const uint8_t *d = dec.contents, *raw = rawb.contents;
            double se = 0; int maxe = 0, rawmax = 0; long n = 0;
            for (int i = 0; i < NB; i++) {
                uint8_t ref[64]; ref_decode(fmt, src + (size_t)i * sb, ref);
                int bx = i % BW, by = i / BW;
                for (int k = 0; k < 16; k++) {
                    const uint8_t *g = d + ((size_t)(by * 4 + k / 4) * W + bx * 4 + k % 4) * 4;
                    for (int c = 0; c < nch; c++) { int df = abs((int)g[c] - (int)ref[4 * k + c]); se += df * df; n++; if (df > maxe) { maxe = df;
                        if (getenv("BCTC_WORST")) { fprintf(stderr, "%s kind %d block %d texel %d ch %d got %d want %d src", "", kind, i, k, c, g[c], ref[4 * k + c]); for (int j = 0; j < sb; j++) fprintf(stderr, " %02x", src[(size_t)i * sb + j]); fprintf(stderr, "\n"); } } }
                    if (nch == 4) for (int c = 0; c < 4; c++) { int df = abs((int)raw[(size_t)i * 64 + 4 * k + c] - (int)ref[4 * k + c]); if (df > rawmax) rawmax = df; }
                }
            }
            double psnr = se ? 10 * log10(255.0 * 255.0 * n / se) : 99;
            const char *kn = kind == 0 ? "smooth" : kind == 1 ? "random" : "two-level-alpha";
            printf("%s{\"format\":\"%s\",\"blocks\":\"%s\",\"psnr\":%.2f,\"max_error\":%d,\"decoder_max_error\":%d}", first ? "" : ",", names[fi], kn, psnr, maxe, nch == 4 ? rawmax : -1);
            first = 0;
            char what[96];
            if (nch == 4) { snprintf(what, sizeof what, "%s %s: kernel decoder vs bcdec", names[fi], kn); check(rawmax <= (fmt == 0x4d ? 0 : 1), what, rawmax); }
            if (kind == 0) { snprintf(what, sizeof what, "%s smooth PSNR", names[fi]); check(psnr >= (nch == 4 ? 36.0 : 42.0), what, psnr); }
            if (kind == 2) { snprintf(what, sizeof what, "BC3 two-level alpha (dual plane) max error"); check(maxe <= 8, what, maxe); }
            free(src);
        }
        printf("],\"checked\":%d,\"failed\":%d,\"status\":\"%s\"}\n", checks, fails, fails ? "fail" : "pass");
        return fails ? 1 : 0;
    }
}
