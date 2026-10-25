// Variable c1 adapted from nxnative (c) 2026 seedds, MIT; see ../../LICENSE.nxnative.
// 着色器反射 json（B：Switch 原版翻译，tools/dmsh_build.py 出）→ 定长 C 数组（nvn_refl.h）
// Shader reflection json (B: produced by translating the original Switch shaders, output of tools/dmsh_build.py) → fixed-length C arrays (nvn_refl.h)
#import "nvn_refl.h"
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

void nvn_refl_destroy(nvn_refl *r) { free(r->c1); r->c1 = NULL; r->c1_len = 0; r->has_c1 = 0; }

// 哑贴图类型：与原 dummy_tex 同一套前缀判定（未绑贴图槽按 D3D 语义读出 0）
// Dummy texture type: same prefix rules as the original dummy_tex (an unbound texture slot reads 0 per D3D semantics)
static void dummy_kind(NSString *t, uint8_t *tt, uint8_t *pf) {
    MTLTextureType y = MTLTextureType2D;
    if ([t hasPrefix:@"texture2d_array"] || [t hasPrefix:@"depth2d_array"]) y = MTLTextureType2DArray;
    else if ([t hasPrefix:@"texturecube_array"] || [t hasPrefix:@"depthcube_array"]) y = MTLTextureTypeCubeArray;
    else if ([t hasPrefix:@"texturecube"] || [t hasPrefix:@"depthcube"]) y = MTLTextureTypeCube;
    else if ([t hasPrefix:@"texture3d"]) y = MTLTextureType3D;
    else if ([t hasPrefix:@"texture1d_array"]) y = MTLTextureType1DArray;
    else if ([t hasPrefix:@"texture1d"]) y = MTLTextureType1D;
    *tt = (uint8_t)y;
    *pf = [t hasPrefix:@"depth"] ? NVN_DPF_DEPTH : [t containsString:@"<uint"] ? NVN_DPF_UINT : [t containsString:@"<int"] ? NVN_DPF_SINT : NVN_DPF_FLOAT;
}

/* TOTK 2026-10-16: the json's rw came from the translator's BufferUsageFlags tested with the wrong bit (& 2; Write is
   1 << 0), so every cached reflection says read-only -- while the deferred-lighting quads (dbe0acd9 ...) store per-tile
   feedback into the stats buffer. The loader (nvn_mtl.m refl_mark_stores) sets rw from the MSL's actual stores / atomics;
   here only the json flag and a write-access image type count. (A non-const `device` pointer is not enough: spirv-cross
   emits it for 1,140 fragment variants that never store, and treating them as writers disables argument-block reuse.) */
static int refl_rw(NSDictionary *b) {
    if ([b[@"rw"] isKindOfClass:[NSNumber class]] && [b[@"rw"] boolValue]) return 1;
    NSString *t = b[@"msl_type"]; if (![t isKindOfClass:[NSString class]]) return 0;
    return [t containsString:@"access::write"] || [t containsString:@"access::read_write"];
}
/* TXQ Maxwell sobre imagens: o shader consulta dimensões de imagem via handle imediato tcb na faixa de imagens.
   Faixa de imagens: [ImgBase, TexBase) = [0x120, 0x168) em bytes = palavras [0x48, 0x5a).
   Descritores de imagem têm 8 bytes = 2 palavras, logo (h - 0x48) deve ser par e slot = (h*4 - 0x120) / 8 = (h - 0x48) / 2.
   O fim da faixa em 0x5a é provado por TexBase = 0x168 (0x168 / 4 = 0x5a = 90). */
static int parse_tcb_image_handle(NSString *name, int is_sampler, int *out_slot) {
    if (!name) return 0;
    const char *s = name.UTF8String;
    const char *p = strstr(s, "_t_tcb_");
    if (!p || p == s) return 0;
    for (const char *q = s; q < p; q++) {
        if (*q < 'a' || *q > 'z') return 0;
    }
    p += 7; // após "_t_tcb_"
    char *end = NULL;
    unsigned long h = strtoul(p, &end, 16);
    if (end == p) return 0;
    if (is_sampler) {
        if (strcmp(end, "Smplr") != 0) return 0;
    } else {
        if (*end != '\0') return 0;
    }
    if (h >= 0x48 && h < 0x5a && (h % 2 == 0)) {
        if (out_slot) *out_slot = (int)((h - 0x48) / 2);
        return 1;
    }
    return 0;
}

