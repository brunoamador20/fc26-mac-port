// Execute each exact translated visibility counter on the Mac GPU.
// Covers partial groups, draw offsets, rejected values and uint wraparound.
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdio.h>
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 3) return 2;
    int instance_mode=!strcmp(argv[2],"instance");
    if(!instance_mode&&strcmp(argv[2],"vertex"))return 2;
    id<MTLDevice> d = MTLCreateSystemDefaultDevice(); NSError *err = nil;
    NSString *src = [NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:&err];
    if (getenv("TOTK_PROBE_NEGATIVE")) {
        NSRegularExpression *re=[NSRegularExpression regularExpressionWithPattern:@"uint\\((_[0-9]+)\\), memory_order_relaxed" options:0 error:&err];
        if([re numberOfMatchesInString:src options:0 range:NSMakeRange(0,src.length)]!=1)return 2;
        src=[re stringByReplacingMatchesInString:src options:0 range:NSMakeRange(0,src.length) withTemplate:@"uint($1) * 2u, memory_order_relaxed"];
    }
    src = [src stringByAppendingString:@"\nfragment float4 probe_fragment() { return float4(0); }\n"];
    MTLCompileOptions *opts = [MTLCompileOptions new]; opts.mathMode = MTLMathModeSafe;
    id<MTLLibrary> lib = [d newLibraryWithSource:src options:opts error:&err];
    if (!lib) { fprintf(stderr,"compile: %s\n",err.description.UTF8String); return 1; }
    id<MTLFunction> fn = [lib newFunctionWithName:@"main0"];
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = fn; pd.fragmentFunction = [lib newFunctionWithName:@"probe_fragment"]; pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    id<MTLRenderPipelineState> pso = [d newRenderPipelineStateWithDescriptor:pd error:&err];
    if (!pso) { fprintf(stderr,"pipeline: %s\n",err.description.UTF8String); return 1; }
    id<MTLBuffer> input = [d newBufferWithLength:65536 options:MTLResourceStorageModeShared];
    id<MTLBuffer> output = [d newBufferWithLength:4 options:MTLResourceStorageModeShared];
    id<MTLArgumentEncoder> ae = [fn newArgumentEncoderWithBufferIndex:0];
    id<MTLBuffer> args = [d newBufferWithLength:ae.encodedLength options:MTLResourceStorageModeShared];
    [ae setArgumentBuffer:args offset:0]; [ae setBuffer:input offset:0 atIndex:0]; [ae setBuffer:output offset:0 atIndex:1];
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget; id<MTLTexture> target = [d newTextureWithDescriptor:td];
    id<MTLCommandQueue> queue = [d newCommandQueue]; unsigned cases = 0;
    const unsigned sizes[] = {1, 31, 32, 33, 127, 1025};
    for (unsigned n = 0; n < 6; n++) for (unsigned pattern = 0; pattern < 4; pattern++)
    for (unsigned start = 0; start < 2; start++) for (unsigned wrap = 0; wrap < 2; wrap++) {
        uint32_t *in = input.contents, *out = output.contents;
        memset(in, 0, input.length); unsigned base = start ? 17 : 0;
        uint32_t want = wrap ? UINT32_MAX - 7 : 13; *out = want;
        for (unsigned i = 0; i < sizes[n]; i++) {
            uint32_t value = pattern == 0 ? 0 : pattern == 1 ? 1 : pattern == 2 ? i % 3 : (i * 1664525u + 1013904223u) % 5;
            in[(instance_mode?114:8304) + (instance_mode?i:base+i) * 4] = value; want += value == 1;
        }
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = target; rp.colorAttachments[0].loadAction = MTLLoadActionDontCare;
        rp.colorAttachments[0].storeAction = MTLStoreActionDontCare;
        id<MTLCommandBuffer> cb = [queue commandBuffer]; id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
        [enc setRenderPipelineState:pso]; [enc setVertexBuffer:args offset:0 atIndex:0];
        [enc useResource:input usage:MTLResourceUsageRead stages:MTLRenderStageVertex]; [enc useResource:output usage:MTLResourceUsageRead | MTLResourceUsageWrite stages:MTLRenderStageVertex];
        if(instance_mode)[enc drawPrimitives:MTLPrimitiveTypePoint vertexStart:0 vertexCount:1 instanceCount:sizes[n] baseInstance:base];
        else [enc drawPrimitives:MTLPrimitiveTypePoint vertexStart:base vertexCount:sizes[n]];
        [enc endEncoding]; [cb commit]; [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted || *out != want) {
            fprintf(stderr,"FAIL n=%u pattern=%u base=%u wrap=%u got=%u want=%u GPU=%s\n",sizes[n],pattern,base,wrap,*out,want,cb.error.description.UTF8String); return 1;
        }
        cases++;
    }
    printf("{\"status\":\"pass\",\"cases\":%u,\"scope\":\"translated vertex counter; partial groups, nonzero vertex starts, rejected values, atomic overflow\"}\n",cases);
    return 0;
} }
