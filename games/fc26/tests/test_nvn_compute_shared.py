"""Real Metal compiler + shared-memory repair; no game shader/data.

Reproduces a 64-lane BC encoder's 432-byte lane stride and last word at +424.
NVN control+0x754 declares 27644 bytes. Old cached MSL reserves just 4096.
On the old revision the source goes unchanged to the real compiler, as in sh_load.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import tempfile
import unittest

NVN = Path(os.environ.get('FC26_NVN_DIR') or Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn')
MSL = r'''
#include <metal_stdlib>
using namespace metal;
template<typename T,size_t N>struct spvUnsafeArray {T elements[N];threadgroup T& operator[](size_t i)threadgroup{return elements[i];}};
kernel void probe(device uint *out [[buffer(0)]],uint3 id [[thread_position_in_threadgroup]]) {
 threadgroup spvUnsafeArray<uint, 1024> shared_memory;
 uint lane=id.x*8+id.y,at=lane*108+106;
 uint cap=sizeof(shared_memory.elements)/sizeof(uint);
 if(at<cap)shared_memory[at]=lane+1;
 threadgroup_barrier(mem_flags::mem_threadgroup);
 uint next=(lane+1)%64,pos=next*108+106;
 out[lane]=pos<cap?shared_memory[pos]:0;
}
'''
# Two shared arrays: the control total does not say how to split it, so nothing grows.
MSL_TWO = MSL.replace('threadgroup spvUnsafeArray<uint, 1024> shared_memory;',
                      'threadgroup spvUnsafeArray<uint, 1024> shared_memory;\n threadgroup spvUnsafeArray<uint, 1024> other;') \
    .replace('if(at<cap)', 'other[lane]=lane;if(at<cap)').replace('out[lane]=pos<cap?shared_memory[pos]:0;',
                                                                    'out[lane]=(pos<cap?shared_memory[pos]:0)+(other[next]>1000u?1u:0u);')
# SPIR-V Cross passes the shared array by reference to helper functions (about 1 in 3
# cached compute shaders): their parameter type must grow with the declaration.
MSL_HELPER = MSL.replace('kernel void probe', '''static inline void put(threadgroup spvUnsafeArray<uint, 1024>& s, uint at, uint v) { s[at] = v; }
kernel void probe''').replace('if(at<cap)shared_memory[at]=lane+1;', 'if(at<cap)put(shared_memory,at,lane+1);')


@unittest.skipUnless(platform.system() == 'Darwin', 'Metal required')
class ComputeSharedTest(unittest.TestCase):
    def test_control_size_preserves_all_64_lanes(self):
        self.run_probe(MSL)

    def test_helper_parameters_follow_the_repaired_size(self):
        self.run_probe(MSL_HELPER)

    def test_two_shared_arrays_are_left_alone(self):
        self.run_probe(MSL_TWO, expect_bytes=8192)

    def run_probe(self, msl, expect_bytes=None):
        source = (NVN / 'nvn_mtl.m').read_text()
        functions = []
        for name in ('totk_precise_opts', 'totk_msl_library'):
            m = re.search(r'^static [^\n]*\b' + name + r'\(.*?^}', source, re.M | re.S)
            self.assertIsNotNone(m)
            functions.append(m.group())
        repair = re.search(r'^static NSString \*compute_shared_source\(.*?^}', source, re.M | re.S)
        if repair:
            functions.append(repair.group())
        apply = 'src=compute_shared_source(src,control);' if repair else ''
        runner = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static id<MTLDevice> g_dev;
#define MLOG(...) ((void)0)
/*FUNCTIONS*/
int main(int argc,const char **argv){@autoreleasepool{
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;
 NSString *src=[NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:nil];
 uint8_t control[0x880]={0};uint32_t stage=5,bytes=27644;
 memcpy(control+0x714,&stage,4);memcpy(control+0x754,&bytes,4);
 /*APPLY*/
 NSError *err=nil;id<MTLLibrary> lib=totk_msl_library(src,&err);
 if(!lib){fprintf(stderr,"%s\n",err.localizedDescription.UTF8String);return 3;}
 id<MTLComputePipelineState> ps=[g_dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"probe"] error:&err];
 if(!ps)return 4;
 id<MTLBuffer> out=[g_dev newBufferWithLength:256 options:MTLResourceStorageModeShared];memset(out.contents,0,256);
 id<MTLCommandBuffer> cb=[[g_dev newCommandQueue] commandBuffer];id<MTLComputeCommandEncoder> en=[cb computeCommandEncoder];
 [en setComputePipelineState:ps];[en setBuffer:out offset:0 atIndex:0];
 [en dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(8,8,1)];[en endEncoding];[cb commit];[cb waitUntilCompleted];
 unsigned bad=0;uint32_t *p=out.contents;for(unsigned i=0;i<64;i++)bad+=p[i]!=(i+1)%64+1;
 printf("shared_bytes=%lu required=%u lanes=64 bad=%u\n",(unsigned long)ps.staticThreadgroupMemoryLength,bytes,bad);
 return 0;
}}
'''.replace('/*FUNCTIONS*/', '\n'.join(functions)).replace('/*APPLY*/', apply)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'probe.metal').write_text(msl)
            (tmp / 'runner.m').write_text(runner)
            exe = tmp / 'runner'
            build = subprocess.run(['clang', '-fobjc-arc', '-fblocks', '-framework', 'Metal', '-framework', 'Foundation', str(tmp / 'runner.m'), '-o', str(exe)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe), str(tmp / 'probe.metal')], text=True, capture_output=True, timeout=180)
            if run.returncode == 77:
                self.skipTest('No Metal device')
            print(run.stdout.strip())
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            got = dict(kv.split('=') for kv in run.stdout.split())
            if expect_bytes is not None:
                self.assertEqual(int(got['shared_bytes']), expect_bytes, run.stdout)
            else:
                self.assertGreaterEqual(int(got['shared_bytes']), 27644, run.stdout)
                self.assertEqual(got['bad'], '0', run.stdout)
