// Construction-only diagnostic for repeated production interpolation rebuilds.
// No game data or encoded interpolation: this isolates one part of a memory
// investigation, and cannot establish the lifetime of encoded/in-flight work.
// Build with runtime/game_slot.c; run in the same canonical game slot.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <libproc.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <unistd.h>
#include "runtime.h"
#include "totk_mfx.m"

_Noreturn void runtime_fail(const char *message) {
    fprintf(stderr, "resize probe: %s\n", message);
    exit(2);
}

static void sample(id<MTLDevice> device, int iteration, int previous_alive) {
    struct rusage_info_v4 usage = {0};
    if (proc_pid_rusage(getpid(), RUSAGE_INFO_V4, (rusage_info_t *)&usage))
        runtime_fail("proc_pid_rusage");
    printf("{\"iteration\":%d,\"canvas_width\":%lu,\"canvas_height\":%lu,"
           "\"metal_allocated_bytes\":%llu,\"phys_footprint\":%llu,"
           "\"residency_allocations\":%lu,\"previous_interpolator_alive\":%s}\n", iteration,
           (unsigned long)g.out_w, (unsigned long)g.out_h,
           (unsigned long long)device.currentAllocatedSize,
           (unsigned long long)usage.ri_phys_footprint, (unsigned long)g.rs.allocationCount,
           previous_alive ? "true" : "false");
    fflush(stdout);
}

// Optional real encodes: black scene, transparent UI, fixed depth and identity
// camera motion. Keep the returned frame payload through completion, after the
// production helper has cleared its interpolator's public texture bindings.
static void encode_fixture(id<MTLDevice> device) {
    static id<MTLCommandQueue> copy_queue;
    static id<MTL4CommandQueue> queue;
    static id<MTL4CommandAllocator> allocator;
    static id<MTL4CommandBuffer> command;
    static id<MTLTexture> depth;
    static id<MTLResidencySet> depth_set;
    NSError *error = nil;
    if (!queue) {
        copy_queue = [device newCommandQueue]; queue = [device newMTL4CommandQueue];
        allocator = [device newCommandAllocator]; command = [device newCommandBuffer];
        depth_set = [device newResidencySetWithDescriptor:[MTLResidencySetDescriptor new] error:&error];
        if (!queue || !copy_queue || !allocator || !command || !depth_set) runtime_fail("fixture queues");
        [queue addResidencySet:g.rs]; [queue addResidencySet:depth_set];
    }
    if (!depth || depth.width != g.in_w || depth.height != g.in_h) {
        if (depth) [depth_set removeAllocation:depth];
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:g.in_w height:g.in_h mipmapped:NO];
        td.storageMode = MTLStorageModePrivate; td.usage = MTLTextureUsageShaderRead;
        depth = [device newTextureWithDescriptor:td];
        if (!depth) runtime_fail("fixture depth");
        [depth_set addAllocation:depth]; [depth_set commit];
    }
    id<MTLBuffer> zero = [device newBufferWithLength:g.out_w*g.out_h*8 options:MTLResourceStorageModeShared];
    id<MTLBuffer> db = [device newBufferWithLength:g.in_w*g.in_h*4 options:MTLResourceStorageModeShared];
    if (!zero || !db) runtime_fail("fixture initialization buffers");
    memset(zero.contents, 0, zero.length);
    for (NSUInteger i=0; i<g.in_w*g.in_h; i++) ((float *)db.contents)[i] = 0.5f;
    id<MTLCommandBuffer> init = [copy_queue commandBuffer];
    id<MTLBlitCommandEncoder> blit = [init blitCommandEncoder];
    for (id<MTLTexture> target in @[g.scene[0],g.scene[1],g.ui]) {
        NSUInteger pitch = target.width*(target.pixelFormat == MTLPixelFormatRGBA16Float ? 8 : 4);
        [blit copyFromBuffer:zero sourceOffset:0 sourceBytesPerRow:pitch sourceBytesPerImage:pitch*target.height sourceSize:MTLSizeMake(target.width,target.height,1) toTexture:target destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
    }
    [blit copyFromBuffer:db sourceOffset:0 sourceBytesPerRow:g.in_w*4 sourceBytesPerImage:g.in_w*g.in_h*4 sourceSize:MTLSizeMake(g.in_w,g.in_h,1) toTexture:depth destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
    [blit endEncoding];
    for (int s=0; s<2; s++) {
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=g.out[s]; pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore; pass.colorAttachments[0].clearColor=MTLClearColorMake(1,0,1,1);
        [[init renderCommandEncoderWithDescriptor:pass] endEncoding];
    }
    [init commit]; [init waitUntilCompleted]; if (init.error) runtime_fail("fixture initialization");
    g.dt=1.0/30; g.cur=0; g.hist_ok=0; g.cam[56]=0.1; g.cam[57]=25000; g.cam[62]=(double)g.out_w/g.out_h; g.cam[70]=50*M_PI/180;
    for (int s=0; s<2; s++) {
        float *par=g.mv_par[s].contents; memset(par,0,256);
        par[0]=par[5]=par[10]=par[15]=1; par[16]=g.in_w; par[17]=g.in_h;
        par[18]=1.0f/g.in_w; par[19]=1.0f/g.in_h; par[20]=1;
        g.enc_depth=depth; [allocator reset]; [command beginCommandBufferWithAllocator:allocator];
        NSArray *resources=mfx_frame_encode(command,s,nil,0);
        if (resources.count!=8 || g.fi.colorTexture || g.fi.depthTexture || g.fi.outputTexture) runtime_fail("frame binding ownership");
        [command endCommandBuffer]; dispatch_semaphore_t done=dispatch_semaphore_create(0); __block NSError *gpu_error=nil;
        MTL4CommitOptions *options=[MTL4CommitOptions new];
        [options addFeedbackHandler:^(id<MTL4CommitFeedback> feedback) { gpu_error=feedback.error; if(resources.count!=8) abort(); dispatch_semaphore_signal(done); }];
        const id<MTL4CommandBuffer> list[]={command}; [queue commit:list count:1 options:options];
        if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC)) || gpu_error) runtime_fail("fixture interpolation completion");
    }
    id<MTLBuffer> pixel=[device newBufferWithLength:256 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> read=[copy_queue commandBuffer]; blit=[read blitCommandEncoder];
    [blit copyFromTexture:g.out[1] sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(g.out_w/2,g.out_h/2,0) sourceSize:MTLSizeMake(1,1,1) toBuffer:pixel destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:256];
    [blit endEncoding]; [read commit]; [read waitUntilCompleted]; if(read.error) runtime_fail("fixture readback");
    const uint8_t *rgb=pixel.contents; if(rgb[0]>4 || rgb[1]>4 || rgb[2]>4) runtime_fail("fixture black output remained unwritten/incorrect");
}

