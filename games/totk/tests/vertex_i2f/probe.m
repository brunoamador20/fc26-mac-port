#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>

int main(void) { @autoreleasepool {
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
        "struct VertexInput { float4 p [[attribute(0)]]; };\n"
        "vertex float4 v(VertexInput input [[stage_in]]) { return float4(input.p.xy / 10.0, 0, 1); }\n"
        "fragment float4 f() { return float4(1, 0, 0, 1); }\n";
    NSError *error = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:source options:nil error:&error];
    if (!lib) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
    MTLRenderPipelineDescriptor *desc = [MTLRenderPipelineDescriptor new];
    desc.vertexFunction = [lib newFunctionWithName:@"v"];
    desc.fragmentFunction = [lib newFunctionWithName:@"f"];
    desc.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    MTLVertexDescriptor *vd = [MTLVertexDescriptor vertexDescriptor];
    vd.attributes[0].format = MTLVertexFormatChar4;
    vd.attributes[0].bufferIndex = 0;
    vd.layouts[0].stride = 4;
    desc.vertexDescriptor = vd;
    id<MTLRenderPipelineState> pipeline = [dev newRenderPipelineStateWithDescriptor:desc error:&error];
    if (!pipeline) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:16 height:16 mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    id<MTLTexture> target = [dev newTextureWithDescriptor:td];
    signed char vertices[12] = {-8,-8,0,0, 8,-8,0,0, 0,8,0,0};
    id<MTLBuffer> data = [dev newBufferWithBytes:vertices length:sizeof(vertices) options:MTLResourceStorageModeShared];
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = target;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0,0,0,1);
    id<MTLCommandBuffer> command = [[dev newCommandQueue] commandBuffer];
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:pipeline];
    [encoder setVertexBuffer:data offset:0 atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [encoder endEncoding];
    [command commit]; [command waitUntilCompleted];
    unsigned char pixel[4] = {0};
    [target getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(8,8,1,1) mipmapLevel:0];
    printf("Char4 -> float4 center pixel: %u,%u,%u,%u\n",pixel[0],pixel[1],pixel[2],pixel[3]);
    return pixel[0] > 200 && pixel[1] < 20 && pixel[2] < 20 ? 0 : 1;
} }
