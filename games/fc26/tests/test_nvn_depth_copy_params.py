"""More than four production depth copies must retain each command's parameters."""
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest
from test_nvn_cubemap_mips import HARNESS, NVN

MAIN = r'''
int main(void) { @autoreleasepool {
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;
 NSError *err=nil;id<MTL4CommandQueue> q=[g_dev newMTL4CommandQueueWithDescriptor:[MTL4CommandQueueDescriptor new] error:&err];
 id<MTL4CommandAllocator> alloc=[g_dev newCommandAllocator];g_res=[g_dev newResidencySetWithDescriptor:[MTLResidencySetDescriptor new] error:&err];[q addResidencySet:g_res];
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:64 height:4 mipmapped:NO];td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
 id<MTLTexture> src=[g_dev newTextureWithDescriptor:td],dst=[g_dev newTextureWithDescriptor:td];res_add(src);res_add(dst);
 id<MTLBuffer> upload=[g_dev newBufferWithLength:1024 options:MTLResourceStorageModeShared];for(int i=0;i<256;i++)((float *)upload.contents)[i]=(i%64+1)/128.0f;
 id<MTLCommandQueue> legacy=[g_dev newCommandQueue];id<MTLCommandBuffer> u=[legacy commandBuffer];id<MTLBlitCommandEncoder> b=[u blitCommandEncoder];[b copyFromBuffer:upload sourceOffset:0 sourceBytesPerRow:256 sourceBytesPerImage:1024 sourceSize:MTLSizeMake(64,4,1) toTexture:src destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];[b endEncoding];[u commit];[u waitUntilCompleted];
 g_cb=[g_dev newCommandBuffer];[g_cb beginCommandBufferWithAllocator:alloc];
 MTL4RenderPassDescriptor *clear=[MTL4RenderPassDescriptor new];clear.depthAttachment.texture=dst;clear.depthAttachment.loadAction=MTLLoadActionClear;clear.depthAttachment.clearDepth=.9;clear.depthAttachment.storeAction=MTLStoreActionStore;[[g_cb renderCommandEncoderWithDescriptor:clear] endEncoding];
 for(int i=0;i<6;i++)if(!copy_t2t_depth(src,dst,0,0,0,0,i+2,0,i*4,1,2,1))return 3;
 [g_cb endCommandBuffer];[g_res commit];id<MTL4CommandBuffer> cbs[]={g_cb};[q commit:cbs count:1 options:[MTL4CommitOptions new]];id<MTLSharedEvent> ev=[g_dev newSharedEvent];[q signalEvent:ev value:1];if(![ev waitUntilSignaledValue:1 timeoutMS:15000])return 9;
 id<MTLBuffer> rb=[g_dev newBufferWithLength:1024 options:MTLResourceStorageModeShared];u=[legacy commandBuffer];b=[u blitCommandEncoder];[b copyFromTexture:dst sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(64,4,1) toBuffer:rb destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:1024];[b endEncoding];[u commit];[u waitUntilCompleted];
 float *p=rb.contents;int bad=0;for(int y=0;y<4;y++)for(int x=0;x<64;x++){float expected=.9f;if(y==1)for(int i=0;i<6;i++)if(x>=i*4&&x<i*4+2)expected=(i+3+x-i*4)/128.0f;if(fabsf(p[y*64+x]-expected)>1e-5f)bad++;}
 printf("depth_copies=6 bad=%d\n",bad);return bad?2:0;
}}
'''

class DepthCopyParamsTest(unittest.TestCase):
 def test_six_copies_one_submission(self):
  if platform.system()!='Darwin' or not shutil.which('clang'):self.skipTest('Metal required')
  src=(NVN/'nvn_mtl.m').read_text();m=re.search(r'^static const char k_depth_copy_msl\[\].*?^static int copy_t2t_depth\(.*?^}',src,re.M|re.S);self.assertIsNotNone(m)
  prefix=HARNESS.split('/*PRODUCTION*/')[0];prefix=re.sub(r'^static int copy_t2t_depth\(.*?\n','',prefix,flags=re.M);prefix=prefix.replace('newBufferWithLength:n options','newBufferWithLength:n+256 options').replace('res_add(*buf); return 0;','res_add(*buf); return 256;')
  with tempfile.TemporaryDirectory()as tmp:
   exe=Path(tmp)/'depth';build=subprocess.run(['clang','-x','objective-c','-I',str(NVN),'-I',str(NVN/'include'),'-framework','Metal','-framework','Foundation','-','-o',str(exe)],input=prefix+m.group(0)+MAIN,text=True,capture_output=True);self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run(['/usr/bin/lockf','-k','/tmp/fc26-boot.lock',str(exe)],text=True,capture_output=True,timeout=180)
   if run.returncode==77:self.skipTest('No Metal device')
   self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertIn('bad=0',run.stdout);print(run.stdout.strip())