int main(void) {
    runtime_game_slot_acquire("probe-gpu-mfx-resize-construction");
    @autoreleasepool {
        int unpooled = getenv("MFX_RESIZE_UNPOOLED") != NULL;
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device || ![MTLFXFrameInterpolatorDescriptor supportsMetal4FX:device])
            runtime_fail("Metal 4 frame interpolation unavailable");
        __weak id previous = nil;
        sample(device, -1, 0);
        for (int iteration = 0; iteration < 12; iteration++) {
            @autoreleasepool {
                previous = g.fi;
                NSUInteger w = iteration % 2 ? 2560 : 1920;
                NSUInteger h = iteration % 2 ? 1440 : 1080;
                ensure_out(device, w, h, MTLPixelFormatRG11B10Float);
            }
            // Production scene-target allocation runs inside the submission
            // pool. Interpolator construction currently follows that pool.
            NSUInteger iw = iteration % 2 ? 2128 : 1600, ih = iteration % 2 ? 1200 : 896;
            if (unpooled) ensure_fi(iw, ih);
            else @autoreleasepool { ensure_fi(iw, ih); }
            if (getenv("MFX_RESIZE_ENCODE")) @autoreleasepool { encode_fixture(device); }
            sample(device, iteration, previous != nil);
        }
        @autoreleasepool {
            g.fi = nil;
            for (unsigned i = 0; i < g_fi_cache_count; i++) g_fi_cache[i] = nil;
            g_fi_cache_count = 0;
            for (int i = 0; i < 2; i++) drop(&g.scene[i]);
            drop(&g.ui); drop(&g.mv);
            for (int i = 0; i < MFX_OUT; i++) {
                g.outv[i] = nil; drop(&g.out[i]);
                [g.rs removeAllocation:g.mv_par[i]];
                g.mv_par[i] = nil; g.mv_args[i] = nil;
            }
            [g.rs commit]; g.rs = nil; g.mv_ps = nil; g.fence = nil;
        }
        sample(device, 12, previous != nil);
    }
    @autoreleasepool { sample(g.dev, 13, 0); }
    @autoreleasepool {
        id<MTLCommandQueue> queue = [g.dev newCommandQueue];
        id<MTLCommandBuffer> barrier = [queue commandBuffer];
        [barrier commit]; [barrier waitUntilCompleted];
        if (barrier.error) runtime_fail("empty completion barrier");
        usleep(250000);
        sample(g.dev, 14, 0);
    }
    printf("{\"status\":\"complete\",\"encoded_fixture\":%s,\"scope\":\"12 configuration changes; optional two real encodes each with reset then history and black readback; no game; observations, not leak verdict\"}\n",getenv("MFX_RESIZE_ENCODE") ? "true":"false");
    return 0;
}
