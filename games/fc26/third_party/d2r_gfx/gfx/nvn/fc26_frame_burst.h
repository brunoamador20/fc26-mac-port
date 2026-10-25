#pragma once
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <pthread.h>

/* Diagnostic only: retain raw presented images; write after the entire sequence.
   No PNG encoder, file I/O or image hashing between adjacent frames. */
static pthread_mutex_t fc26_burst_mu = PTHREAD_MUTEX_INITIALIZER;
static unsigned fc26_burst_want, fc26_burst_taken;
static NSString *fc26_burst_path;
static NSMutableArray *fc26_burst_buffers, *fc26_burst_rows;
static int fc26_burst_request(unsigned n, const char *path) {
    if (!n || n > 32 || !path || !*path) return 0;
    pthread_mutex_lock(&fc26_burst_mu);
    int ok = !fc26_burst_want;
    if (ok) {
        fc26_burst_want = n; fc26_burst_taken = 0; fc26_burst_path = @(path);
        fc26_burst_buffers = [NSMutableArray new]; fc26_burst_rows = [NSMutableArray new];
    }
    pthread_mutex_unlock(&fc26_burst_mu);
    return ok;
}
static int fc26_burst_active(void) {
    pthread_mutex_lock(&fc26_burst_mu);
    int active = fc26_burst_taken < fc26_burst_want;
    pthread_mutex_unlock(&fc26_burst_mu); return active;
}
static void fc26_burst_capture(id<MTLTexture> src, id<MTLCommandBuffer> cb, uint64_t frame, uint64_t ns) {
    pthread_mutex_lock(&fc26_burst_mu);
    if (fc26_burst_taken >= fc26_burst_want) { pthread_mutex_unlock(&fc26_burst_mu); return; }
    BOOL valid = src && cb && (src.pixelFormat == MTLPixelFormatBGRA8Unorm || src.pixelFormat == MTLPixelFormatBGRA8Unorm_sRGB ||
                               src.pixelFormat == MTLPixelFormatRGBA8Unorm || src.pixelFormat == MTLPixelFormatRGBA8Unorm_sRGB);
    NSUInteger row = (src.width * 4 + 255) & ~(NSUInteger)255;
    id<MTLBuffer> buf = valid ? [src.device newBufferWithLength:row * src.height options:MTLResourceStorageModeShared] : nil;
    if (!buf) { fprintf(stderr, "[fc26-burst] FAILED: unsupported texture or allocation\n"); fc26_burst_want = 0; pthread_mutex_unlock(&fc26_burst_mu); return; }
    id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
    [blit copyFromTexture:src sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
        sourceSize:MTLSizeMake(src.width,src.height,1) toBuffer:buf destinationOffset:0
        destinationBytesPerRow:row destinationBytesPerImage:row*src.height];
    [blit endEncoding];
    [fc26_burst_buffers addObject:buf];
    [fc26_burst_rows addObject:@{@"frame":@(frame), @"ns":@(ns), @"width":@(src.width), @"height":@(src.height), @"row":@(row), @"format":@(src.pixelFormat)}];
    unsigned i = fc26_burst_taken++;
    NSString *path = fc26_burst_path;
    BOOL last = fc26_burst_taken == fc26_burst_want;
    NSArray *buffers = last ? [fc26_burst_buffers copy] : nil, *rows = last ? [fc26_burst_rows copy] : nil;
    [cb addCompletedHandler:^(id<MTLCommandBuffer> done) {
        if (done.status == MTLCommandBufferStatusError) fprintf(stderr, "[fc26-burst] FAILED: GPU frame %u\n", i);
        if (!last) return;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            BOOL ok = done.status == MTLCommandBufferStatusCompleted;
            for (NSUInteger k = 0; k < buffers.count; k++) {
                id<MTLBuffer> b = buffers[k];
                NSData *data = [NSData dataWithBytesNoCopy:b.contents length:b.length freeWhenDone:NO];
                ok &= [data writeToFile:[NSString stringWithFormat:@"%@_%02lu.raw", path, (unsigned long)k] atomically:NO];
            }
            NSData *json = [NSJSONSerialization dataWithJSONObject:rows options:NSJSONWritingPrettyPrinted error:nil];
            ok &= [json writeToFile:[path stringByAppendingString:@".json"] atomically:YES];
            fprintf(stderr, "[fc26-burst] %s: %lu consecutive frames -> %s\n", ok ? "saved" : "FAILED", (unsigned long)buffers.count, path.UTF8String);
            pthread_mutex_lock(&fc26_burst_mu);
            fc26_burst_want = fc26_burst_taken = 0; fc26_burst_buffers = nil; fc26_burst_rows = nil;
            pthread_mutex_unlock(&fc26_burst_mu);
        });
    }];
    pthread_mutex_unlock(&fc26_burst_mu);
}
