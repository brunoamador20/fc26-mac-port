"""Native virtual sources must still support GPU clears/scaled-copy render passes.

Compiles the real tex_desc, format map and depth promotion. BC-only hooks are
unused for the native RGBA8 formats tested here. No game data.
"""
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import unittest

NVN = Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn'


@unittest.skipUnless(platform.system() == 'Darwin', 'Metal required')
class VirtualRenderTest(unittest.TestCase):
    def test_native_virtual_descriptors_remain_renderable(self):
        src = (NVN / 'nvn_mtl.m').read_text()
        funcs = []
        for name in ('fmt_compressed', 'fmt_depth', 'depth_promote_type', 'tex_desc'):
            pat = r'^static [^\n]*\b' + name + r'\([^\n]*\{[^\n]*}\n' if name in ('fmt_compressed', 'fmt_depth') else r'^static [^\n]*\b' + name + r'\(.*?^}'
            m = re.search(pat, src, re.M | re.S)
            self.assertIsNotNone(m, name)
            funcs.append(m.group())
        runner = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include "nvn_obj.h"
#include "../tex/nvn_fmt_mtl.h"
#include <stdio.h>
#define RED_ONCE(...) ((void)0)
static int tex_astc(const tex_t *t){return 0;}
static int tex_tc(const tex_t *t){return 0;}
static MTLPixelFormat bc1_astc_pf(int f){return 0;}
static MTLPixelFormat tc_pf(int f){return 0;}
static int bc_unpack(int f,uint32_t *p,int *b){return 0;}
static int tex_swizzle(const tex_t *t,int f,MTLTextureSwizzleChannels *s){return 0;}
/*FUNCS*/
int main(void){@autoreleasepool{
 id<MTLDevice> dev=MTLCreateSystemDefaultDevice();if(!dev)return 77;
 pool_t pool={0};pool.flags=0x221;tex_t t={0};t.pool=&pool;t.d.target=1;t.d.width=16;t.d.height=16;t.d.levels=1;
 int bad=0;
 pool.flags=0x21;t.d.format=NVN_FORMAT_RGBA8;bad+=!!(tex_desc(&t,1).usage&MTLTextureUsageRenderTarget);
 pool.flags=0x221;t.d.format=0x46;bad+=!!(tex_desc(&t,1).usage&MTLTextureUsageRenderTarget);
 for(int i=0;i<2;i++){
  t.d.format=i?NVN_FORMAT_RGBA8_SRGB:NVN_FORMAT_RGBA8;
  MTLTextureDescriptor *d=tex_desc(&t,1);
  printf("native_virtual fmt=%#x renderable=%d\n",t.d.format,!!(d.usage&MTLTextureUsageRenderTarget));
  if(!(d.usage&MTLTextureUsageRenderTarget)){bad++;continue;}
  id<MTLTexture> tex=[dev newTextureWithDescriptor:d];if(!tex)return 3;
  id<MTLCommandQueue> q=[dev newCommandQueue];id<MTLCommandBuffer> cb=[q commandBuffer];
  MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=tex;rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;rp.colorAttachments[0].clearColor=MTLClearColorMake(.25,.5,.75,1);
  [[cb renderCommandEncoderWithDescriptor:rp] endEncoding];
  id<MTLBuffer> rb=[dev newBufferWithLength:1024 options:MTLResourceStorageModeShared];id<MTLBlitCommandEncoder> en=[cb blitCommandEncoder];
  [en copyFromTexture:tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(16,16,1) toBuffer:rb destinationOffset:0 destinationBytesPerRow:64 destinationBytesPerImage:1024];[en endEncoding];[cb commit];[cb waitUntilCompleted];
  uint8_t *p=rb.contents;int r=i?137:64,g=i?188:128,b=i?225:191;
  for(int k=0;k<256;k++)bad+=abs((int)p[k*4]-r)>1||abs((int)p[k*4+1]-g)>1||abs((int)p[k*4+2]-b)>1||p[k*4+3]!=255;
 }
 printf("virtual_render_bad=%d\n",bad);return bad?1:0;
}}
'''.replace('/*FUNCS*/', '\n'.join(funcs))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'runner.m').write_text(runner)
            exe = tmp / 'runner'
            build = subprocess.run(['clang', '-fobjc-arc', '-I', str(NVN), '-I', str(NVN / 'include'), '-framework', 'Metal', '-framework', 'Foundation', str(tmp / 'runner.m'), str(NVN.parent / 'tex/nvn_fmt_mtl.c'), '-o', str(exe)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], text=True, capture_output=True, timeout=180)
            if run.returncode == 77:
                self.skipTest('No Metal device')
            print(run.stdout.strip())
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
