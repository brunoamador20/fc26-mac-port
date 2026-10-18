// Run an exact translated spatial-upscale fragment shader on constant HDR/RGB
// inputs. This catches channel swaps and a missing normalization/un-normalization
// pair before admitting another shader to the manual MetalFX replacement path.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>
#include <stdio.h>

int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=2)return 2;
 NSError *error=nil;id<MTLDevice>d=MTLCreateSystemDefaultDevice();
 NSString *source=[NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:&error];
 if(getenv("TOTK_PROBE_NEGATIVE"))source=[source stringByReplacingOccurrencesOfString:@"* 3.5;" withString:@"* 1.0;"];
 source=[source stringByAppendingString:@"\nstruct probe_v { float4 p [[position]]; float4 uv [[user(locn0)]]; };\nvertex probe_v probe_vertex(uint id [[vertex_id]]) { float2 p=float2(id==1?3.0:-1.0,id==2?3.0:-1.0);probe_v o;o.p=float4(p,0,1);o.uv=float4(p*0.5+0.5,0,0);return o;}\n"];
 MTLCompileOptions *options=[MTLCompileOptions new];options.mathMode=MTLMathModeSafe;
 id<MTLLibrary>lib=[d newLibraryWithSource:source options:options error:&error];
 if(!lib){fprintf(stderr,"compile: %s\n",error.description.UTF8String);return 1;}
 id<MTLFunction>fs=[lib newFunctionWithName:@"main0"];
 MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"probe_vertex"];pd.fragmentFunction=fs;pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
 id<MTLRenderPipelineState>pso=[d newRenderPipelineStateWithDescriptor:pd error:&error];
 if(!pso){fprintf(stderr,"pipeline: %s\n",error.description.UTF8String);return 1;}
 id<MTLBuffer>support=[d newBufferWithLength:65536 options:MTLResourceStorageModeShared];
 id<MTLBuffer>c3=[d newBufferWithLength:65536 options:MTLResourceStorageModeShared];
 id<MTLBuffer>c1=[d newBufferWithLength:65536 options:MTLResourceStorageModeShared];
 memset(support.contents,0,65536);memset(c3.contents,0,65536);memset(c1.contents,0,65536);
 // support_buffer._m5 starts at 0xc0 (uint4 bank); entries 1/2 are texture scaling.
 ((float*)support.contents)[0xc0/4+4]=1;((float*)support.contents)[0xc0/4+8]=1;
 float *params=c3.contents;params[0]=params[1]=1;params[4]=1;
 ((uint32_t*)params)[16]=((uint32_t*)params)[17]=16;
 ((uint32_t*)c1.contents)[0]=0x1fbc4639;((float*)c1.contents)[1]=2;
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:16 height:16 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageShaderRead;
 id<MTLTexture>input=[d newTextureWithDescriptor:td];td.usage=MTLTextureUsageRenderTarget;id<MTLTexture>output=[d newTextureWithDescriptor:td];
 MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;id<MTLSamplerState>sampler=[d newSamplerStateWithDescriptor:sd];
 id<MTLArgumentEncoder>ae=[fs newArgumentEncoderWithBufferIndex:0];id<MTLBuffer>args=[d newBufferWithLength:ae.encodedLength options:MTLResourceStorageModeShared];[ae setArgumentBuffer:args offset:0];
 [ae setBuffer:support offset:0 atIndex:0];[ae setBuffer:c3 offset:0 atIndex:1];[ae setBuffer:c1 offset:0 atIndex:2];[ae setTexture:input atIndex:3];[ae setSamplerState:sampler atIndex:4];
 const float colors[][3]={{0,0,0},{0.1,0.2,0.3},{0.2,0.7,0.4},{0.8,0.1,0.6},{1,0,0},{0,1,0},{0,0,1},{1,1,1},{1.5,0.5,2},{2.5,3,1.5},{3.5,3.5,3.5},{5,4,6}};
 id<MTLCommandQueue>queue=[d newCommandQueue];
 for(unsigned n=0;n<sizeof colors/sizeof *colors;n++){
  float pixels[16*16*4];for(int i=0;i<16*16;i++){for(int j=0;j<3;j++)pixels[4*i+j]=colors[n][j];pixels[4*i+3]=1;}
  [input replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:pixels bytesPerRow:16*16];
  MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=output;rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
  id<MTLCommandBuffer>cb=[queue commandBuffer];id<MTLRenderCommandEncoder>enc=[cb renderCommandEncoderWithDescriptor:rp];[enc setRenderPipelineState:pso];[enc setFragmentBuffer:args offset:0 atIndex:0];
  for(id<MTLResource>resource in @[support,c3,c1,input])[enc useResource:resource usage:MTLResourceUsageRead stages:MTLRenderStageFragment];
  [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];[cb commit];[cb waitUntilCompleted];
  if(cb.status!=MTLCommandBufferStatusCompleted){fprintf(stderr,"GPU: %s\n",cb.error.description.UTF8String);return 1;}
  float got[4];[output getBytes:got bytesPerRow:16 fromRegion:MTLRegionMake2D(8,8,1,1) mipmapLevel:0];
  for(int j=0;j<3;j++){float want=fminf(colors[n][j],3.5f);if(!isfinite(got[j])||fabsf(got[j]-want)>0.015f){fprintf(stderr,"FAIL color %u channel %d got %.6g want %.6g\n",n,j,got[j],want);return 1;}}
 }
 printf("{\"status\":\"pass\",\"cases\":12,\"scope\":\"exact translated v143 EASU shader: RGB/HDR flat colors retain their channels and gain, clamp at 3.5\"}\n");return 0;
}}
