// Execute the production Metal 4 spatial-scaler helper with the game's packed
// R11G11B10 float format. Flat RGB/HDR inputs must retain channels and gain.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include "totk_mfx_up.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static uint32_t pack(float value,unsigned mantissa){
 _Float16 h=(_Float16)value;uint16_t bits;memcpy(&bits,&h,2);
 unsigned shift=10-mantissa;return ((uint32_t)bits+(1u<<(shift-1)))>>shift;
}
static float unpack(uint32_t bits,unsigned mantissa){
 unsigned exp=bits>>mantissa,m=bits&((1u<<mantissa)-1);
 if(exp==31)return INFINITY;
 return exp?ldexpf(1.0f+(float)m/(1u<<mantissa),(int)exp-15):ldexpf((float)m,-14-(int)mantissa);
}
int main(void){@autoreleasepool{
 id<MTLDevice>d=MTLCreateSystemDefaultDevice();NSError *error=nil;
 id<MTL4CommandQueue>queue=[d newMTL4CommandQueue];id<MTLCommandQueue>blitQueue=[d newCommandQueue];
 id<MTL4CommandAllocator>allocator=[d newCommandAllocator];id<MTL4CommandBuffer>cb=[d newCommandBuffer];
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRG11B10Float width:64 height:64 mipmapped:NO];
 td.usage=MTLTextureUsageShaderRead;td.storageMode=MTLStorageModeShared;id<MTLTexture>source=[d newTextureWithDescriptor:td];
 td.width=td.height=128;td.usage=MTLTextureUsageShaderRead|MTLTextureUsageShaderWrite|MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModePrivate;
 id<MTLTexture>target=[d newTextureWithDescriptor:td];id<MTLBuffer>readback=[d newBufferWithLength:128*128*4 options:MTLResourceStorageModeShared];
 id<MTLResidencySet>rs=[d newResidencySetWithDescriptor:[MTLResidencySetDescriptor new] error:&error];
 if(!source||!target||!rs){fprintf(stderr,"resources: %s\n",error.description.UTF8String);return 1;}
 [rs addAllocation:source];[rs addAllocation:target];[rs commit];[queue addResidencySet:rs];
 int ready=0;for(unsigned i=0;i<1000&&!ready;i++){ready=mfxup_prepare(MFXUP_DOCKED,source,target,128,128,MFXUP_HDR);if(!ready)usleep(10000);}
 if(!ready){fprintf(stderr,"production HDR scaler did not become ready\n");return 1;}
 id<MTLResidencySet>own=mfxup_residency();if(own)[queue addResidencySet:own];
 const float colors[][3]={{0,0,0},{.1,.2,.3},{.2,.7,.4},{.8,.1,.6},{1,0,0},{0,1,0},{0,0,1},{1,1,1},{1.5,.5,2},{2.5,3,1.5},{3.5,3.5,3.5}};
 for(unsigned n=0;n<sizeof colors/sizeof *colors;n++){
  uint32_t pixel=pack(colors[n][0],6)|(pack(colors[n][1],6)<<11)|(pack(colors[n][2],5)<<22),pixels[64*64];
  for(unsigned i=0;i<64*64;i++)pixels[i]=pixel;
  [source replaceRegion:MTLRegionMake2D(0,0,64,64) mipmapLevel:0 withBytes:pixels bytesPerRow:64*4];
  [allocator reset];[cb beginCommandBufferWithAllocator:allocator];
  if(!mfxup_encode_ex(MFXUP_DOCKED,cb,source,64,64,target,128,128,MFXUP_HDR)){fprintf(stderr,"encode refused\n");return 1;}
  [cb endCommandBuffer];dispatch_semaphore_t done=dispatch_semaphore_create(0);__block NSError *gpuError=nil;
  MTL4CommitOptions *options=[MTL4CommitOptions new];[options addFeedbackHandler:^(id<MTL4CommitFeedback>feedback){gpuError=feedback.error;dispatch_semaphore_signal(done);}];
  const id<MTL4CommandBuffer>list[]={cb};[queue commit:list count:1 options:options];
  if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))||gpuError){fprintf(stderr,"GPU: %s\n",gpuError.description.UTF8String);return 1;}
  id<MTLCommandBuffer>copy=[blitQueue commandBuffer];id<MTLBlitCommandEncoder>enc=[copy blitCommandEncoder];
  [enc copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(128,128,1) toBuffer:readback destinationOffset:0 destinationBytesPerRow:128*4 destinationBytesPerImage:128*128*4];
  [enc endEncoding];[copy commit];[copy waitUntilCompleted];if(copy.error){fprintf(stderr,"readback failed\n");return 1;}
  uint32_t got=((uint32_t*)readback.contents)[64*128+64];
  const unsigned shifts[]={0,11,22},mantissas[]={6,6,5},masks[]={2047,2047,1023};
  for(unsigned c=0;c<3;c++){
   float value=unpack((got>>shifts[c])&masks[c],mantissas[c]),want=unpack((pixel>>shifts[c])&masks[c],mantissas[c]);
   if(!isfinite(value)||fabsf(value-want)>.004f+want*.04f){fprintf(stderr,"FAIL color %u channel %u got %g want %g\n",n,c,value,want);return 1;}
  }
 }
 printf("{\"status\":\"pass\",\"cases\":11,\"scope\":\"production Metal4 HDR spatial helper, packed game format, flat RGB/HDR 0..3.5 keeps channels and gain\"}\n");return 0;
}}