/* FC26 2026-10-23: texture arrays the translator made from a bindless access (vendor/ryujinx BindlessToArray.RunPass: the
   shader loads a texture handle from c2 at a dynamic offset and samples with it; the array index is that byte offset / 8,
   clamped to the length). Element n is the texture whose handle sits at c2 byte 4 * o0 + 8 * n, o0 = low 14 bits of the
   handle in the name (<p>_t2d_cb<slots>_<hex>, TextureHandle.PackOffsets); every element of the sampler array is the second
   handle word's separate sampler (the json reg). The replay's c2 holds S.tex[r] at both 0x20 + 8 r (combined) and
   0x168 + 8 r (separate), so a byte offset names a texture slot; anything else reads 0 (empty slot, reg 0xffff).
   First seen in fragment shader b9764ae7 (Encontro Clássico, entering the match). */
static int msl_array_len(NSString *t, NSString **elem) {
    if (![t isKindOfClass:[NSString class]] || ![t hasPrefix:@"array<"]) return 0;
    NSRange c = [t rangeOfString:@", " options:NSBackwardsSearch];
    if (c.location == NSNotFound || ![t hasSuffix:@">"]) return 0;
    int n = [[t substringWithRange:NSMakeRange(c.location + 2, t.length - c.location - 3)] intValue];
    if (elem) *elem = [t substringWithRange:NSMakeRange(6, c.location - 6)];
    return n;
}
static unsigned c2_tex_slot(unsigned byte) {
    if (byte >= 0x20 && byte < 0x120 && (byte - 0x20) % 8 == 0) return (byte - 0x20) / 8;
    if (byte >= 0x168 && byte < 0x568 && (byte - 0x168) % 8 == 0) return (byte - 0x168) / 8;
    return 0xffff;
}
unsigned tex_array_elem_reg(const char *name, int n) {
    const char *p = name ? strstr(name, "_cb") : NULL;
    if (!p) return 0xffff;
    char *end = NULL; unsigned long slots = strtoul(p + 3, &end, 10);
    if (end == p + 3 || *end != '_' || (slots & 0xffff) != 2) return 0xffff;
    const char *h = end + 1; unsigned long handle = strtoul(h, &end, 16);
    if (end == h) return 0xffff;
    return c2_tex_slot((unsigned)(4 * (handle & 0x3fff) + 8 * (unsigned)n));
}

int drv_fillable(int stage, int bank, unsigned off) {
    if (bank == 2) return (off >= 0x20 && off < 0x120) || (off >= 0x168 && off < 0x968);
    switch (stage) {
    case 0: return (off >= 0x110 && off < 0x210) || off == 0x610 || (off >= 0x640 && off < 0x64c);   // FC26: + draw parameters
    case 1: return off >= 0x510 && off < 0x610;
    case 5: return off >= 0x200 && off < 0x410;
    default: return 0;
    }
}

int drv_access_components_fillable(int stage, int bank, unsigned long idx, const char *after) {
    unsigned base_off = (unsigned)idx * 16;
    if (after) {
        while (*after == ' ') after++;
    }
    if (after && *after == '.') {
        const char *c = after + 1;
        while (*c == ' ') c++;
        int found_comp = 0;
        while (*c == 'x' || *c == 'y' || *c == 'z' || *c == 'w') {
            found_comp = 1;
            unsigned comp_off = (*c == 'x' ? 0 : *c == 'y' ? 4 : *c == 'z' ? 8 : 12);
            if (!drv_fillable(stage, bank, base_off + comp_off))
                return 0;
            c++;
        }
        if (found_comp) return 1;
    }
    // Whole vec4 (no component swizzle)
    for (unsigned comp_off = 0; comp_off < 16; comp_off += 4) {
        if (!drv_fillable(stage, bank, base_off + comp_off))
            return 0;
    }
    return 1;
}

