"""Real copy_t2t: six RG11B10 faces, 128->64->32->16, linear NVN copies.

No game assets. Compile production functions and execute them on Metal 4.
FC26_NVN_DIR can select the source before a fix for regression verification.
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

NVN = Path(os.environ.get('FC26_NVN_DIR') or Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn')

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <math.h>
#include <stdatomic.h>
#include "nvn_obj.h"
#define MLOG(...) fprintf(stderr, __VA_ARGS__)
#define RED_ONCE(k, ...) do { errors++; } while(0)
#define PD(...) ((void)0)
static int errors, g_pso_dirty, g_dss_dirty;
static _Atomic uint64_t g_cur_frame;
static id<MTLDevice> g_dev;
static id g_cb, g_blit;
static id<MTLResidencySet> g_res;
static id<MTLTexture> cube, extra;
static const tex_t *extra_tex;
static id<MTLTexture> tex_mtl(const tex_t *t) { return t == extra_tex ? extra : cube; }
static void res_add(id o) { if(o) [g_res addAllocation:o]; }
/* Per-submission arena: every call gets fresh memory that lives until the command buffer has run. */
static size_t arena_alloc(size_t n, id<MTLBuffer> *buf) { *buf=[g_dev newBufferWithLength:n options:MTLResourceStorageModeShared]; res_add(*buf); return 0; }
static void rp_end(void) {} static void rp_flush(void) {}
static void blit_close(void) {} static void rs_sync(void) {}
static void pt_mark(id cb,char k,id d) {}
/* These copy-only tests keep timing disabled, as in the default runtime. */
static void gp_begin(id e, char kind, id d) { (void)e; (void)kind; (void)d; } static void es_reset(void) {}
static void m4_end(id e) { [e endEncoding]; }
static void enc_b_end(id e) { [e endEncoding]; }
static void args_dirty_all(void) {}
static void defer_obj_unref(id o) {} static void defer_obj_release(id o) {}
static void xv_check(uint64_t s,unsigned l,unsigned a,const char *w) {}
static void zskip_del(uint64_t s) {} static int zskip_has(uint64_t s,int l,int a) { return 0; }
static void zskip_add(uint64_t s,int l,int a) {}
static int b2t_log_gate(_Atomic uint64_t *n) { return 0; }
static int no_bc(void) { return 0; }
static id blit(void) { abort(); }
static void enc_b_copy_texture(id e,id s,unsigned ss,unsigned sl,MTLOrigin so,MTLSize z,id d,unsigned ds,unsigned dl,MTLOrigin dd) { abort(); }
static int copy_t2t_astc(id s,id d,unsigned sl,unsigned ss,unsigned dl,unsigned ds,int sx,int sy,int dx,int dy,int w,int h) { return 0; }
static int copy_t2t_depth(id s,id d,unsigned sl,unsigned ss,unsigned dl,unsigned ds,int sx,int sy,int dx,int dy,int w,int h) { return 0; }
/*PRODUCTION*/
static uint32_t pack(float r,float g,float b) {
    _Float16 h[3]={r,g,b};uint16_t u[3];memcpy(u,h,6);
    return (u[0]>>4) | ((uint32_t)(u[1]>>4)<<11) | ((uint32_t)(u[2]>>5)<<22);
}
static float unpack(uint32_t u,int bits) {
    int m=bits-5,e=u>>m;unsigned f=u&((1u<<m)-1);
    if(e==31)return f?NAN:INFINITY;
    return e?ldexpf(1.0f+(float)f/(1u<<m),e-15):ldexpf((float)f,1-15-m);
}
int main(void) { @autoreleasepool {
    g_dev=MTLCreateSystemDefaultDevice(); if(!g_dev)return 77;
    NSError *err=nil;
    id<MTL4CommandQueue> q=[g_dev newMTL4CommandQueueWithDescriptor:[MTL4CommandQueueDescriptor new] error:&err];
    id<MTL4CommandAllocator> alloc=[g_dev newCommandAllocator];
    g_res=[g_dev newResidencySetWithDescriptor:[MTLResidencySetDescriptor new] error:&err];[q addResidencySet:g_res];
    MTLTextureDescriptor *td=[MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatRG11B10Float size:128 mipmapped:YES];
    td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    cube=[g_dev newTextureWithDescriptor:td];res_add(cube);
    uint32_t *pixels=malloc(128*128*4);
    for(int face=0;face<6;face++)for(int lv=0;lv<4;lv++) {
        int w=128>>lv;
        for(int y=0;y<w;y++)for(int x=0;x<w;x++)pixels[y*w+x]=lv?0xfc0007e0u:pack((face+1)/16.0f+x/256.0f,(y&1)?.75f:.25f,(x&1)?.375f:.125f);
        [cube replaceRegion:MTLRegionMake2D(0,0,w,w) mipmapLevel:lv slice:face withBytes:pixels bytesPerRow:w*4 bytesPerImage:w*w*4];
    }
    tex_t t={0};t.serial=1;t.d.target=8;t.d.width=t.d.height=128;t.d.levels=8;t.d.format=0x3f;
    g_cb=[g_dev newCommandBuffer];[g_cb beginCommandBufferWithAllocator:alloc];
    for(int face=0;face<6;face++)for(int lv=0;lv<3;lv++) {
        p_copy_t2t c={0};c.src=c.dst=&t;c.has_sv=c.has_dv=1;
        c.sv.set_levels=c.dv.set_levels=1;c.sv.base_level=lv;c.dv.base_level=lv+1;
        c.sv.set_layers=c.dv.set_layers=1;
        if(face<3)c.sv.min_layer=c.dv.min_layer=face;else c.sr.zoffset=c.dr.zoffset=face;
        c.sr.width=c.sr.height=128>>lv;c.dr.width=c.dr.height=64>>lv;c.sr.depth=c.dr.depth=1;c.flags=NVN_COPY_FLAGS_LINEAR_FILTER_BIT;
        copy_t2t(&c);
    }
    /* A following unrelated upsample must not overwrite parameters still used by the chain. */
    td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRG11B10Float width:128 height:128 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    extra=[g_dev newTextureWithDescriptor:td];res_add(extra);tex_t et=t;et.serial=2;et.d.target=1;extra_tex=&et;
    p_copy_t2t c={0};c.src=&t;c.dst=&et;c.has_sv=1;c.sv.set_levels=1;c.sv.base_level=1;c.sv.set_layers=1;c.sv.min_layer=5;c.sr.width=c.sr.height=64;c.dr.width=c.dr.height=128;c.sr.depth=c.dr.depth=1;c.flags=1;copy_t2t(&c);
    [g_cb endCommandBuffer];[g_res commit];id<MTL4CommandBuffer> cbs[]={g_cb};[q commit:cbs count:1 options:[MTL4CommitOptions new]];
    id<MTLSharedEvent> ev=[g_dev newSharedEvent];[q signalEvent:ev value:1];if(![ev waitUntilSignaledValue:1 timeoutMS:15000])return 9;
    int bad=0,nan=0;float max_error=0;
    for(int face=0;face<6;face++) {
        [cube getBytes:pixels bytesPerRow:64 bytesPerImage:1024 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:3 slice:face];
        for(int y=0;y<16;y++)for(int x=0;x<16;x++) {
            uint32_t w=pixels[y*16+x];float a[3]={unpack(w&2047,11),unpack((w>>11)&2047,11),unpack(w>>22,10)};
            float expected[3]={(face+1)/16.0f+(8*x+3.5f)/256.0f,.5f,.25f};
            for(int k=0;k<3;k++){float d=fabsf(a[k]-expected[k]);if(!isfinite(a[k]))nan++;else if(d>max_error)max_error=d;if(!isfinite(a[k])||d>.02f)bad++;}
        }
    }
    printf("faces=6 mip=16 nan=%d bad=%d max_error=%g dropped=%d\n",nan,bad,max_error,errors);
    return bad||errors?2:0;
}}
'''

class CubemapMipRegression(unittest.TestCase):
    def test_real_copy_chain(self):
        if platform.system() != 'Darwin' or not shutil.which('clang'):
            self.skipTest('Metal 4 requires macOS and clang')
        src=(NVN/'nvn_mtl.m').read_text()
        copy=re.search(r'^static void copy_t2t\(.*?^}',src,re.M|re.S)
        self.assertIsNotNone(copy)
        scale=re.search(r'^static const char k_scale_copy_msl\[\].*?^static int copy_t2t_scale\(.*?^}',src,re.M|re.S)
        code=HARNESS.replace('/*PRODUCTION*/',(scale.group(0) if scale else '')+'\n'+copy.group(0))
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'cubemap'
            build=subprocess.run(['clang','-x','objective-c','-fobjc-arc','-I',str(NVN),'-I',str(NVN/'include'),'-framework','Metal','-framework','Foundation','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(exe)],text=True,capture_output=True,timeout=180)
            if run.returncode==77:self.skipTest('No Metal device')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('nan=0 bad=0',run.stdout)
            print(run.stdout.strip())
