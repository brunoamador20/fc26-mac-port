// probe-bc1astc: BC1 -> ASTC 4x4 transcoding (third_party/d2r_gfx/gfx/tex/nvn_bc1astc.c) checked through Metal's own
// ASTC decoder against a reference BC1 decode (bcdec). Random blocks of every kind (four-colour, three-colour opaque,
// three-colour with transparent texels, extreme endpoints); per kind the largest channel error and the alpha mismatches.
// Also compares the GPU transcoder (nvn_bc1astc_msl.h, used by nvn_mtl.m) byte for byte with the C one.
// TOTK_PROBE_NEGATIVE=1 flips one weight bit in every block: the four-colour check must then fail.
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BCDEC_IMPLEMENTATION
#include "../../third_party/d2r_gfx/third_party/bcdec/bcdec.h"
#include "../../third_party/d2r_gfx/gfx/tex/nvn_bc1astc.h"
#include "../../third_party/d2r_gfx/gfx/tex/nvn_bc1astc_msl.h"
#include <math.h>

enum { W = 512, H = 512, BW = W / 4, BH = H / 4, NB = BW * BH };
static uint32_t rng = 12345;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

int main(int argc, char **argv) {
    @autoreleasepool {
        (void)argc; (void)argv;
        int negative = getenv("TOTK_PROBE_NEGATIVE") != NULL;
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (![dev supportsFamily:MTLGPUFamilyApple7]) { printf("{\"status\":\"skip\",\"reason\":\"no ASTC\"}\n"); return 0; }
        uint8_t *bc = malloc(NB * 8), *astc = malloc(NB * 16); int *kind = malloc(NB * sizeof(int));
        for (int i = 0; i < NB; i++) {
            uint8_t *b = bc + i * 8; int k = i % 5; uint16_t c0 = (uint16_t)rnd(), c1 = (uint16_t)rnd(); uint32_t ix = rnd();
            if (k == 4) { c0 = (rnd() & 1) ? 0xffff : 0; c1 = (rnd() & 1) ? 0xffff : 0x0001; }   // extreme endpoints
            if (k == 0 || k == 4) { if (c0 == c1) c0 ^= 0x0841; if (c0 < c1) { uint16_t t = c0; c0 = c1; c1 = t; } }   // four colours
            else { if (c0 > c1) { uint16_t t = c0; c0 = c1; c1 = t; }
                   if (k == 1) { uint32_t m = 0; for (int p = 0; p < 16; p++) { uint32_t v = (ix >> (2 * p)) & 3; if (v == 3) v = rnd() % 3; m |= v << (2 * p); } ix = m; }   // no index 3
                   if (k == 3) { c0 = (uint16_t)(rnd() & 0x7bef); c1 = (uint16_t)(c0 + (rnd() & 0x0841)); if (c0 > c1) { uint16_t t = c0; c0 = c1; c1 = t; } } }   // near-equal colours
            b[0] = c0 & 255; b[1] = c0 >> 8; b[2] = c1 & 255; b[3] = c1 >> 8; memcpy(b + 4, &ix, 4);
            int has3 = 0; for (int p = 0; p < 16; p++) if (((ix >> (2 * p)) & 3) == 3) has3 = 1;
            kind[i] = c0 > c1 ? 0 : has3 ? 2 : 1;
            nvn_bc1_to_astc(b, astc + i * 16, 1);
            if (negative) astc[i * 16 + 15] ^= 0x40;
        }
        // GPU transcoder: same blocks, compared byte for byte.
        NSError *e = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(k_bc1astc_msl) options:nil error:&e];
        id<MTLComputePipelineState> ps = lib ? [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"bc1astc"] error:&e] : nil;
        if (!ps) { fprintf(stderr, "GPU transcoder: %s\n", e.localizedDescription.UTF8String); return 1; }
        id<MTLBuffer> inb = [dev newBufferWithBytes:bc length:NB * 8 options:MTLResourceStorageModeShared];
        id<MTLBuffer> outb = [dev newBufferWithLength:NB * 16 options:MTLResourceStorageModeShared];
        uint32_t prm[8] = {0, BW * 8, W, H, 1, 0, 0, 0};   // src offset, src pitch, width, height, rgba formats, dst offset
        id<MTLCommandQueue> q = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
        [ce setComputePipelineState:ps]; [ce setBuffer:inb offset:0 atIndex:0]; [ce setBytes:prm length:sizeof prm atIndex:1]; [ce setBuffer:outb offset:0 atIndex:2];
        [ce dispatchThreadgroups:MTLSizeMake(BW / 8, BH / 8, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)]; [ce endEncoding];
        [cb commit]; [cb waitUntilCompleted];
        int gpu_diff = 0; for (int i = 0; i < NB; i++) if (memcmp((uint8_t *)outb.contents + i * 16, astc + i * 16, 16)) gpu_diff++;
        if (negative) gpu_diff = 0;   // the CPU blocks were corrupted on purpose
        // Metal decodes the ASTC texture; a kernel writes RGBA8 texels.
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatASTC_4x4_LDR width:W height:H mipmapped:NO];
        id<MTLTexture> tex = [dev newTextureWithDescriptor:td];
        [tex replaceRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0 withBytes:astc bytesPerRow:BW * 16];
        id<MTLLibrary> rl = [dev newLibraryWithSource:@"#include <metal_stdlib>\nusing namespace metal;\n"
            "kernel void rd(texture2d<float> t [[texture(0)]], device uchar4 *o [[buffer(0)]], uint2 g [[thread_position_in_grid]]) {"
            " constexpr sampler s(filter::nearest, coord::pixel); o[g.y * t.get_width() + g.x] = uchar4(round(t.sample(s, float2(g) + 0.5) * 255.0)); }" options:nil error:&e];
        id<MTLComputePipelineState> rp = [dev newComputePipelineStateWithFunction:[rl newFunctionWithName:@"rd"] error:&e];
        id<MTLBuffer> px = [dev newBufferWithLength:W * H * 4 options:MTLResourceStorageModeShared];
        cb = [q commandBuffer]; ce = [cb computeCommandEncoder];
        [ce setComputePipelineState:rp]; [ce setTexture:tex atIndex:0]; [ce setBuffer:px offset:0 atIndex:0];
        [ce dispatchThreadgroups:MTLSizeMake(W / 8, H / 8, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)]; [ce endEncoding];
        [cb commit]; [cb waitUntilCompleted];
        const uint8_t *got = px.contents;
        int maxerr[3] = {0}, alpha_bad[3] = {0}; long count[3] = {0}; double sumsq[3] = {0};
        for (int i = 0; i < NB; i++) {
            uint8_t ref[16 * 4]; bcdec_bc1(bc + i * 8, ref, 16);
            int bx = i % BW, by = i / BW, k = kind[i]; count[k]++;
            for (int p = 0; p < 16; p++) {
                const uint8_t *r = ref + p * 4, *g = got + ((by * 4 + p / 4) * W + bx * 4 + p % 4) * 4;
                if (r[3] != g[3]) { alpha_bad[k]++; continue; }
                if (r[3] == 0) continue;   // transparent texel: colour not shown
                for (int c = 0; c < 3; c++) { int d = abs(r[c] - g[c]); if (d > maxerr[k]) maxerr[k] = d; sumsq[k] += d * d; }
            }
        }
        const char *names[3] = {"four_colour", "three_colour_opaque", "three_colour_transparent"};
        int pass = gpu_diff == 0 && maxerr[0] <= 2 && alpha_bad[0] == 0 && alpha_bad[1] == 0 && alpha_bad[2] == 0;
        printf("{\"status\":\"%s\",\"blocks\":%d,\"gpu_vs_cpu_differing_blocks\":%d", pass ? "pass" : "fail", NB, gpu_diff);
        for (int k = 0; k < 3; k++) printf(",\"%s\":{\"blocks\":%ld,\"max_channel_error\":%d,\"rms\":%.3f,\"alpha_mismatch_texels\":%d}", names[k], count[k], maxerr[k], sqrt(sumsq[k] / (count[k] * 48.0 + 1)), alpha_bad[k]);
        printf("%s}\n", negative ? ",\"negative_control\":true" : "");
        return pass ? 0 : 1;
    }
}