int msl_drv_unfillable_check(const char *msl, int stage, const char *entry) {
    if (!msl || !entry) return 0;
    if (strstr(entry, "dynamic") != NULL) return 0;
    if (entry[0] != 'c') return 0;
    int bank = entry[1] - '0';
    if (bank != 0 && bank != 2) return 0;
    const char *plus = strstr(entry, "+0x");
    if (!plus) return 0;
    char *end_off = NULL;
    unsigned long off = strtoul(plus + 3, &end_off, 16);
    if (end_off == plus + 3 || (off % 16) != 0) return 0;
    unsigned long target_idx = off / 16;

    int found_count = 0;
    for (const char *p = strstr(msl, "p_c"); p; p = strstr(p + 3, "p_c")) {
        if (p <= msl) continue;
        char prev = p[-1];
        if (prev != 'v' && prev != 'f' && prev != 'c') continue;
        if (p - 1 > msl) {
            char pprev = p[-2];
            if ((pprev >= 'a' && pprev <= 'z') || (pprev >= 'A' && pprev <= 'Z') || (pprev >= '0' && pprev <= '9') || pprev == '_')
                continue;
        }
        int b = p[3] - '0';
        if (b != bank || strncmp(p + 4, ")._m0[", 6) != 0) continue;
        const char *q = p + 10;
        while (*q == ' ') q++;
        char *end = NULL;
        unsigned long idx_read = strtoul(q, &end, 10);
        if (end == q) return 0; // dynamic index
        while (*end == ' ') end++;
        if (*end == 'u') { end++; while (*end == ' ') end++; }
        if (*end != ']') return 0; // dynamic index
        if (idx_read != target_idx) continue;
        found_count++;
        const char *after = end + 1;
        if (!drv_access_components_fillable(stage, bank, idx_read, after)) {
            return 0; // component out of range
        }
    }
    return found_count > 0;
}

