/* See ro_core.h. Plain C11, no host calls: the same file runs in the Mac runtime and in the Linux tests. */
#include "ro_core.h"
#include "ro_sha256.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }   /* guest and host are little endian */
static uint64_t rd64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
static uint64_t up(uint64_t x, uint64_t a) { return (x + a - 1) & ~(a - 1); }
static uint64_t down(uint64_t x, uint64_t a) { return x & ~(a - 1); }
static int fail(char *err, size_t errn, const char *format, ...) {
    va_list args; va_start(args, format);
    if (err && errn) vsnprintf(err, errn, format, args);
    va_end(args);
    return -1;
}
/* [off, off + n) inside [0, size) without overflow */
static int inside(uint64_t off, uint64_t n, uint64_t size) { return off <= size && n <= size - off; }

/* ---------- NRR ---------- */
uint32_t ro_nrr_parse(const uint8_t *nrr, uint64_t size, RoNrr *out) {
    memset(out, 0, sizeof *out);
    if (size < RO_NRR_HEADER_SIZE || memcmp(nrr, "NRR0", 4)) return RO_INVALID_NRR;
    out->program_id = rd64(nrr + 0x330); out->size = rd32(nrr + 0x338); out->kind = nrr[0x33c];
    out->hash_offset = rd32(nrr + 0x340); out->num_hashes = rd32(nrr + 0x344);
    if (out->size != size) return RO_INVALID_SIZE;
    if (out->hash_offset < RO_NRR_HEADER_SIZE || !inside(out->hash_offset, (uint64_t)out->num_hashes * 32, size)) return RO_INVALID_NRR;
    out->hashes = nrr + out->hash_offset;
    out->sorted = 1;
    for (uint32_t i = 1; i < out->num_hashes; i++) if (memcmp(out->hashes + 32 * (i - 1), out->hashes + 32 * i, 32) > 0) out->sorted = 0;
    return 0;
}

uint32_t ro_nrr_check(const RoNrr *nrr, uint64_t program_id, int kind) {
    if (program_id && nrr->program_id != program_id) return RO_INVALID_NRR;
    if (kind >= 0 && nrr->kind != (unsigned)kind) return RO_INVALID_NRR_KIND;
    return 0;
}

int ro_nrr_has(const uint8_t *hashes, uint32_t count, const uint8_t hash[32]) {
    uint32_t lo = 0, hi = count;   /* lower bound */
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (memcmp(hashes + 32 * (uint64_t)mid, hash, 32) < 0) lo = mid + 1; else hi = mid;
    }
    return lo < count && !memcmp(hashes + 32 * (uint64_t)lo, hash, 32);
}

/* ---------- NRO ---------- */
uint32_t ro_nro_parse(const uint8_t *nro, uint64_t nro_size, uint64_t bss_size, RoNro *out) {
    memset(out, 0, sizeof *out);
    if (nro_size < RO_NRO_HEADER_SIZE || memcmp(nro + 0x10, "NRO0", 4)) return RO_INVALID_NRO;
    uint32_t text_off = rd32(nro + 0x20);
    out->size = rd32(nro + 0x18); out->flags = rd32(nro + 0x1c);
    out->text_size = rd32(nro + 0x24); out->ro_off = rd32(nro + 0x28); out->ro_size = rd32(nro + 0x2c);
    out->data_off = rd32(nro + 0x30); out->data_size = rd32(nro + 0x34); out->bss_size = rd32(nro + 0x38);
    out->mod0 = rd32(nro + 4);
    memcpy(out->module_id, nro + 0x40, 32);
    if (out->flags & 2) return RO_INVALID_NRO;   /* [23.0.0+] compressed NRO: not supported here */
    if ((out->text_size | out->ro_size | out->data_size | out->bss_size) & (RO_GUEST_PAGE - 1)) return RO_INVALID_NRO;
    if (out->size != nro_size || out->bss_size != bss_size) return RO_INVALID_NRO;
    if (text_off || out->text_size != out->ro_off || (uint64_t)out->ro_off + out->ro_size != out->data_off ||
        (uint64_t)out->data_off + out->data_size != out->size) return RO_INVALID_NRO;
    if (out->mod0 < RO_NRO_HEADER_SIZE || !inside(out->mod0, RO_MOD0_SIZE, out->size) || memcmp(nro + out->mod0, "MOD0", 4)) return RO_INVALID_NRO;
    return 0;
}

