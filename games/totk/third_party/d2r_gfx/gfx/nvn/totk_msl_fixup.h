/* TOTK (Mac, 2026-10-20, issue #89 "far shadows flat / dark ground patches"): two Metal-vs-Maxwell differences in the
   translated shaders, patched in the MSL text just before it is compiled. The game and tools/warm_metal_cache.m both
   compile through this, so Metal's source-keyed cache sees one text.

   1. Shadow compare reference, D16 cascades. The game's cascaded shadow maps are Depth16Unorm arrays. Maxwell rounds the
      reference depth to the texture's precision before the compare; Metal compares the full float. Every lit surface then
      fails its own compare by a fraction of a 16-bit step: dark patches and streaks on walls and ground that move with
      the camera (the low-res shadow mask feeding the lighting pass showed Link's own silhouette and whole wall faces as
      shadowed). Rounding the reference to 1/65535 the way the depth write did restores the Switch picture. Only array
      compares are touched: in TOTK those are the D16 cascades; the 2D depth copies are D32F and never compare-sampled.
   2. Non-compare reads of a depth texture (the translator wraps them in totk_depth_fetch). The game binds a trilinear
      sampler, yet on the Switch the read lands on one texel. On Metal the linear sampler blends neighbouring depths, so
      the shadow test at object edges reconstructs positions in mid-air that are "in shadow": a dark halo around Link on
      the wall behind him. Point sampling matches the Switch. */
#pragma once
#import <Foundation/Foundation.h>

static NSString *totk_msl_fixup(NSString *src) {
    if (!src || [src containsString:@"totk_msl_fixup"]) return src;
    static NSRegularExpression *d16, *nearest; static dispatch_once_t once;
    dispatch_once(&once, ^{
        d16 = [NSRegularExpression regularExpressionWithPattern:
               @"(\\.sample_compare\\(spvDescriptorSet0\\.[A-Za-z0-9_]+Smplr, [^,]+\\.xy, uint\\(rint\\([^)]+\\)\\), )([^,]+)(, level)" options:0 error:nil];
        nearest = [NSRegularExpression regularExpressionWithPattern:
                   @"totk_depth_fetch\\((spvDescriptorSet0\\.[A-Za-z0-9_]+)\\.sample\\(spvDescriptorSet0\\.[A-Za-z0-9_]+Smplr, " options:0 error:nil];
    });
    NSMutableString *s = [src mutableCopy];
    NSUInteger n1 = [d16 replaceMatchesInString:s options:0 range:NSMakeRange(0, s.length) withTemplate:@"$1totk_d16ref($2)$3"];
    NSUInteger n2 = [nearest replaceMatchesInString:s options:0 range:NSMakeRange(0, s.length) withTemplate:@"totk_depth_fetch($1.sample(totk_nearest, "];
    if (!n1 && !n2) return src;
    NSRange ns = [s rangeOfString:@"using namespace metal;"];
    if (ns.location == NSNotFound) return src;
    NSString *helpers = @"using namespace metal;\n"
        "// totk_msl_fixup (totk_msl_fixup.h): D16 shadow compare reference rounded like the Switch; depth reads point-sampled\n"
        "static inline float totk_d16ref(float r) { return floor(fast::clamp(r, 0.0f, 1.0f) * 65535.0f + 0.5f) * (1.0f / 65535.0f); }\n"
        "constexpr sampler totk_nearest(filter::nearest, mip_filter::none, address::clamp_to_edge);\n";
    [s replaceCharactersInRange:ns withString:helpers];
    return s;
}
