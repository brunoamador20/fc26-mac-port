"""Test 1D and 1DArray depth/stencil texture promotion to 2D/2DArray for Metal compliance.

Metal requires depth and stencil pixel formats to be of type MTLTextureType2D[Array]
or MTLTextureTypeCube[Array]. 1D depth textures (created e.g. as Frostbite dummy/fallback
textures) must be promoted to 2D with height=1.
"""
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_MTL = HERE / 'third_party/d2r_gfx/gfx/nvn/nvn_mtl.m'


class NvnDepth1DTest(unittest.TestCase):
    def test_depth_1d_target_promotion_in_metal_source(self):
        """nvn_mtl.m must use depth_promote_type in tex_desc and tex_by_id."""
        src = NVN_MTL.read_text(encoding='utf-8')

        # Check depth_promote_type definition and usage
        self.assertIn('depth_promote_type', src,
                      'nvn_mtl.m must define depth_promote_type')
        self.assertRegex(src, r'depth_promote_type\s*\(\s*t->d\.format\s*,\s*d\.textureType\s*\)',
                         'tex_desc must call depth_promote_type to promote textureType')
        self.assertRegex(src, r'depth_promote_type\s*\([^,]+,\s*tt\s*\)',
                         'tex_by_id must call depth_promote_type to promote view textureType')

    def test_isolated_depth_promotion_logic(self):
        """Compile and execute an isolated C test verifying depth promotion rules."""
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang not available')

        c_code = r'''
#include <stdio.h>
#include <assert.h>
#include <stdint.h>

// Mirror Metal texture type enum values
typedef enum {
    MTLTextureType1D = 0,
    MTLTextureType1DArray = 1,
    MTLTextureType2D = 2,
    MTLTextureType2DArray = 3,
    MTLTextureType2DMultisample = 4,
    MTLTextureTypeCube = 5,
    MTLTextureTypeCubeArray = 6,
    MTLTextureType3D = 7,
} MTLTextureType;

@@PROMOTE@@

static MTLTextureType ttype(int target, int fallback) {
    switch (target) { case 0: return MTLTextureType1D; case 1: case 7: return MTLTextureType2D; case 2: return MTLTextureType3D;
        case 3: return MTLTextureType1DArray; case 4: return MTLTextureType2DArray; case 5: return MTLTextureType2DMultisample;
        case 8: return MTLTextureTypeCube; case 9: return MTLTextureTypeCubeArray; }
    return (MTLTextureType)fallback;
}

int main(void) {
    // 1. Depth format 0x34 (Depth32F): 1D -> 2D
    assert(depth_promote_type(0x34, MTLTextureType1D) == MTLTextureType2D);
    // 2. Depth format 0x32 (Depth16): 1DArray -> 2DArray
    assert(depth_promote_type(0x32, MTLTextureType1DArray) == MTLTextureType2DArray);
    // 3. Stencil format 0x31: 1D -> 2D
    assert(depth_promote_type(0x31, MTLTextureType1D) == MTLTextureType2D);
    // 4. Color format 0x25 (RGBA8): 1D stays 1D
    assert(depth_promote_type(0x25, MTLTextureType1D) == MTLTextureType1D);
    // 5. Color format 0x25 (RGBA8): 1DArray stays 1DArray
    assert(depth_promote_type(0x25, MTLTextureType1DArray) == MTLTextureType1DArray);
    // 6. Depth 2D stays 2D
    assert(depth_promote_type(0x34, MTLTextureType2D) == MTLTextureType2D);
    // 7. Depth Cube stays Cube
    assert(depth_promote_type(0x34, MTLTextureTypeCube) == MTLTextureTypeCube);
    // 8. View: target 0 (1D) requested on promoted depth base
    MTLTextureType base_type = depth_promote_type(0x34, ttype(0, MTLTextureType2D)); // base was promoted to 2D
    assert(base_type == MTLTextureType2D);
    MTLTextureType view_tt = ttype(0, base_type); // view requested target 0 (1D)
    assert(view_tt == MTLTextureType1D);
    view_tt = depth_promote_type(0x34, view_tt); // promoted view type
    assert(view_tt == MTLTextureType2D);

    printf("PASS: isolated depth promotion logic\n");
    return 0;
}
'''
        src = NVN_MTL.read_text(encoding='utf-8')
        fmt = re.search(r'^static int fmt_depth\(int f\).*$', src, re.M)
        promote = re.search(r'^static inline MTLTextureType depth_promote_type\(.*?^}$', src, re.M | re.S)
        self.assertIsNotNone(fmt, 'nvn_mtl.m must define fmt_depth')
        self.assertIsNotNone(promote, 'nvn_mtl.m must define depth_promote_type')
        c_code = c_code.replace('@@PROMOTE@@', fmt.group(0) + '\n' + promote.group(0))
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_isolated_depth'
            build = subprocess.run([compiler, '-x', 'c', '-', '-o', str(exe)],
                                   input=c_code, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)

    def test_unpromoted_1d_depth_aborts_on_metal(self):
        """Verify that without promotion, Metal rejects Depth32Float on 1D texture descriptor."""
        if platform.system() != 'Darwin':
            self.skipTest('Metal device tests only run on Darwin (macOS)')

        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang not available')

        c_code = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) return 0;
        MTLTextureDescriptor *d = [MTLTextureDescriptor new];
        d.pixelFormat = MTLPixelFormatDepth32Float;
        d.textureType = MTLTextureType1D;
        d.width = 1;
        d.height = 1;
        d.depth = 1;
        d.arrayLength = 1;
        d.mipmapLevelCount = 1;
        // Metal validation aborts here
        [dev newTextureWithDescriptor:d];
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_unpromoted_metal'
            build = subprocess.run(
                [compiler, '-x', 'objective-c', '-framework', 'Metal', '-framework', 'Foundation',
                 '-', '-o', str(exe)],
                input=c_code, text=True, capture_output=True
            )
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            # Expect crash/assertion failure (non-zero exit code)
            self.assertNotEqual(run.returncode, 0, 'Unpromoted 1D depth texture should fail Metal assertion')
            self.assertIn('failed assertion', run.stderr)

    def test_metal_device_depth_promotion_execution(self):
        """On macOS, test that Metal accepts promoted 2D depth textures and view creation."""
        if platform.system() != 'Darwin':
            self.skipTest('Metal device tests only run on Darwin (macOS)')

        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang not available')

        c_code = r'''
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <assert.h>

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) {
            fprintf(stderr, "No Metal device\n");
            return 1;
        }

        // Test 1: Promoted 2D depth texture (1x1) succeeds
        MTLTextureDescriptor *d1 = [MTLTextureDescriptor new];
        d1.pixelFormat = MTLPixelFormatDepth32Float;
        d1.textureType = MTLTextureType2D;
        d1.width = 1;
        d1.height = 1;
        d1.depth = 1;
        d1.arrayLength = 1;
        d1.mipmapLevelCount = 1;
        d1.storageMode = MTLStorageModePrivate;
        d1.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;

        id<MTLTexture> t1 = [dev newTextureWithDescriptor:d1];
        if (!t1) {
            fprintf(stderr, "Failed to create promoted 2D depth texture\n");
            return 2;
        }

        // Test 2: View 2D on promoted 2D depth base succeeds
        id<MTLTexture> v1 = [t1 newTextureViewWithPixelFormat:MTLPixelFormatDepth32Float
                                                  textureType:MTLTextureType2D
                                                       levels:NSMakeRange(0, 1)
                                                       slices:NSMakeRange(0, 1)];
        if (!v1) {
            fprintf(stderr, "Failed to create view on promoted 2D depth texture\n");
            return 3;
        }

        // Test 3: Promoted 2DArray depth texture succeeds
        MTLTextureDescriptor *d2 = [MTLTextureDescriptor new];
        d2.pixelFormat = MTLPixelFormatDepth32Float;
        d2.textureType = MTLTextureType2DArray;
        d2.width = 1;
        d2.height = 1;
        d2.depth = 1;
        d2.arrayLength = 2;
        d2.mipmapLevelCount = 1;
        d2.storageMode = MTLStorageModePrivate;
        d2.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;

        id<MTLTexture> t2 = [dev newTextureWithDescriptor:d2];
        if (!t2) {
            fprintf(stderr, "Failed to create promoted 2DArray depth texture\n");
            return 4;
        }

        // Test 4: View 2DArray on promoted 2DArray depth base succeeds
        id<MTLTexture> v2 = [t2 newTextureViewWithPixelFormat:MTLPixelFormatDepth32Float
                                                  textureType:MTLTextureType2DArray
                                                       levels:NSMakeRange(0, 1)
                                                       slices:NSMakeRange(0, 2)];
        if (!v2) {
            fprintf(stderr, "Failed to create view on promoted 2DArray depth texture\n");
            return 5;
        }

        printf("PASS: Promoted depth textures and views valid on Metal\n");
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            exe = Path(tmpdir) / 'test_metal_exec'
            build = subprocess.run(
                [compiler, '-x', 'objective-c', '-framework', 'Metal', '-framework', 'Foundation',
                 '-', '-o', str(exe)],
                input=c_code, text=True, capture_output=True
            )
            self.assertEqual(build.returncode, 0, f'Compilation failed: {build.stderr}')
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, f'Runtime failed: {run.stderr}\n{run.stdout}')
            self.assertIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