/* ---------- Rewritten image ---------- */
static const char *const key_names[RO_KEY_SLOTS] = {"K18", "KTLS", "KTLR", "KGATE", "KRES0", "KRES1", "KASPECT", "KASPECTUI"};

int ro_fixups_parse(const char *text, RoLayout *out, char *err, size_t errn) {
    memset(out, 0, sizeof *out);
    for (unsigned i = 0; i < RO_KEY_SLOTS; i++) out->key_index[i] = -1;
    unsigned seen = 0;
    for (const char *line = text; *line;) {
        const char *end = strchr(line, '\n'); if (!end) end = line + strlen(line);
        char key[32]; unsigned long long value;
        if (*line == '#') {
            char row[96]; size_t n = (size_t)(end - line) < sizeof row - 1 ? (size_t)(end - line) : sizeof row - 1;
            memcpy(row, line, n); row[n] = 0;
            if (sscanf(row, "# %31s %lli", key, &value) != 2) return fail(err, errn, "fixups: unreadable line \"%s\"", row);
            static const char *const fields[] = {"PATCH_OFF", "KEY_PAGE_OFF", "TEXT_END", "RO_OFF", "DATA_OFF", "KEY_PAGE_SIZE"};
            uint64_t *slots[] = {&out->patch_off, &out->key_off, &out->text_end, &out->ro_off, &out->data_off, NULL};
            for (unsigned f = 0; f < 6; f++) if (!strcmp(key, fields[f])) {
                if (slots[f]) *slots[f] = value;
                else if (value != RO_KEY_PAGE_SIZE) return fail(err, errn, "fixups: key page size %#llx", value);
                seen |= 1u << f;
            }
            for (unsigned k = 0; k < RO_KEY_SLOTS; k++) {
                char name[32]; snprintf(name, sizeof name, "KEY_%s_IDX", key_names[k]);
                if (!strcmp(key, name)) out->key_index[k] = (int)value;
            }
        }
        line = *end ? end + 1 : end;
    }
    if ((seen & 31) != 31) return fail(err, errn, "fixups: PATCH_OFF, KEY_PAGE_OFF, TEXT_END, RO_OFF and DATA_OFF are all needed");
    /* The loader writes slot i's key at index i of the key page (loader.c map_module); the rewriter must agree. */
    for (unsigned k = 0; k < RO_KEY_SLOTS; k++)
        if ((k < 4 || out->key_index[k] >= 0) && out->key_index[k] != (int)k) return fail(err, errn, "fixups: KEY_%s_IDX is %d, expected %u", key_names[k], out->key_index[k], k);
    return 0;
}

int ro_layout_check(const RoLayout *l, const RoNro *nro, char *err, size_t errn) {
    uint64_t end = (uint64_t)nro->size + nro->bss_size;
    if (l->text_end != nro->text_size || l->ro_off != nro->ro_off || l->data_off != nro->data_off)
        return fail(err, errn, "rewritten layout text %#llx ro %#llx data %#llx, NRO header %#x %#x %#x", (unsigned long long)l->text_end,
                    (unsigned long long)l->ro_off, (unsigned long long)l->data_off, nro->text_size, nro->ro_off, nro->data_off);
    if (l->key_off != up(end, RO_HOST_PAGE) || l->patch_off != up(end + RO_KEY_PAGE_SIZE, 0x10000))
        return fail(err, errn, "key page %#llx / patch area %#llx are not where patch_nso.py puts them", (unsigned long long)l->key_off, (unsigned long long)l->patch_off);
    if (l->file_size < l->patch_off) return fail(err, errn, "rewritten image (%#llx bytes) ends before its patch area", (unsigned long long)l->file_size);
    if (up(l->text_end, RO_HOST_PAGE) > down(l->data_off, RO_HOST_PAGE)) return fail(err, errn, "text and data share a 16 KiB page");
    return 0;
}

static int gate_order(const void *a, const void *b) {
    const RoGate *x = a, *y = b; return x->ret < y->ret ? -1 : x->ret > y->ret;
}

