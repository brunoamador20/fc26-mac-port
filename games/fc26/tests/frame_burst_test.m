#include "../third_party/d2r_gfx/gfx/nvn/fc26_frame_burst.h"
#include <assert.h>
#include <unistd.h>
int main(int argc, char **argv) {
    (void)argc;
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice(); assert(dev);
        id<MTLCommandQueue> queue = [dev newCommandQueue];
        MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:8 mipmapped:NO];
        desc.storageMode = MTLStorageModeShared;
        id<MTLTexture> tex = [dev newTextureWithDescriptor:desc];
        assert(!fc26_burst_active());
        assert(!fc26_burst_request(33, argv[1]));
        assert(fc26_burst_request(4, argv[1]));
        assert(!fc26_burst_request(4, argv[1]));
        for (unsigned i=0; i<4; i++) {
            uint8_t pixels[256]; memset(pixels, i, sizeof pixels);
            [tex replaceRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0 withBytes:pixels bytesPerRow:32];
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            fc26_burst_capture(tex, cb, 100+i, 1000000+i*16666667);
            [cb commit]; [cb waitUntilCompleted];
            if (i<3) assert(![[NSFileManager defaultManager] fileExistsAtPath:[@(argv[1]) stringByAppendingString:@".json"]]);
        }
        for (int k=0; k<500; k++) {
            pthread_mutex_lock(&fc26_burst_mu); int done = !fc26_burst_want; pthread_mutex_unlock(&fc26_burst_mu);
            if (done) return 0; usleep(10000);
        }
        return 2;
    }
}