int nvn_refl_from_json_msl(NSDictionary *j, NSString *msl, nvn_refl *o, char *err, int errlen) {
    memset(o, 0, sizeof *o);
    #define FAIL(...) do { snprintf(err, errlen, __VA_ARGS__); nvn_refl_destroy(o); return 1; } while (0)
    if (![j[@"route"] isEqual:@"B"]) FAIL("不是 B 反射（route ≠ B；A 路线 / PC 链反射已退役）");
    {   // Switch 原版翻译：种类与 NVN 槽号已由 dmsh_build.py 从 MSL 成员名解出 | Translated original Switch shaders: kind and NVN slot number are already parsed from the MSL member names by dmsh_build.py
        NSArray *bs = j[@"bindings"];
        if (![bs isKindOfClass:[NSArray class]]) FAIL("缺 bindings");
        if (bs.count > NVN_REFL_MAXB) FAIL("绑定 %lu 个，超上限 %d", (unsigned long)bs.count, NVN_REFL_MAXB);
        o->route_b = 1; o->abi = 0;   // spirv-cross 第 0 组 → [[buffer(0)]] | spirv-cross set 0 → [[buffer(0)]]
        int arr_at[NVN_REFL_MAXB], arr_len[NVN_REFL_MAXB], narr = 0, ntexarr = 0;
        for (NSDictionary *b in bs) {
            NSString *k = b[@"kind"]; nvn_rbind *r = &o->b[o->nb];
            id rg = b[@"reg"]; int reg = [rg isKindOfClass:[NSNumber class]] ? [rg intValue] : -1, aid = [b[@"arg_id"] intValue];
            NSString *elem = nil; int alen = msl_array_len(b[@"msl_type"], &elem);
            if (alen > 1 && [k isEqualToString:@"tex"]) {   // FC26: bindless texture array, element 0 here, the rest appended below
                r->aid = (uint16_t)aid; r->kind = NVN_RB_TEX; r->reg = (uint16_t)tex_array_elem_reg([b[@"msl_name"] UTF8String], 0);
                dummy_kind(elem, &r->dtt, &r->dpf);
                arr_at[narr] = o->nb; arr_len[narr++] = alen; ntexarr++; o->nb++;
                { static int warned; if (!warned++) fprintf(stderr, "[dm] [nvn-mtl] 【红】texture array from a bindless access (%s): the prebuilt totk_xlate clamps the index to the array length, so elements past the first may sample the wrong texture until it is rebuilt (needs .NET)\n", [b[@"msl_name"] UTF8String]); }
                continue;
            }
            if (alen > 1 && [k isEqualToString:@"samp"] && reg >= 0) {   // FC26: its sampler array, one separate sampler for every element
                r->aid = (uint16_t)aid; r->kind = NVN_RB_SAMP; r->reg = (uint16_t)reg;
                arr_at[narr] = o->nb; arr_len[narr++] = alen; o->nb++; continue;
            }
            if (alen > 1) FAIL("B 绑定 %s 是数组（%s），种类 %s 未实现", [b[@"msl_name"] UTF8String], [b[@"msl_type"] UTF8String], k.UTF8String);
            r->aid = (uint16_t)aid; r->reg = reg < 0 ? 0 : (uint16_t)reg;
            if ([k isEqualToString:@"cbuf"]) r->kind = NVN_RB_CBUF;
            else if ([k isEqualToString:@"samp"]) r->kind = NVN_RB_SAMP;
            else if ([k isEqualToString:@"samp_tex"]) {
                int img_slot = -1;
                if (reg < 0 && parse_tcb_image_handle(b[@"msl_name"], 1, &img_slot)) {
                    /* The sampler half of a size query on an image: no texture slot holds its handle, so reg 0xffff
                       (outside every slot table) binds the empty-slot sampler; the shader never samples with it. */
                    r->kind = NVN_RB_SAMPT;
                    r->reg = 0xffff;
                    reg = 0xffff;
                } else {
                    r->kind = NVN_RB_SAMPT;
                }
            }
            else if ([k isEqualToString:@"tex"]) {
                int img_slot = -1;
                if (reg < 0 && parse_tcb_image_handle(b[@"msl_name"], 0, &img_slot)) {
                    r->kind = NVN_RB_TEXIMG;
                    r->reg = (uint16_t)img_slot;
                    reg = img_slot;
                } else {
                    r->kind = NVN_RB_TEX;
                }
                dummy_kind(b[@"msl_type"], &r->dtt, &r->dpf);
            }
            else if ([k isEqualToString:@"img"]) { r->kind = NVN_RB_IMG; dummy_kind(b[@"msl_type"], &r->dtt, &r->dpf); r->rw = refl_rw(b); }
            else if ([k isEqualToString:@"tbuf"]) { r->kind = NVN_RB_TBUF; uint8_t tt; dummy_kind(b[@"msl_type"], &tt, &r->dpf); }
            else if ([k isEqualToString:@"sbuf"]) { r->kind = NVN_RB_SBUFP; r->rw = refl_rw(b); }
            else if ([k isEqualToString:@"ubo_ptr"]) r->kind = NVN_RB_UBOP;
            else if ([k isEqualToString:@"sbuf_ubo"]) { r->kind = NVN_RB_SBUFU; r->rw = refl_rw(b); r->off = (uint16_t)[b[@"off"] intValue]; }
            else if ([k isEqualToString:@"support"]) r->kind = NVN_RB_SUPPORT;
            else if ([k isEqualToString:@"c1"]) r->kind = NVN_RB_C1;
            else if ([k isEqualToString:@"drvcb"]) r->kind = [b[@"bank"] intValue] == 2 ? NVN_RB_DRV2 : NVN_RB_DRV0;
            else FAIL("B 绑定种类 %s 未实现（%s）", k.UTF8String, [b[@"msl_name"] UTF8String]);
            if ((r->kind == NVN_RB_CBUF || r->kind == NVN_RB_SAMP || r->kind == NVN_RB_SAMPT || r->kind == NVN_RB_TEX || r->kind == NVN_RB_IMG || r->kind == NVN_RB_TBUF || r->kind == NVN_RB_SBUFP || r->kind == NVN_RB_UBOP || r->kind == NVN_RB_SBUFU || r->kind == NVN_RB_TEXIMG) && reg < 0)
                FAIL("B 绑定 %s 没解出槽号", [b[@"msl_name"] UTF8String]);
            o->nb++;
        }
        o->nj = o->nb;   // json order 1:1 up to here; array elements 1.. follow
        for (int a = 0; a < narr; a++) {
            const nvn_rbind e0 = o->b[arr_at[a]];
            const char *name = [bs[(NSUInteger)arr_at[a]][@"msl_name"] UTF8String];
            for (int n = 1; n < arr_len[a]; n++) {
                if (o->nb >= NVN_REFL_MAXB) FAIL("绑定（含数组元素）超上限 %d", NVN_REFL_MAXB);
                nvn_rbind *r = &o->b[o->nb++]; *r = e0; r->aid = (uint16_t)(e0.aid + n);
                if (e0.kind == NVN_RB_TEX) r->reg = (uint16_t)tex_array_elem_reg(name, n);
            }
        }
        NSDictionary *dr = j[@"drv_reads"];
        if ([dr isKindOfClass:[NSDictionary class]]) { o->drv_read[0] = dr[@"0"] != nil; o->drv_read[2] = dr[@"2"] != nil; }
        NSArray *uf = j[@"drv_unfillable"];
        if ([uf isKindOfClass:[NSArray class]] && uf.count) {
            int stage = -1;
            NSString *st = j[@"stage"];
            if ([st isEqualToString:@"vs"]) stage = 0;
            else if ([st isEqualToString:@"ps"]) stage = 1;
            else if ([st isEqualToString:@"cs"]) stage = 5;

            NSMutableArray *unaccepted = [NSMutableArray array];
            for (id item in uf) {
                NSString *entry = [item description];
                if (ntexarr && [entry isEqualToString:@"c2 dynamic index"]) continue;   // FC26: the array's own handle load from c2 (see msl_array_len)
                if (!msl || stage < 0 || !msl_drv_unfillable_check(msl.UTF8String, stage, entry.UTF8String)) {
                    [unaccepted addObject:entry];
                }
            }
            if (unaccepted.count) {
                FAIL("运行时读驱动段的回放层填不了的位置：%s", [[unaccepted componentsJoinedByString:@" "] UTF8String]);
            }
        }
        NSString *c1 = j[@"c1"];
        if (c1.length % 2 || c1.length / 2 > UINT16_MAX) FAIL("c1 长 %lu 字节，超上限或不成对", (unsigned long)c1.length / 2);
        if (c1.length) { o->c1 = malloc(c1.length / 2); if (!o->c1) FAIL("c1 allocation failed"); o->has_c1 = 1; o->c1_len = (uint16_t)(c1.length / 2); for (unsigned i = 0; i < o->c1_len; i++) o->c1[i] = (uint8_t)strtoul([[c1 substringWithRange:NSMakeRange(2 * i, 2)] UTF8String], NULL, 16); }
        for (NSDictionary *v in j[@"vertex_inputs"]) {   // [[attribute(n)]]：n 即 NVN 顶点属性号 | [[attribute(n)]]: n is the NVN vertex attribute number
            int loc = [v[@"location"] intValue]; NSString *t = v[@"msl_type"];
            if (loc < 0 || loc >= NVN_REFL_MAXV || o->nv >= NVN_REFL_MAXV) FAIL("B 顶点输入 %d 越界", loc);
            o->v[o->nv].loc = o->v[o->nv].nvn = (uint8_t)loc;
            o->v[o->nv].ct = [t hasPrefix:@"uint"] ? NVN_CT_UINT : [t hasPrefix:@"int"] ? NVN_CT_INT : NVN_CT_FLOAT;
            o->nv++;
        }
        NSDictionary *ra = j[@"raster"];
        o->pos_attr = -1; o->may_discard = 1; o->writes_smask = 1;
        if ([ra isKindOfClass:[NSDictionary class]]) {
            if (ra[@"pos_attr"]) { int pa = [ra[@"pos_attr"] intValue]; o->pos_attr = (int8_t)(pa >= 0 && pa < 16 ? pa : -1); o->pos_w1 = [ra[@"pos_w"] isEqual:@"one"]; }
            if (ra[@"discard"]) o->may_discard = [ra[@"discard"] intValue] != 0;
            if (ra[@"sample_mask"]) o->writes_smask = [ra[@"sample_mask"] intValue] != 0;
            for (NSNumber *c in ra[@"colors"]) if (c.intValue >= 0 && c.intValue < 8) o->color_mask |= (uint8_t)(1u << c.intValue);
        }
        memset(o->uv_attr, -1, sizeof o->uv_attr); memset(o->uv_aff_attr, -1, sizeof o->uv_aff_attr);
        NSDictionary *ua = [ra isKindOfClass:[NSDictionary class]] ? ra[@"uv_affine"] : nil;
        if ([ua isKindOfClass:[NSDictionary class]]) for (NSString *k in ua) { int l = k.intValue; NSDictionary *e = ua[k]; int a = [e[@"attr"] intValue];
            if (l < 0 || l >= 32 || a < 0 || a >= 16) continue;
            NSArray *refs[4] = {e[@"sx"], e[@"ox"], e[@"sy"], e[@"oy"]}; int ok = 1;
            for (int q = 0; q < 4; q++) { NSArray *r = refs[q]; if (![r isKindOfClass:[NSArray class]] || r.count != 3) { ok = 0; break; }
                int sl = [r[0] intValue], vec = [r[1] intValue], cmp = [r[2] intValue]; if (sl < 0 || sl > 15 || vec < 0 || vec > 63 || cmp < 0 || cmp > 3) { ok = 0; break; }
                o->uv_aff[l][q] = (uint16_t)(sl << 8 | vec << 2 | cmp); }
            if (ok) o->uv_aff_attr[l] = (int8_t)a; }
        NSDictionary *uv = [ra isKindOfClass:[NSDictionary class]] ? ra[@"uv_from_attr"] : nil;
        if ([uv isKindOfClass:[NSDictionary class]]) for (NSString *k in uv) { int l = k.intValue, a = [uv[k] intValue]; if (l >= 0 && l < 32 && a >= 0 && a < 16) o->uv_attr[l] = (int8_t)a; }
        NSDictionary *fe = j[@"fetch"];
        if ([fe isKindOfClass:[NSDictionary class]]) {
            for (NSDictionary *c in fe[@"calls"]) { int i = [c[@"fc"] intValue], r = [c[@"tex_reg"] intValue], l = [c[@"varying_locn"] intValue];
                if (i != o->nfc || i >= 32 || r < 0 || r >= 128 || l < 0 || l >= 32) FAIL("fetch 调用表不连续或越界（第 %d 条）", i);
                o->fc_reg[o->nfc] = (uint8_t)r; o->fc_locn[o->nfc] = (uint8_t)l; o->nfc++; }
            for (NSNumber *r in fe[@"mixed_regs"]) if (r.intValue >= 0 && r.intValue < 128) o->fc_mixed[r.intValue >> 6] |= 1ull << (r.intValue & 63);
            for (NSDictionary *u in fe[@"outputs"]) { if (o->nfo >= 4) FAIL("fetch 输出超过 4 个"); o->fo_color[o->nfo++] = (uint8_t)[u[@"color"] intValue]; }
        }
        NSArray *tg = j[@"threadgroup_size"];
        if ([tg isKindOfClass:[NSArray class]] && tg.count == 3) for (int i = 0; i < 3; i++) o->tg[i] = (uint16_t)[tg[i] intValue];
        return 0;
    }
    #undef FAIL
}

int nvn_refl_from_json(NSDictionary *j, nvn_refl *o, char *err, int errlen) {
    return nvn_refl_from_json_msl(j, nil, o, err, errlen);
}