int ro_gates_parse(const char *text, const RoLayout *l, RoGate **out, unsigned *count, char *err, size_t errn) {
    unsigned n = 0, cap = 0;
    for (const char *p = text; *p; p++) if (*p == '\n') cap++;
    RoGate *gates = calloc(cap + 1, sizeof *gates);
    if (!gates) return fail(err, errn, "gates: out of memory");
    for (const char *line = text; *line;) {
        const char *end = strchr(line, '\n'); if (!end) end = line + strlen(line);
        if (end > line) {
            char row[128], kind[16]; unsigned long long ret, original; unsigned arg;
            size_t len = (size_t)(end - line) < sizeof row - 1 ? (size_t)(end - line) : sizeof row - 1;
            memcpy(row, line, len); row[len] = 0;
            if (n == cap + 1 || sscanf(row, "%lli %15s %u %lli", &ret, kind, &arg, &original) != 4) { free(gates); return fail(err, errn, "gates: unreadable line \"%s\"", row); }
            unsigned timer = !strcmp(kind, "cntpct") || !strcmp(kind, "cntvct");
            if (!timer && strcmp(kind, "svc")) { free(gates); return fail(err, errn, "gates: unknown kind %s", kind); }
            if (timer && (arg >= 31 || arg == 18)) { free(gates); return fail(err, errn, "gates: timer target register x%u", arg); }
            if (ret < l->patch_off || ret >= l->file_size || original >= l->text_end) { free(gates); return fail(err, errn, "gates: %s outside the module", row); }
            gates[n++] = (RoGate){ret, original, timer, arg};
        }
        line = *end ? end + 1 : end;
    }
    qsort(gates, n, sizeof *gates, gate_order);
    for (unsigned i = 1; i < n; i++) if (gates[i].ret == gates[i - 1].ret) {
        unsigned long long twice = gates[i].ret;
        free(gates); return fail(err, errn, "gates: return point %#llx twice", twice);
    }
    *out = gates; *count = n;
    return 0;
}

const RoGate *ro_gate_find(const RoGate *gates, unsigned count, uint64_t ret_offset) {
    unsigned lo = 0, hi = count;
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        if (gates[mid].ret < ret_offset) lo = mid + 1; else hi = mid;
    }
    return lo < count && gates[lo].ret == ret_offset ? &gates[lo] : NULL;
}

int ro_catalog_each(const char *text, int (*visit)(void *ctx, const RoImage *row, unsigned line), void *ctx, char *err, size_t errn) {
    unsigned number = 0;
    for (const char *line = text; *line;) {
        const char *end = strchr(line, '\n'); if (!end) end = line + strlen(line);
        number++;
        if (end > line && *line != '#') {
            const char *field[6]; size_t len[6]; const char *p = line;
            for (unsigned f = 0; f < 6; f++) {
                const char *tab = f < 5 ? memchr(p, '\t', (size_t)(end - p)) : end;
                if (!tab || (f == 5 && memchr(p, '\t', (size_t)(end - p)))) return fail(err, errn, "manifest line %u: 6 tab-separated fields expected", number);
                field[f] = p; len[f] = (size_t)(tab - p); p = tab + 1;
            }
            RoImage row; memset(&row, 0, sizeof row);
            char number_text[24]; char *stop;
            if (ro_unhex(field[0], len[0], row.nro_sha256, 32) || ro_unhex(field[2], len[2], row.image_sha256, 32) ||
                ro_unhex(field[5], len[5], row.module_id, 32)) return fail(err, errn, "manifest line %u: bad hex field", number);
            if (!len[1] || len[1] >= sizeof row.name) return fail(err, errn, "manifest line %u: bad module name", number);
            for (size_t i = 0; i < len[1]; i++) {
                char c = field[1][i];
                if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-'))
                    return fail(err, errn, "manifest line %u: bad module name", number);
            }
            memcpy(row.name, field[1], len[1]);
            uint64_t *sizes[2] = {&row.nro_size, &row.bss_size};
            for (unsigned f = 0; f < 2; f++) {
                if (!len[3 + f] || len[3 + f] >= sizeof number_text) return fail(err, errn, "manifest line %u: bad size", number);
                memcpy(number_text, field[3 + f], len[3 + f]); number_text[len[3 + f]] = 0;
                *sizes[f] = strtoull(number_text, &stop, 10);
                if (*stop) return fail(err, errn, "manifest line %u: bad size", number);
            }
            int r = visit(ctx, &row, number);
            if (r) return r;
        }
        line = *end ? end + 1 : end;
    }
    return 0;
}

