// Compile the production profiler against tiny, synthetic Metal passes.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdatomic.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static id<MTLDevice> g_dev;
#define MLOG(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
#define MDIE(...) do { MLOG(__VA_ARGS__); abort(); } while (0)
@interface TotkCommitOptions : MTL4CommitOptions @end
@implementation TotkCommitOptions @end
#include "nvn_gpuprof.h"
int main(void) { @autoreleasepool {
    g_dev = MTLCreateSystemDefaultDevice(); if (!g_dev) return 77;
    NSError *error = nil;
    id<MTL4CommandQueue> queue = [g_dev newMTL4CommandQueueWithDescriptor:[MTL4CommandQueueDescriptor new] error:&error];
    id<MTL4CommandAllocator> alloc = [g_dev newCommandAllocator];
    MTLResidencySetDescriptor *rd = [MTLResidencySetDescriptor new];
    id<MTLResidencySet> resident = [g_dev newResidencySetWithDescriptor:rd error:&error];
    [queue addResidencySet:resident];
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:64 height:64 mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget; td.storageMode = MTLStorageModePrivate;
    id<MTLTexture> tex = [g_dev newTextureWithDescriptor:td];
    [resident addAllocation:tex];
    td.pixelFormat = MTLPixelFormatDepth32Float;
    id<MTLTexture> depth = [g_dev newTextureWithDescriptor:td];
    [resident addAllocation:depth]; [resident commit];
    NSString *msl = @"#include <metal_stdlib>\nusing namespace metal; vertex float4 vs(uint i [[vertex_id]]) { return float4(i==2?3.0:-1.0,i==1?3.0:-1.0,0,1); } fragment float4 fs(){return float4(1,0,0,1);}";
    id<MTLLibrary> lib = [g_dev newLibraryWithSource:msl options:nil error:&error];
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [lib newFunctionWithName:@"vs"]; pd.fragmentFunction = [lib newFunctionWithName:@"fs"];
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    id<MTLRenderPipelineState> ps = [g_dev newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!ps) { MLOG("pipeline: %s", error.description.UTF8String); return 2; }
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatInvalid;
    pd.fragmentFunction = nil; pd.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;
    id<MTLRenderPipelineState> depth_ps = [g_dev newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!depth_ps) return 4;
    gp_config();
    id<MTL4CommandBuffer> cb = [g_dev newCommandBuffer]; [cb beginCommandBufferWithAllocator:alloc];
    for (int i = 0; i < 4; i++) {
        MTL4RenderPassDescriptor *d = [MTL4RenderPassDescriptor new];
        d.colorAttachments[0].texture = tex;
        d.colorAttachments[0].loadAction = MTLLoadActionClear;
        d.colorAttachments[0].storeAction = MTLStoreActionStore;
        if (i == 3) {
            d.colorAttachments[0].texture = nil;
            d.depthAttachment.texture = depth; d.depthAttachment.loadAction = MTLLoadActionClear;
            d.depthAttachment.storeAction = MTLStoreActionStore;
        }
        id<MTL4RenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:d];
        [e barrierAfterQueueStages:MTLStageAll beforeStages:MTLStageAll visibilityOptions:MTL4VisibilityOptionDevice];
        gp_begin(e, 'R', d);
        if (i) { [e setRenderPipelineState:i == 3 ? depth_ps : ps]; [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; g_stat_draw++; }
        int empty = gp_end(e); [e barrierAfterStages:MTLStageAll beforeQueueStages:MTLStageAll visibilityOptions:MTL4VisibilityOptionDevice]; [e endEncoding]; gp_clear_end(cb, empty);
    }
    TotkCommitOptions *o = [TotkCommitOptions new];
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    gp_finish(o);
    [o addFeedbackHandler:^(id<MTL4CommitFeedback> f) { if (f.error) MLOG("GPU: %s", f.error.description.UTF8String); dispatch_semaphore_signal(done); }];
    [cb endCommandBuffer]; id<MTL4CommandBuffer> buffers[] = {cb}; [queue commit:buffers count:1 options:o];
    if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 15*NSEC_PER_SEC))) return 3;
    return 0;
} }
