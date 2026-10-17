// GPU probe: a threadgroup barrier placed after an early return (the shape the Switch shader translator emits for
// "@!P0 EXIT; BAR.SYNC", which is correct on NVIDIA because exited threads count as arrived). Each of 64 threads writes
// tid+1 to threadgroup memory; threads other than 0 return; thread 0 passes the barrier and sums all 64 slots (2080).
// The "moved" variant puts the barrier before the return (a candidate rewrite of translated kernels; not applied).
// build: xcrun clang -fobjc-arc -O2 tests/divergent_barrier/probe.m -framework Metal -framework Foundation -o build/divergent-barrier-probe
// usage: build/divergent-barrier-probe [threadgroups 200000] [rounds 20]; exit 1 when the moved variant ever sums wrong.
// Result on M4 (2026-10-15): 0 wrong sums in 6 million threadgroups for both variants, so Metal handles this shape here.
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
static const char *k_src =
"#include <metal_stdlib>\nusing namespace metal;\n"
"static uint slow(device const uint *chain, uint tid, uint gid) {\n"   // dependent loads: threads 32..63 arrive late
"  uint v = (gid * 131u + tid) & 4095u; if (tid >= 32u) for (uint k = 0u; k < 64u; k++) v = chain[v]; return v; }\n"
"kernel void original(device uint *out [[buffer(0)]], device const uint *chain [[buffer(1)]], uint tid [[thread_index_in_threadgroup]], uint gid [[threadgroup_position_in_grid]]) {\n"
"  threadgroup uint tg[64]; uint v = slow(chain, tid, gid); tg[tid] = tid + 1u + (gid & 7u) * 64u + (v & 0u);\n"
"  if (tid != 0u) { return; }\n"
"  threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"  uint s = 0u; for (uint i = 0u; i < 64u; i++) s += tg[i]; out[gid] = s; }\n"
"kernel void moved(device uint *out [[buffer(0)]], device const uint *chain [[buffer(1)]], uint tid [[thread_index_in_threadgroup]], uint gid [[threadgroup_position_in_grid]]) {\n"
"  threadgroup uint tg[64]; uint v = slow(chain, tid, gid); tg[tid] = tid + 1u + (gid & 7u) * 64u + (v & 0u);\n"
"  threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"  if (tid != 0u) { return; }\n"
"  uint s = 0u; for (uint i = 0u; i < 64u; i++) s += tg[i]; out[gid] = s; }\n";
int main(int argc, char **argv) {
    @autoreleasepool {
        NSUInteger groups = argc > 1 ? (NSUInteger)atol(argv[1]) : 200000, rounds = argc > 2 ? (NSUInteger)atol(argv[2]) : 20;
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice(); NSError *e = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(k_src) options:nil error:&e]; if (!lib) { fprintf(stderr, "compile: %s\n", e.localizedDescription.UTF8String); return 2; }
        id<MTLCommandQueue> q = [dev newCommandQueue];
        id<MTLBuffer> out = [dev newBufferWithLength:groups * 4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> chain = [dev newBufferWithLength:4096 * 4 options:MTLResourceStorageModeShared];
        { uint32_t *c = chain.contents; for (uint32_t i = 0; i < 4096; i++) c[i] = (i * 2654435761u >> 7) & 4095u; }
        unsigned long long bad[2] = {0, 0};
        const char *names[2] = {"original", "moved"};
        for (int v = 0; v < 2; v++) {
            id<MTLComputePipelineState> ps = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@(names[v])] error:&e];
            if (!ps) { fprintf(stderr, "pipeline: %s\n", e.localizedDescription.UTF8String); return 2; }
            for (NSUInteger r = 0; r < rounds; r++) {
                memset(out.contents, 0xff, groups * 4);
                id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
                [ce setComputePipelineState:ps]; [ce setBuffer:out offset:0 atIndex:0]; [ce setBuffer:chain offset:0 atIndex:1];
                [ce dispatchThreadgroups:MTLSizeMake(groups, 1, 1) threadsPerThreadgroup:MTLSizeMake(64, 1, 1)]; [ce endEncoding];
                [cb commit]; [cb waitUntilCompleted];
                const uint32_t *o = out.contents;
                for (NSUInteger g = 0; g < groups; g++) { uint32_t want = 2080u + (uint32_t)(g & 7) * 64u * 64u; if (o[g] != want) bad[v]++; }
            }
            printf("%s: %llu wrong sums out of %llu threadgroups\n", names[v], bad[v], (unsigned long long)(groups * rounds));
        }
        printf("{\"status\":\"%s\",\"probe\":\"divergent-barrier\",\"original_wrong\":%llu,\"moved_wrong\":%llu,\"threadgroups\":%llu}\n", bad[1] ? "fail" : "pass", bad[0], bad[1], (unsigned long long)(groups * rounds));
        return bad[1] ? 1 : 0;
    }
}