typedef struct { const uint8_t *sha256; RoImage *out; int found; unsigned twice; } CatalogFind;
static int catalog_match(void *ctx, const RoImage *row, unsigned line) {
    CatalogFind *f = ctx;
    if (memcmp(row->nro_sha256, f->sha256, 32)) return 0;
    if (f->found) { f->twice = line; return 2; }
    *f->out = *row; f->found = 1;
    return 0;
}

int ro_catalog_find(const char *text, const uint8_t nro_sha256[32], RoImage *out, char *err, size_t errn) {
    CatalogFind f = {nro_sha256, out, 0, 0};
    int r = ro_catalog_each(text, catalog_match, &f, err, errn);
    if (r == 2) return fail(err, errn, "manifest line %u: second row for the same NRO", f.twice);
    return r ? -1 : f.found;
}

/* ---------- Host pages ---------- */
uint64_t ro_map_size(const RoLayout *l) { return up(l->file_size, RO_HOST_PAGE); }

unsigned ro_plan(const RoLayout *l, RoRange out[6]) {
    uint64_t rx = up(l->text_end, RO_HOST_PAGE), rw = down(l->data_off, RO_HOST_PAGE), key_end = l->key_off + RO_KEY_PAGE_SIZE;
    uint64_t marks[7] = {0, rx, rw, l->key_off, key_end, l->patch_off, ro_map_size(l)};
    unsigned prots[6] = {RO_PROT_R | RO_PROT_X, RO_PROT_R, RO_PROT_R | RO_PROT_W, RO_PROT_R, 0, RO_PROT_R | RO_PROT_X}, n = 0;
    for (unsigned i = 0; i < 6; i++) if (marks[i + 1] > marks[i]) out[n++] = (RoRange){marks[i], marks[i + 1] - marks[i], prots[i]};
    return n;
}

/* ---------- Guest view ---------- */
int ro_guest_init(RoGuestMemory *g, const RoNro *nro, const RoLayout *l) {
    g->text_size = nro->text_size; g->data_off = nro->data_off; g->end = (uint64_t)nro->size + nro->bss_size; g->key_off = l->key_off;
    size_t pages = (size_t)(l->key_off / RO_GUEST_PAGE);
    g->page = malloc(pages ? pages : 1);
    if (!g->page) return -1;
    for (size_t p = 0; p < pages; p++) {
        uint64_t off = (uint64_t)p * RO_GUEST_PAGE;
        /* Pages past the bss up to the key page exist only on the host: no guest permission, so they never widen a
           shared 16 KiB page beyond what the guest asked for. */
        g->page[p] = off < g->text_size ? RO_PROT_R | RO_PROT_X : off < g->data_off ? RO_PROT_R : off < g->end ? RO_PROT_R | RO_PROT_W : 0;
    }
    return 0;
}

void ro_guest_free(RoGuestMemory *g) { free(g->page); g->page = NULL; }

static uint32_t guest_range(const RoGuestMemory *g, uint64_t off, uint64_t size) {
    if (off & (RO_GUEST_PAGE - 1)) return RO_SVC_INVALID_ADDRESS;
    if (!size || (size & (RO_GUEST_PAGE - 1))) return RO_SVC_INVALID_SIZE;
    if (off < g->data_off || off >= g->end || size > g->end - off) return RO_SVC_INVALID_MEMORY;
    return 0;
}

uint32_t ro_guest_set_permission(RoGuestMemory *g, uint64_t off, uint64_t size, unsigned perm, uint64_t *lo, uint64_t *hi) {
    uint32_t r = guest_range(g, off, size);
    if (r) return r;
    if (perm != 0 && perm != RO_PROT_R && perm != (RO_PROT_R | RO_PROT_W)) return RO_SVC_INVALID_PERMISSION;
    for (uint64_t p = off / RO_GUEST_PAGE; p < (off + size) / RO_GUEST_PAGE; p++) if (g->page[p] & RO_ATTR_PERMISSION_LOCKED) return RO_SVC_INVALID_MEMORY;
    memset(g->page + off / RO_GUEST_PAGE, (int)perm, (size_t)(size / RO_GUEST_PAGE));
    *lo = down(off, RO_HOST_PAGE); *hi = up(off + size, RO_HOST_PAGE);
    return 0;
}

