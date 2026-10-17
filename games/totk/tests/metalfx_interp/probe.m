// MetalFX frame interpolation on this GPU with synthetic frames of known motion.
// Two frames (t = 0 and t = 1) of a panning, band-limited background and a square moving at another speed, plus depth
// and motion vectors; the interpolator's output is compared with the analytically rendered middle frame (t = 0.5).
// Checks: the motion-vector convention (units and sign) that MetalFX expects, input (depth / motion) smaller than the
// output as in TOTK (1600x900 scene, 1920x1080 colour), a static UI layer, an 8-bit colour format, the Metal 4 encoder,
// and the GPU time per interpolated frame. Negative controls: flipped motion, zero motion, wrong units.
// usage: build/metalfx-interp-probe   (exit 0 = all checks passed)
#import <Metal/Metal.h>
#import <MetalFX/MetalFX.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *kSrc =
"#include <metal_stdlib>\nusing namespace metal;\n"
"struct P { float t; float mvscale; float2 vbg; float2 s0; float2 w; float2 osz; uint2 out; uint2 in; uint ui; uint mvmode; float sign; float pad; };\n"
"static float3 bg(float2 u) {\n"
"  float3 c = 0.5 + 0.22 * float3(sin(u.x * 0.051) * cos(u.y * 0.047), sin(u.x * 0.023 + 1.3) * cos(u.y * 0.031 + 0.7), cos(u.x * 0.017 + u.y * 0.019));\n"
"  float k = 0.12 * tanh(3.0 * sin(u.x * 0.1309) * sin(u.y * 0.1309));\n"
"  return saturate(c + k);\n"
"}\n"
"static float3 obj(float2 l, float2 sz) {\n"
"  float2 q = l / sz; float r = length(q - 0.5);\n"
"  return saturate(float3(0.9 * q.x + 0.1, 0.3 + 0.5 * q.y, 0.6 + 0.3 * sin(r * 40.0)));\n"
"}\n"
"static bool in_obj(float2 p, constant P &c, float t) { float2 l = p - (c.s0 + c.w * t); return all(l >= 0.0) && all(l < c.osz); }\n"
"static float4 ui_at(float2 p) {\n"
"  if (p.x >= 100 && p.x < 400 && p.y >= 100 && p.y < 160) return float4(1, 1, 1, 1);\n"
"  if (p.x >= 1500 && p.x < 1850 && p.y >= 800 && p.y < 1000) return float4(0, 0, 0, 0.5);\n"
"  if (p.x >= 200 && p.x < 600 && p.y >= 880 && p.y < 980) return float4(1.0, 0.55, 0.1, 0.5);\n"
"  return float4(0);\n"
"}\n"
"static float3 scene_at(float2 p, constant P &c, float t) {\n"
"  float3 col = in_obj(p, c, t) ? obj(p - (c.s0 + c.w * t), c.osz) : bg(p + c.vbg * t);\n"
"  if (c.ui) { float4 u = ui_at(p); col = col * (1.0 - u.a) + u.rgb * u.a; }\n"
"  return col;\n"
"}\n"
// 4x4 supersampled colour keeps edges band-limited (both the inputs and the reference)
"kernel void scene(texture2d<float, access::write> o [[texture(0)]], constant P &c [[buffer(0)]], uint2 g [[thread_position_in_grid]]) {\n"
"  if (any(g >= c.out)) return; float3 s = 0;\n"
"  for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) s += scene_at(float2(g) + (float2(i, j) + 0.5) / 4.0, c, c.t);\n"
"  o.write(float4(s / 16.0, 1), g);\n"
"}\n"
// depth (not reversed: 0 near) and motion of the current frame (t = 1) at the input size; motion points to the
// pixel's position in the previous frame: background +vbg, object -w (output pixels)
"kernel void aux(device float *depth [[buffer(1)]], texture2d<float, access::write> mv [[texture(0)]], constant P &c [[buffer(0)]], uint2 g [[thread_position_in_grid]]) {\n"
"  if (any(g >= c.in)) return; float2 sc = float2(c.out) / float2(c.in); float2 p = (float2(g) + 0.5) * sc;\n"
"  bool o = in_obj(p, c, 1.0); float2 m = o ? -c.w : c.vbg;\n"
"  if (c.mvmode == 1) m /= sc;            // input pixels\n"
"  else if (c.mvmode == 2) m /= float2(c.out);   // normalised to [0,1] of the frame\n"
"  m *= c.sign;\n"
"  depth[g.y * c.in.x + g.x] = o ? 0.30 : 0.95;\n"
"  mv.write(float4(m, 0, 0), g);\n"
"}\n"
"kernel void ui(texture2d<float, access::write> o [[texture(0)]], constant P &c [[buffer(0)]], uint2 g [[thread_position_in_grid]]) {\n"
"  if (any(g >= c.out)) return; float4 s = 0;\n"
"  for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) s += ui_at(float2(g) + (float2(i, j) + 0.5) / 4.0);\n"
"  s /= 16.0; o.write(c.mvscale < 0 ? float4(s.rgb * s.a, s.a) : s, g);\n"   // mvscale < 0 here selects premultiplied UI
"}\n";

