"""Image slot over a texture with a channel swizzle (abort at 4 s, boot d3a, 2026-10-23).

The merged a0045c8 made an image-bound texture without ShaderWrite get a copy with ShaderWrite (tex_upgrade_shader_write).
The texture handed to it was the slot's sampling view; a view made with a swizzle has usage ShaderRead only (Metal strips
ShaderWrite), and the copy kept that swizzle: Metal aborted in -[MTLTextureDescriptorInternal validateWithDevice:]
"Texture swizzling is not compatable with MTLTextureUsageShaderWrite" (logs/boot_d3a.log, encode_args <- draw_inner).

Compiles the real desc_swizzle, tex_upgrade_shader_write and tex_image_view cut out of nvn_mtl.m, against the real Metal
device, with the replay-layer services they call stubbed. FC26_NVN_DIR points the test at another copy of the nvn sources.
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = Path(os.environ.get('FC26_NVN_DIR') or HERE / 'third_party/d2r_gfx/gfx/nvn')


def _cut(src, pattern, what):
    m = re.search(pattern, src, re.M | re.S)
    if not m:
        raise AssertionError(f'{what} not found in nvn_mtl.m')
    return m.group(0)


HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>
#define MLOG(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
static int g_red_once[256];
#define RED_ONCE(k, ...) do { if (!g_red_once[k]++) MLOG("RED " __VA_ARGS__); } while (0)
#define NVN_TEXTURE_FLAGS_IMAGE 0x40
typedef struct { struct { int format; uint32_t flags; } d; uint64_t serial; } tex_t;
typedef struct { uint64_t pf, type, w, h, z, levels, layers, samples, usage, storage; uint8_t swz[4]; } reup_key;
typedef struct { uint64_t a; } stor_key;
@interface NvPkg : NSObject { @public id<MTLTexture> tex; reup_key key; } @end
@implementation NvPkg @end
static id<MTLDevice> g_dev;
static int g_tex_preparing, g_tex_prepare_split;
static NSMapTable<id, id<MTLTexture>> *g_img_views;
static id g_holder; static int g_copies, g_bumps;
static int fmt_compressed(int f) { (void)f; return 0; }
static int fmt_depth(int f) { (void)f; return 0; }
static int rp_active(void) { return 0; }
static int stor_key_lookup(id o, stor_key *k) { (void)o; (void)k; return 0; }
static id<MTLTexture> stor_recreate(const stor_key *k, MTLTextureUsage u) { (void)k; (void)u; return nil; }
static id<MTLTexture> tex_mtl(const tex_t *t) { (void)t; return nil; }
static void res_add(id o) { (void)o; }
static id blit(void) { return nil; }
static void enc_b_copy_texture(id e, id<MTLTexture> s, NSUInteger sl, NSUInteger lv, MTLOrigin so, MTLSize z, id<MTLTexture> d, NSUInteger dl, NSUInteger dv, MTLOrigin doo) { g_copies++; }
static __unsafe_unretained id serial_get(uint64_t k) { (void)k; return g_holder; }
static void serial_put(uint64_t k, id o) { (void)k; g_holder = o; }
static void ser_bump(uint64_t s) { (void)s; g_bumps++; }
static void defer_obj_release(id o) { (void)o; }
static void defer_obj_unref(id o) { (void)o; }
%(FUNCS)s
static MTLTextureSwizzleChannels BGR1(void) { return MTLTextureSwizzleChannelsMake(MTLTextureSwizzleBlue, MTLTextureSwizzleGreen, MTLTextureSwizzleRed, MTLTextureSwizzleOne); }
static int is_default(MTLTextureSwizzleChannels s) { MTLTextureSwizzleChannels d = MTLTextureSwizzleChannelsDefault; return s.red == d.red && s.green == d.green && s.blue == d.blue && s.alpha == d.alpha; }
int main(int argc, const char **argv) { @autoreleasepool {
    g_dev = MTLCreateSystemDefaultDevice(); if (!g_dev) { printf("NODEV\n"); return 0; }
    const char *mode = argc > 1 ? argv[1] : "";
#ifdef HAVE_tex_upgrade_shader_write
    if (!strcmp(mode, "upgrade")) {
        /* a texture made for sampling with its swizzle in the descriptor (tex_desc without image use) */
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:8 mipmapped:YES];
        d.usage = MTLTextureUsageShaderRead; d.storageMode = MTLStorageModePrivate; d.swizzle = BGR1();
        id<MTLTexture> base = [g_dev newTextureWithDescriptor:d];
        NvPkg *pkg = [NvPkg new]; pkg->tex = base; g_holder = pkg;
        tex_t t = {{0x25, 0}, 7};
        id<MTLTexture> up = tex_upgrade_shader_write(&t, base);
        printf("UP write=%d default_swizzle=%d levels=%lu copies=%d holder_swapped=%d\n", (int)((up.usage & MTLTextureUsageShaderWrite) != 0),
               is_default(up.swizzle), (unsigned long)up.mipmapLevelCount, g_copies, (int)(pkg->tex == up));
        /* the sampling view still carries the swizzle (tex_by_id) */
        id<MTLTexture> sv = [up newTextureViewWithPixelFormat:up.pixelFormat textureType:up.textureType levels:NSMakeRange(0, up.mipmapLevelCount) slices:NSMakeRange(0, 1) swizzle:BGR1()];
        printf("SAMPLE_VIEW ok=%d\n", sv != nil);
    }
#endif
#ifdef HAVE_desc_swizzle
    if (!strcmp(mode, "rt")) {
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:4 height:4 mipmapped:NO];
        d.usage = MTLTextureUsageShaderRead; d.swizzle = BGR1();
        id<MTLTexture> base = [g_dev newTextureWithDescriptor:d];
        printf("KEEP=%d DROP_W=%d DROP_RT=%d\n", !is_default(desc_swizzle(base, MTLTextureUsageShaderRead | MTLTextureUsagePixelFormatView)),
               is_default(desc_swizzle(base, MTLTextureUsageShaderRead | MTLTextureUsageShaderWrite)), is_default(desc_swizzle(base, MTLTextureUsageRenderTarget)));
    }
#endif
#ifdef HAVE_tex_image_view
    if (!strcmp(mode, "view")) {
        /* a writable texture (made with image use) and its swizzled sampling view, level 1..2 of 4, as tex_by_id builds it */
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:16 height:16 mipmapped:YES];
        d.textureType = MTLTextureType2DArray; d.arrayLength = 3;
        d.usage = MTLTextureUsageShaderRead | MTLTextureUsageShaderWrite; d.storageMode = MTLStorageModePrivate;
        id<MTLTexture> base = [g_dev newTextureWithDescriptor:d];
        id<MTLTexture> sv = [base newTextureViewWithPixelFormat:base.pixelFormat textureType:MTLTextureType2DArray levels:NSMakeRange(1, 2) slices:NSMakeRange(1, 2) swizzle:BGR1()];
        id<MTLTexture> w = tex_image_view(sv), again = tex_image_view(sv);
        printf("SV write=%d\n", (int)((sv.usage & MTLTextureUsageShaderWrite) != 0));
        printf("IMG write=%d parent=%d level=%lu levels=%lu slice=%lu slices=%lu default_swizzle=%d cached=%d\n", (int)((w.usage & MTLTextureUsageShaderWrite) != 0),
               (int)(w.parentTexture == base), (unsigned long)w.parentRelativeLevel, (unsigned long)w.mipmapLevelCount, (unsigned long)w.parentRelativeSlice,
               (unsigned long)w.arrayLength, is_default(w.swizzle), (int)(w == again));
        /* a view of a texture that has no ShaderWrite is not made writable here (tex_upgrade_shader_write's job) */
        d.usage = MTLTextureUsageShaderRead;
        id<MTLTexture> ro = [g_dev newTextureWithDescriptor:d];
        id<MTLTexture> rv = [ro newTextureViewWithPixelFormat:ro.pixelFormat textureType:MTLTextureType2DArray levels:NSMakeRange(0, 1) slices:NSMakeRange(0, 1) swizzle:BGR1()];
        printf("RO nil=%d\n", tex_image_view(rv) == nil);
    }
#endif
    return 0;
} }
'''


@unittest.skipUnless(platform.system() == 'Darwin', 'needs Metal')
class NvnImageSwizzleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = shutil.which('clang')
        if not cls.cc:
            raise unittest.SkipTest('clang not available')
        src = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        cls.missing = {}
        funcs = []
        for name, ret in (('desc_swizzle', 'MTLTextureSwizzleChannels'), ('tex_upgrade_shader_write', 'id<MTLTexture>'), ('tex_image_view', 'id<MTLTexture>')):
            try:
                funcs.append(f'#define HAVE_{name} 1\n' + _cut(src, rf'^static {re.escape(ret)} {name}\(.*?\n}}\n', name))
            except AssertionError as e:
                cls.missing[name] = str(e)
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        (t / 'h.m').write_text(HARNESS.replace('%(FUNCS)s', '\n'.join(funcs)), encoding='utf-8')
        cls.exe = t / 'h'
        r = subprocess.run([cls.cc, '-fobjc-arc', '-w', '-framework', 'Foundation', '-framework', 'Metal', str(t / 'h.m'), '-o', str(cls.exe)],
                           capture_output=True, text=True)
        if r.returncode:
            raise AssertionError('harness does not compile:\n' + r.stderr[-3000:])

    def run_mode(self, mode, needs):
        if needs in self.missing:
            self.fail(self.missing[needs])
        r = subprocess.run([str(self.exe), mode], capture_output=True, text=True, timeout=60)
        if 'NODEV' in r.stdout:
            self.skipTest('no Metal device')
        self.assertEqual(r.returncode, 0, f'{mode} aborted (status {r.returncode}):\n{r.stderr[-2000:]}')
        return r.stdout

    def test_upgrade_of_swizzled_texture_gets_shader_write(self):
        out = self.run_mode('upgrade', 'tex_upgrade_shader_write')
        self.assertIn('UP write=1 default_swizzle=1 levels=4 copies=4 holder_swapped=1', out)
        self.assertIn('SAMPLE_VIEW ok=1', out)

    def test_desc_swizzle_drops_only_for_write_or_render_target(self):
        self.assertIn('KEEP=1 DROP_W=1 DROP_RT=1', self.run_mode('rt', 'desc_swizzle'))

    def test_swizzled_view_of_writable_texture_binds_a_plain_view(self):
        out = self.run_mode('view', 'tex_image_view')
        self.assertIn('SV write=0', out)   # what Metal does to a swizzled view: the reason the slot saw "no ShaderWrite"
        self.assertIn('IMG write=1 parent=1 level=1 levels=2 slice=1 slices=2 default_swizzle=1 cached=1', out)
        self.assertIn('RO nil=1', out)

    def test_encode_args_image_slot_uses_both(self):
        src = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        body = _cut(src, r'else if \(b->kind == NVN_RB_IMG\) \{.*?USE\(t, MTLResourceUsageRead \| MTLResourceUsageWrite\);', 'image slot in encode_args')
        self.assertIn('tex_upgrade_shader_write(&g_treg[tid].t, base)', body)   # the base, not the (swizzled) view
        self.assertIn('tex_image_view(t)', body)
        self.assertNotIn('g_treg[tid].view = (__bridge void *)up', body)   # the registered view is rebuilt, not overwritten unretained


if __name__ == '__main__':
    unittest.main()