uint32_t ro_guest_lock(RoGuestMemory *g, uint64_t off, uint64_t size, unsigned mask, unsigned attribute) {
    uint32_t r = guest_range(g, off, size);
    if (r) return r;
    if (mask != RO_ATTR_PERMISSION_LOCKED || attribute != RO_ATTR_PERMISSION_LOCKED) return RO_SVC_INVALID_PERMISSION;   /* the RELRO lock only, as loader.c */
    for (uint64_t p = off / RO_GUEST_PAGE; p < (off + size) / RO_GUEST_PAGE; p++) g->page[p] |= RO_ATTR_PERMISSION_LOCKED;
    return 0;
}

unsigned ro_guest_host_prot(const RoGuestMemory *g, uint64_t page_off) {
    unsigned combined = 0;
    for (uint64_t p = page_off / RO_GUEST_PAGE; p < (page_off + RO_HOST_PAGE) / RO_GUEST_PAGE && p < g->key_off / RO_GUEST_PAGE; p++) combined |= g->page[p] & 7;
    return combined;
}

void ro_guest_query(const RoGuestMemory *g, uint64_t off, uint64_t *base, uint64_t *size, unsigned *state, unsigned *perm, unsigned *attr) {
    uint64_t page = off / RO_GUEST_PAGE, data = g->data_off / RO_GUEST_PAGE, end = up(g->end, RO_GUEST_PAGE) / RO_GUEST_PAGE;
    int in_data = page >= data;
    uint64_t limit = in_data ? data : 0, top = in_data ? end : data, lo = page, hi = page + 1;
    while (lo > limit && g->page[lo - 1] == g->page[page]) lo--;
    while (hi < top && g->page[hi] == g->page[page]) hi++;
    *base = lo * RO_GUEST_PAGE; *size = (hi - lo) * RO_GUEST_PAGE;
    *state = in_data ? RO_STATE_ALIAS_CODE_DATA : RO_STATE_ALIAS_CODE;
    *perm = g->page[page] & 7; *attr = g->page[page] & RO_ATTR_PERMISSION_LOCKED;
}

/* ---------- ELF dynamic section ---------- */
int ro_dynamic_parse(const uint8_t *image, uint64_t size, RoDynamic *d, char *err, size_t errn) {
    memset(d, 0, sizeof *d);
    if (size < 8) return fail(err, errn, "image too small");
    d->mod0 = rd32(image + 4);
    if (!inside(d->mod0, RO_MOD0_SIZE, size) || memcmp(image + d->mod0, "MOD0", 4)) return fail(err, errn, "no MOD0");
    int64_t dynamic = (int64_t)d->mod0 + (int32_t)rd32(image + d->mod0 + 4);
    if (dynamic < 0) return fail(err, errn, "dynamic section before the module");
    d->dynamic = (uint64_t)dynamic;
    uint64_t relaent = 24, syment = 24, relrent = 8, pltrel = 7, at = d->dynamic;
    for (;; at += 16) {
        if (!inside(at, 16, size)) return fail(err, errn, "unterminated dynamic section");
        int64_t tag = (int64_t)rd64(image + at); uint64_t value = rd64(image + at + 8);
        if (!tag) break;
        switch (tag) {
        case 2: d->pltrelsz = value; break;   case 4: d->hash = value; break;      case 5: d->strtab = value; break;
        case 6: d->symtab = value; break;     case 7: d->rela = value; break;      case 8: d->relasz = value; break;
        case 9: relaent = value; break;       case 10: d->strsz = value; break;    case 11: syment = value; break;
        case 12: d->init = value; break;      case 13: d->fini = value; break;     case 20: pltrel = value; break;
        case 23: d->jmprel = value; break;    case 25: d->init_array = value; break; case 27: d->init_arraysz = value; break;
        case 35: d->relrsz = value; break;    case 36: d->relr = value; break;     case 37: relrent = value; break;
        default: break;
        }
    }
    if (relaent != 24 || syment != 24 || relrent != 8 || pltrel != 7) return fail(err, errn, "unexpected RELAENT / SYMENT / RELRENT / PLTREL");
    if (!d->hash || !inside(d->hash, 8, size)) return fail(err, errn, "no DT_HASH");
    uint32_t nbucket = rd32(image + d->hash);
    d->nsym = rd32(image + d->hash + 4);
    if (!inside(d->hash + 8, 4 * ((uint64_t)nbucket + d->nsym), size) || !nbucket) return fail(err, errn, "DT_HASH outside the image");
    if (!d->symtab || !inside(d->symtab, 24 * (uint64_t)d->nsym, size) || !d->strtab || !inside(d->strtab, d->strsz, size))
        return fail(err, errn, "symbol or string table outside the image");
    if ((d->relasz % 24) || (d->pltrelsz % 24) || (d->relrsz % 8) || !inside(d->rela, d->relasz, size) ||
        !inside(d->jmprel, d->pltrelsz, size) || !inside(d->relr, d->relrsz, size)) return fail(err, errn, "relocation table outside the image");
    return 0;
}