typedef struct { float t, mvscale; float vbg[2], s0[2], w[2], osz[2]; uint32_t out[2], in[2], ui, mvmode; float sign, pad; } P;

static id<MTLDevice> dev; static id<MTLCommandQueue> q; static id<MTLComputePipelineState> ps_scene, ps_aux, ps_ui;
static int failures;

static id<MTLTexture> tex(MTLPixelFormat f, NSUInteger w, NSUInteger h, MTLTextureUsage u, MTLStorageMode sm) {
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:f width:w height:h mipmapped:NO];
    d.usage = u; d.storageMode = sm; id<MTLTexture> t = [dev newTextureWithDescriptor:d];
    if (!t) { fprintf(stderr, "FAIL texture %lux%lu fmt %lu\n", (unsigned long)w, (unsigned long)h, (unsigned long)f); exit(2); }
    return t;
}
static void run(id<MTLComputePipelineState> ps, id<MTLTexture> t, id<MTLBuffer> b, const P *p, NSUInteger w, NSUInteger h) {
    id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
    [e setComputePipelineState:ps]; [e setTexture:t atIndex:0]; [e setBytes:p length:sizeof *p atIndex:0]; if (b) [e setBuffer:b offset:0 atIndex:1];
    [e dispatchThreads:MTLSizeMake(w, h, 1) threadsPerThreadgroup:MTLSizeMake(16, 16, 1)]; [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
    if (cb.error) { fprintf(stderr, "FAIL generator: %s\n", cb.error.description.UTF8String); exit(2); }
}
// colour texture -> float RGB on the CPU (through an RGBA32F copy made by a blit-compatible kernel would need another
// pipeline; read 16F / 8-bit directly instead)
static float srgb_dec(float c) { return c <= 0.04045f ? c / 12.92f : powf((c + 0.055f) / 1.055f, 2.4f); }
static float *readback(id<MTLTexture> t) {
    NSUInteger w = t.width, h = t.height, bpp = t.pixelFormat == MTLPixelFormatRGBA16Float ? 8 : 4; int srgb = t.pixelFormat == MTLPixelFormatRGBA8Unorm_sRGB;
    id<MTLBuffer> b = [dev newBufferWithLength:w * h * bpp options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLBlitCommandEncoder> e = [cb blitCommandEncoder];
    [e copyFromTexture:t sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(w, h, 1) toBuffer:b destinationOffset:0 destinationBytesPerRow:w * bpp destinationBytesPerImage:w * h * bpp];
    [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
    float *o = malloc(w * h * 3 * sizeof *o);
    for (NSUInteger i = 0; i < w * h; i++) for (int k = 0; k < 3; k++) {
        if (bpp == 8) { _Float16 v = ((const _Float16 *)b.contents)[i * 4 + k]; o[i * 3 + k] = (float)v; }
        else { float v = ((const uint8_t *)b.contents)[i * 4 + k] / 255.0f; o[i * 3 + k] = srgb ? srgb_dec(v) : v; }
    }
    return o;
}
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
// PROBE_PNG=<dir>: save the interpolated, reference and previous frames of the first scored step of each case
static void save_png(const float *rgb, int W, int H, const char *name, const char *what) {
    const char *dir = getenv("PROBE_PNG"); if (!dir) return;
    uint8_t *px = malloc((size_t)W * H * 4);
    for (int i = 0; i < W * H; i++) { for (int k = 0; k < 3; k++) { float v = rgb[i * 3 + k]; px[i * 4 + k] = (uint8_t)(fminf(fmaxf(v, 0), 1) * 255 + 0.5f); } px[i * 4 + 3] = 255; }
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(px, W, H, 8, (size_t)W * 4, cs, (CGBitmapInfo)kCGImageAlphaNoneSkipLast);
    CGImageRef img = CGBitmapContextCreateImage(ctx);
    char path[1024]; snprintf(path, sizeof path, "%s/%s-%s.png", dir, name, what);
    for (char *c = path + strlen(dir) + 1; *c; c++) if (*c == ' ' || *c == ',' || *c == ':') *c = '_';
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, (CFIndex)strlen(path), false);
    CGImageDestinationRef d = CGImageDestinationCreateWithURL(url, (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL);
    CGImageDestinationAddImage(d, img, NULL); CGImageDestinationFinalize(d);
    CFRelease(d); CFRelease(url); CGImageRelease(img); CGContextRelease(ctx); CGColorSpaceRelease(cs); free(px);
}
typedef struct { double all, bgd, objd, uid; } Score;
// PSNR (dB) over the frame interior (64 px border dropped: content enters there), split into background, the
// object's middle-frame rectangle grown by its per-frame motion (disocclusion), and the UI rectangles
static Score psnr(const float *a, const float *b, int W, int H, const P *p) {
    double se[4] = {0}; long n[4] = {0};
    for (int y = 64; y < H - 64; y++) for (int x = 64; x < W - 64; x++) {
        double e = 0; for (int k = 0; k < 3; k++) { double d = a[(y * W + x) * 3 + k] - b[(y * W + x) * 3 + k]; e += d * d; }
        float ox = p->s0[0] + p->w[0] * 0.5f, oy = p->s0[1] + p->w[1] * 0.5f; float gx = fabsf(p->w[0]) + 8, gy = fabsf(p->w[1]) + 8;
        int cls = (x >= ox - gx && x < ox + p->osz[0] + gx && y >= oy - gy && y < oy + p->osz[1] + gy) ? 2 : 1;
        if (p->ui && ((x >= 96 && x < 404 && y >= 96 && y < 164) || (x >= 1496 && x < 1854 && y >= 796 && y < 1004) || (x >= 196 && x < 604 && y >= 876 && y < 984))) cls = 3;
        se[0] += e; n[0] += 3; se[cls] += e; n[cls] += 3;
    }
    Score s; double *o[4] = {&s.all, &s.bgd, &s.objd, &s.uid};
    for (int i = 0; i < 4; i++) *o[i] = n[i] ? (se[i] ? 10 * log10(n[i] / se[i]) : 99) : -1;
    return s;
}
typedef struct { const char *name; MTLPixelFormat cf; int iw, ih, mvmode, ui, premul, mtl4; float sign, scale; int ow, oh, ui_separate; float vbx, vby; MTLPixelFormat of, uf; } Case;

/* One case = a sequence of frames t = 0..K-1 with the same motion. For each k >= 1 the interpolator gets frame k as
   colour, frame k-1 as previous colour and frame k's depth / motion; its output is scored against the analytic frame
   at t = k - 0.5. The interpolator keeps history, so the first calls are warm-up: scores are the mean over k >= 3. */
static Score run_case(const Case *c, double *gpu_ms, int K) {
    const int W = c->ow ? c->ow : 1920, H = c->oh ? c->oh : 1080;
    MTLFXFrameInterpolatorDescriptor *d = [MTLFXFrameInterpolatorDescriptor new];
    MTLPixelFormat of = c->of ? c->of : c->cf, uf = c->uf ? c->uf : MTLPixelFormatRGBA8Unorm;
    d.colorTextureFormat = c->cf; d.outputTextureFormat = of; d.depthTextureFormat = MTLPixelFormatDepth32Float; d.motionTextureFormat = MTLPixelFormatRG16Float;
    if (c->ui) d.uiTextureFormat = uf;
    d.inputWidth = c->iw; d.inputHeight = c->ih; d.outputWidth = W; d.outputHeight = H;
    id<MTLFXFrameInterpolator> fi = nil; id<MTL4FXFrameInterpolator> fi4 = nil; id<MTLFXFrameInterpolatorBase> base;
    if (c->mtl4) { NSError *e = nil; id<MTL4Compiler> comp = [dev newCompilerWithDescriptor:[MTL4CompilerDescriptor new] error:&e];
                   fi4 = comp ? [d newFrameInterpolatorWithDevice:dev compiler:comp] : nil; base = fi4; }
    else { fi = [d newFrameInterpolatorWithDevice:dev]; base = fi; }
    if (!base) { fprintf(stderr, "FAIL %s: interpolator not created\n", c->name); failures++; Score z = {-1, -1, -1, -1}; return z; }
    MTLTextureUsage gen = MTLTextureUsageShaderRead | MTLTextureUsageShaderWrite;
    id<MTLTexture> col[2] = {tex(c->cf, W, H, base.colorTextureUsage | gen, MTLStorageModePrivate), tex(c->cf, W, H, base.colorTextureUsage | gen, MTLStorageModePrivate)};
    id<MTLTexture> mid = tex(c->cf, W, H, gen, MTLStorageModePrivate), out = tex(of, W, H, base.outputTextureUsage | MTLTextureUsageShaderRead | MTLTextureUsagePixelFormatView, MTLStorageModePrivate);
    id<MTLTexture> depth = tex(MTLPixelFormatDepth32Float, c->iw, c->ih, base.depthTextureUsage | MTLTextureUsageShaderRead, MTLStorageModePrivate);
    id<MTLTexture> mv = tex(MTLPixelFormatRG16Float, c->iw, c->ih, base.motionTextureUsage | gen, MTLStorageModePrivate);
    id<MTLTexture> uit = c->ui ? tex(uf, W, H, base.uiTextureUsage | gen, MTLStorageModePrivate) : nil;
    id<MTLBuffer> db = [dev newBufferWithLength:(NSUInteger)c->iw * c->ih * 4 options:MTLResourceStorageModeShared];
    P p = {0}; p.vbg[0] = c->vbx ? c->vbx : 24; p.vbg[1] = c->vbx ? c->vby : 6; p.s0[0] = W * 0.55f; p.s0[1] = H * 0.30f; p.w[0] = -40; p.w[1] = 10; p.osz[0] = W * 0.135f; p.osz[1] = H * 0.185f;
    p.out[0] = W; p.out[1] = H; p.in[0] = c->iw; p.in[1] = c->ih; p.ui = c->ui; p.mvmode = c->mvmode; p.sign = c->sign; p.mvscale = c->premul ? -1 : 1;
    if (uit) run(ps_ui, uit, nil, &p, W, H);
    id<MTL4CommandQueue> q4 = nil; id<MTL4CommandAllocator> al = nil; id<MTL4CommandBuffer> cb4 = nil; id<MTLResidencySet> rs = nil;
    if (c->mtl4) {
        q4 = [dev newMTL4CommandQueue]; al = [dev newCommandAllocator]; cb4 = [dev newCommandBuffer];
        MTLResidencySetDescriptor *rd = [MTLResidencySetDescriptor new]; NSError *e = nil; rs = [dev newResidencySetWithDescriptor:rd error:&e];
        for (id<MTLAllocation> a in @[col[0], col[1], out, depth, mv]) [rs addAllocation:a];
        if (uit) [rs addAllocation:uit];
        [rs commit]; [q4 addResidencySet:rs];
    }
    double *times = calloc(K, sizeof *times); int nt = 0; Score sum = {0, 0, 0, 0}; int ns = 0; Score rp = {0, 0, 0, 0};
    p.ui = c->ui && !c->ui_separate; p.t = 0; run(ps_scene, col[0], nil, &p, W, H); p.ui = c->ui;
    for (int k = 1; k < K; k++) {
        id<MTLTexture> prev = col[(k - 1) & 1], cur = col[k & 1];
        p.ui = c->ui && !c->ui_separate; p.t = k; run(ps_scene, cur, nil, &p, W, H);
        p.ui = c->ui; p.t = k - 0.5f; run(ps_scene, mid, nil, &p, W, H);
        p.t = k; run(ps_aux, mv, db, &p, c->iw, c->ih);
        { id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLBlitCommandEncoder> e = [cb blitCommandEncoder];
          [e copyFromBuffer:db sourceOffset:0 sourceBytesPerRow:(NSUInteger)c->iw * 4 sourceBytesPerImage:(NSUInteger)c->iw * c->ih * 4 sourceSize:MTLSizeMake(c->iw, c->ih, 1) toTexture:depth destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0, 0, 0)];
          [e endEncoding]; [cb commit]; [cb waitUntilCompleted]; }
        base.colorTexture = cur; base.prevColorTexture = prev; base.depthTexture = depth; base.motionTexture = mv; base.outputTexture = out;
        base.motionVectorScaleX = c->scale; base.motionVectorScaleY = c->scale;
        base.deltaTime = 1.0f / 30; base.nearPlane = 0.1f; base.farPlane = 25000; base.fieldOfView = 50; base.aspectRatio = (float)W / H;
        base.depthReversed = NO; base.jitterOffsetX = 0; base.jitterOffsetY = 0; base.shouldResetHistory = k == 1;
        if (uit) { base.uiTexture = uit; base.uiTextureComposited = !c->ui_separate; }
        double ms = 0;
        if (c->mtl4) {
            __block double gs = 0, ge = 0; dispatch_semaphore_t sem = dispatch_semaphore_create(0);
            [al reset]; [cb4 beginCommandBufferWithAllocator:al]; [fi4 encodeToCommandBuffer:cb4]; [cb4 endCommandBuffer];
            MTL4CommitOptions *o = [MTL4CommitOptions new];
            [o addFeedbackHandler:^(id<MTL4CommitFeedback> f) { if (f.error) fprintf(stderr, "FAIL %s: %s\n", c->name, f.error.description.UTF8String); gs = f.GPUStartTime; ge = f.GPUEndTime; dispatch_semaphore_signal(sem); }];
            const id<MTL4CommandBuffer> list[1] = {cb4}; [q4 commit:list count:1 options:o];
            dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER); ms = (ge - gs) * 1e3;
        } else {
            id<MTLCommandBuffer> cb = [q commandBuffer]; [fi encodeToCommandBuffer:cb]; [cb commit]; [cb waitUntilCompleted];
            if (cb.error) { fprintf(stderr, "FAIL %s: %s\n", c->name, cb.error.description.UTF8String); failures++; }
            ms = (cb.GPUEndTime - cb.GPUStartTime) * 1e3;
        }
        if (k >= 3) times[nt++] = ms;
        if (k >= 3 && k < 8) {
            float *o = readback(out), *m = readback(mid), *a = readback(prev);
            Score s = psnr(o, m, W, H, &p), r = psnr(a, m, W, H, &p);
            if (k == 3) { save_png(o, W, H, c->name, "out"); save_png(m, W, H, c->name, "ref"); save_png(a, W, H, c->name, "prev"); }
            sum.all += s.all; sum.bgd += s.bgd; sum.objd += s.objd; sum.uid += s.uid; rp.all += r.all; ns++;
            free(o); free(m); free(a);
        }
    }
    if (ns) { sum.all /= ns; sum.bgd /= ns; sum.objd /= ns; sum.uid /= ns; rp.all /= ns; }
    for (int i = 1; i < nt; i++) { double v = times[i]; int j = i - 1; while (j >= 0 && times[j] > v) { times[j + 1] = times[j]; j--; } times[j + 1] = v; }
    if (gpu_ms) *gpu_ms = nt ? times[nt / 2] : -1;
    printf("%-36s psnr all %5.1f  bg %5.1f  obj %5.1f  ui %5.1f  (repeating the previous frame: %4.1f)  GPU median %.3f ms\n",
           c->name, sum.all, sum.bgd, sum.objd, c->ui ? sum.uid : -1, rp.all, nt ? times[nt / 2] : -1);
    free(times);
    return sum;
}
static void expect(int ok, const char *what) { printf("  %s %s\n", ok ? "ok  " : "FAIL", what); if (!ok) failures++; }

int main(void) {
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice(); q = [dev newCommandQueue];
        printf("device %s; frame interpolation %d, Metal 4 %d\n", dev.name.UTF8String, [MTLFXFrameInterpolatorDescriptor supportsDevice:dev], [MTLFXFrameInterpolatorDescriptor supportsMetal4FX:dev]);
        if (![MTLFXFrameInterpolatorDescriptor supportsDevice:dev]) { printf("FAIL no MetalFX frame interpolation on this device\n"); return 1; }
        NSError *e = nil; id<MTLLibrary> lib = [dev newLibraryWithSource:@(kSrc) options:nil error:&e];
        if (!lib) { fprintf(stderr, "FAIL compile: %s\n", e.description.UTF8String); return 2; }
        ps_scene = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"scene"] error:&e];
        ps_aux = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"aux"] error:&e];
        ps_ui = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"ui"] error:&e];
        if (!ps_scene || !ps_aux || !ps_ui) { fprintf(stderr, "FAIL pipelines: %s\n", e.description.UTF8String); return 2; }
        const MTLPixelFormat F16 = MTLPixelFormatRGBA16Float, U8 = MTLPixelFormatRGBA8Unorm;
        const int K = 8;
        Case base = {"full size, output px", F16, 1920, 1080, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0};
        Score s0 = run_case(&base, NULL, K);
        Case c;
        c = base; c.name = "neg: motion sign flipped"; c.sign = -1; Score sn1 = run_case(&c, NULL, K);
        c = base; c.name = "neg: zero motion"; c.sign = 0; Score sn2 = run_case(&c, NULL, K);
        c = base; c.name = "normalised motion, scale = size"; c.mvmode = 2; c.scale = 1920; run_case(&c, NULL, K);
        c = base; c.name = "in 1600x900, motion in input px"; c.iw = 1600; c.ih = 900; c.mvmode = 1; c.scale = 1; c.vbx = 96; c.vby = 24; Score si1 = run_case(&c, NULL, K);
        c = base; c.name = "in 1600x900, motion in output px"; c.iw = 1600; c.ih = 900; c.mvmode = 0; c.scale = 1; c.vbx = 96; c.vby = 24; Score si0 = run_case(&c, NULL, K);
        c = base; c.name = "in 1600x900, input px, sign flipped"; c.iw = 1600; c.ih = 900; c.mvmode = 1; c.scale = 1; c.vbx = 96; c.vby = 24; c.sign = -1; Score si1n = run_case(&c, NULL, K);
        c = base; c.name = "8-bit colour"; c.cf = U8; Score s8 = run_case(&c, NULL, K);
        c = base; c.name = "UI straight alpha, composited"; c.ui = 1; Score su = run_case(&c, NULL, K);
        c = base; c.name = "UI premultiplied, composited"; c.ui = 1; c.premul = 1; Score sup = run_case(&c, NULL, K);
        c = base; c.name = "UI straight, separate"; c.ui = 1; c.ui_separate = 1; Score sus = run_case(&c, NULL, K);
        c = base; c.name = "UI premultiplied, separate"; c.ui = 1; c.premul = 1; c.ui_separate = 1; Score sups = run_case(&c, NULL, K);
        c = base; c.name = "Metal 4 encoder"; c.mtl4 = 1; Score s4 = run_case(&c, NULL, K);
        // the game's set-up: scene and UI RGBA16F (linear, UI premultiplied), output RGBA8 sRGB, depth / motion 1600x900
        c = base; c.name = "game set-up (Metal 4)"; c.mtl4 = 1; c.ui = 1; c.premul = 1; c.ui_separate = 1; c.uf = F16; c.of = MTLPixelFormatRGBA8Unorm_sRGB;
        c.iw = 1600; c.ih = 900; c.mvmode = 1; Score sg = run_case(&c, NULL, K);
        printf("checks\n");
        expect(s0.all > 30 && s0.bgd > 32, "interpolated middle frame matches the reference (all > 30 dB, background > 32 dB)");
        // MetalFX refines the motion itself (zero motion still gives about 36 dB), so wrong vectors cost a few dB, not tens
        expect(sn1.bgd < s0.bgd - 2, "flipped motion is worse on the background (> 2 dB)");
        expect(sn2.bgd < s0.bgd - 2, "zero motion is worse on the background (> 2 dB)");
        int in_px = si1.all > si0.all;
        printf("  info motion units with a smaller input (96 px / frame pan): %s pixels (input px %.1f dB, output px %.1f dB, flipped %.1f dB)\n", in_px ? "input" : "output", si1.all, si0.all, si1n.all);
        expect(fabs(si1.all - si0.all) > 1, "the two unit conventions are distinguishable (> 1 dB apart)");
        expect(si1n.all < fmax(si1.all, si0.all) - 2, "large motion with the sign flipped is worse (> 2 dB)");
        expect((in_px ? si1.bgd : si0.bgd) > 30, "smaller depth / motion input still interpolates well (> 30 dB)");
        expect(s8.all > 28, "8-bit colour works (> 28 dB)");
        printf("  info UI mode \"composited\" (colour contains the UI) gives a black frame on this system; the UI must be given apart\n");
        printf("  info UI: composited straight %.1f / premultiplied %.1f dB, separate straight %.1f / premultiplied %.1f dB (whole frame %.1f / %.1f / %.1f / %.1f)\n",
               su.uid, sup.uid, sus.uid, sups.uid, su.all, sup.all, sus.all, sups.all);
        expect(fmax(sus.all, sups.all) > 30 && fmax(sus.uid, sups.uid) > 35, "UI given apart from the colour is overlaid (frame > 30 dB, UI > 35 dB)");
        expect(fabs(sus.uid - sups.uid) > 6, "straight and premultiplied UI are distinguishable (> 6 dB apart)");
        printf("  info MetalFX overlays a %s-alpha UI texture\n", sus.uid > sups.uid ? "straight" : "premultiplied");
        expect(s4.all > s0.all - 0.5 && s4.all > 30, "Metal 4 encoder gives the same result");
        expect(sg.all > 30 && sg.uid > 35, "game set-up: RGBA16F scene + premultiplied RGBA16F UI -> RGBA8 sRGB output (frame > 30 dB, UI > 35 dB)");
        printf("GPU time per interpolated frame (median), M4:\n");
        struct { const char *n; int ow, oh, iw, ih, mtl4; MTLPixelFormat f; } T[] = {
            {"1920x1080 out, 1600x900 in, 16F", 1920, 1080, 1600, 900, 0, F16}, {"same, Metal 4", 1920, 1080, 1600, 900, 1, F16},
            {"1920x1080 out, 1600x900 in, 8-bit", 1920, 1080, 1600, 900, 0, U8}, {"1920x1080 out, 960x540 in", 1920, 1080, 960, 540, 0, F16},
            {"1280x720 out, 1280x720 in", 1280, 720, 1280, 720, 0, F16}, {"1280x720 out, 640x360 in", 1280, 720, 640, 360, 0, F16},
            {"2560x1440 out, 1600x900 in", 2560, 1440, 1600, 900, 0, F16}};
        for (size_t i = 0; i < sizeof T / sizeof *T; i++) {
            Case t = base; t.name = T[i].n; t.ow = T[i].ow; t.oh = T[i].oh; t.iw = T[i].iw; t.ih = T[i].ih; t.mtl4 = T[i].mtl4; t.cf = T[i].f; t.mvmode = in_px ? 1 : 0;
            double ms = 0; run_case(&t, &ms, 40);
        }
        printf("%s (%d failures)\n", failures ? "FAILED" : "all checks passed", failures);
        return failures ? 1 : 0;
    }
}