int ro_symbol(const uint8_t *image, uint64_t size, const RoDynamic *d, uint32_t index, RoSymbol *out) {
    (void)size;   /* ro_dynamic_parse bounded the tables */
    if (index >= d->nsym) return -1;
    const uint8_t *s = image + d->symtab + 24 * (uint64_t)index;
    uint32_t name = rd32(s);
    if (name >= d->strsz || !memchr(image + d->strtab + name, 0, d->strsz - name)) return -1;
    out->name = (const char *)image + d->strtab + name; out->type = s[4] & 15; out->binding = s[4] >> 4;
    out->defined = rd32(s + 4) >> 16 != 0; out->value = rd64(s + 8);
    return 0;
}

static uint32_t elf_hash(const char *name) {
    uint32_t h = 0;
    for (; *name; name++) { h = (h << 4) + (uint8_t)*name; uint32_t g = h & 0xf0000000u; if (g) h ^= g >> 24; h &= ~g; }
    return h;
}

long ro_symbol_find(const uint8_t *image, uint64_t size, const RoDynamic *d, const char *name) {
    uint32_t nbucket = rd32(image + d->hash);
    uint32_t i = rd32(image + d->hash + 8 + 4 * (uint64_t)(elf_hash(name) % nbucket));
    for (uint32_t steps = 0; i && i < d->nsym && steps < d->nsym; steps++) {
        RoSymbol s;
        if (!ro_symbol(image, size, d, i, &s) && s.defined && !strcmp(s.name, name)) return i;
        i = rd32(image + d->hash + 8 + 4 * ((uint64_t)nbucket + i));
    }
    return -1;
}

int ro_relocs_each(const uint8_t *image, uint64_t size, const RoDynamic *d, uint64_t lo, uint64_t hi,
                   int (*visit)(void *ctx, const RoReloc *r), void *ctx, char *err, size_t errn) {
    (void)size;
    uint64_t cursor = 0; int have = 0, r;
    /* RELR: an even entry is an address; an odd one is a bitmap of the 63 words after the last address or bitmap. */
    for (uint64_t at = d->relr; at < d->relr + d->relrsz; at += 8) {
        uint64_t entry = rd64(image + at), where[64]; unsigned n = 0;
        if (!(entry & 1)) { where[n++] = entry; cursor = entry + 8; have = 1; }
        else {
            if (!have) return fail(err, errn, "RELR bitmap before an address");
            for (unsigned bit = 1; bit < 64; bit++) if (entry >> bit & 1) where[n++] = cursor + 8 * (bit - 1);
            cursor += 63 * 8;
        }
        for (unsigned i = 0; i < n; i++) {
            if ((where[i] & 7) || where[i] < lo || where[i] > hi - 8) return fail(err, errn, "RELR relocation outside data: %#llx", (unsigned long long)where[i]);
            RoReloc reloc = {where[i], (int64_t)rd64(image + where[i]), 1027, 0};
            if ((r = visit(ctx, &reloc))) return r;
        }
    }
    const uint64_t tables[2][2] = {{d->rela, d->relasz}, {d->jmprel, d->pltrelsz}};
    for (unsigned t = 0; t < 2; t++)
        for (uint64_t at = tables[t][0]; at < tables[t][0] + tables[t][1]; at += 24) {
            uint64_t info = rd64(image + at + 8);
            RoReloc reloc = {rd64(image + at), (int64_t)rd64(image + at + 16), (uint32_t)info, (uint32_t)(info >> 32)};
            if ((reloc.where & 7) || reloc.where < lo || reloc.where > hi - 8) return fail(err, errn, "relocation outside data: %#llx", (unsigned long long)reloc.where);
            if (reloc.symbol >= d->nsym) return fail(err, errn, "relocation symbol %u of %u", reloc.symbol, d->nsym);
            if ((r = visit(ctx, &reloc))) return r;
        }
    return 0;
}

typedef struct {
    uint8_t *image; uint64_t size, base, lo, hi; const RoDynamic *d; const RoLinker *linker; RoLinkStats *stats;
    uint8_t *seen; unsigned tls_missing; const char *tls_first; char *err; size_t errn;
} LinkState;

/* Each 8-byte slot is relocated once: RELR adds the base to what is there, a second pass would add it again. */
static int claim(LinkState *s, uint64_t where) {
    uint64_t word = (where - s->lo) / 8;
    if (s->seen[word / 8] & (1u << (word % 8))) return fail(s->err, s->errn, "relocation at %#llx twice", (unsigned long long)where);
    s->seen[word / 8] |= (uint8_t)(1u << (word % 8));
    return 0;
}

static int link_one(void *ctx, const RoReloc *r) {
    LinkState *s = ctx;
    if (claim(s, r->where)) return -1;
    uint64_t value;
    if (r->type == 1027) {   /* R_AARCH64_RELATIVE */
        if (r->addend < 0 || (uint64_t)r->addend >= s->size) return fail(s->err, s->errn, "relative addend %#llx outside the module", (unsigned long long)r->addend);
        value = s->base + (uint64_t)r->addend; s->stats->relative++;
    } else if (r->type == 257 || r->type == 1025 || r->type == 1026 || r->type == 1031) {   /* ABS64, GLOB_DAT, JUMP_SLOT, TLSDESC */
        RoSymbol sym = {"", 0, 0, 0, 0};
        if ((r->symbol || r->type != 1031) && ro_symbol(s->image, s->size, s->d, r->symbol, &sym)) return fail(s->err, s->errn, "bad symbol %u", r->symbol);
        if (r->type == 1031) {
            uint64_t pair[2];
            if (!s->linker->tlsdesc) { if (!s->tls_missing++) s->tls_first = sym.name[0] ? sym.name : "(local)"; return 0; }
            if (r->where + 16 > s->hi || claim(s, r->where + 8)) return fail(s->err, s->errn, "TLSDESC pair at %#llx", (unsigned long long)r->where);
            if (s->linker->tlsdesc(s->linker->ctx, &sym, r->addend, pair))
                return fail(s->err, s->errn, "TLSDESC for %s not resolved", sym.name[0] ? sym.name : "(local)");
            memcpy(s->image + r->where, pair, 16); s->stats->tlsdesc++;
            return 0;
        }
        if (!r->symbol) return fail(s->err, s->errn, "symbolic relocation %u without a symbol at %#llx", r->type, (unsigned long long)r->where);
        void *p = s->linker->resolve(s->linker->ctx, &sym, sym.defined ? s->base + sym.value : 0);
        if (!p) {
            if (sym.binding != 2) return fail(s->err, s->errn, "unresolved %s", sym.name);
            value = 0; s->stats->weak_zero++;
        } else {
            if (!sym.defined) s->stats->cross++;
            value = (uint64_t)(uintptr_t)p + (r->type == 1026 ? 0 : (uint64_t)r->addend);   /* JUMP_SLOT as loader.c: the symbol */
        }
        s->stats->symbolic++;
    } else return fail(s->err, s->errn, "relocation type %u at %#llx not supported", r->type, (unsigned long long)r->where);
    memcpy(s->image + r->where, &value, 8);
    return 0;
}

int ro_link(uint8_t *image, uint64_t size, uint64_t base, const RoDynamic *d, uint64_t lo, uint64_t hi,
            const RoLinker *linker, RoLinkStats *stats, char *err, size_t errn) {
    memset(stats, 0, sizeof *stats);
    if (lo >= hi || hi > size || !linker->resolve) return fail(err, errn, "link range");
    LinkState s = {image, size, base, lo, hi, d, linker, stats, calloc((size_t)((hi - lo) / 64 + 1), 1), 0, NULL, err, errn};
    if (!s.seen) return fail(err, errn, "link: out of memory");
    int r = ro_relocs_each(image, size, d, lo, hi, link_one, &s, err, errn);
    free(s.seen);
    if (!r && s.tls_missing)
        return fail(err, errn, "%u TLSDESC relocations (first: %s) and no TLS model for modules yet", s.tls_missing, s.tls_first);
    return r;
}
