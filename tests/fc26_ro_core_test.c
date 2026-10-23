/* games/fc26/runtime/ro/ro_core.c and ro_sha256.c on synthetic files (tests/fc26_synth.py, written by
   tests/test_fc26_ro_runtime.py into the directory given as argv[1], with the expected values in expect.txt). */
#include "ro_core.h"
#include "ro_sha256.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned failures;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #c); failures++; } } while (0)
#define CHECK_EQ(a, b) do { unsigned long long x_ = (unsigned long long)(a), y_ = (unsigned long long)(b); \
    if (x_ != y_) { fprintf(stderr, "%s:%d: %s = %#llx, expected %#llx\n", __FILE__, __LINE__, #a, x_, y_); failures++; } } while (0)

static const char *dir;
static uint8_t *load(const char *name, size_t *size) {
    char path[4096]; snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *p = calloc((size_t)n + 1, 1);
    if (!p || fread(p, 1, (size_t)n, f) != (size_t)n) exit(2);
    fclose(f); *size = (size_t)n; return p;
}
static unsigned long long expect(const char *key) {
    size_t n; char *text = (char *)load("expect.txt", &n), *line = text;
    for (; line && *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : NULL) {
        size_t k = strlen(key);
        if (!strncmp(line, key, k) && line[k] == ' ') { unsigned long long v = strtoull(line + k + 1, NULL, 0); free(text); return v; }
    }
    fprintf(stderr, "expect.txt has no %s\n", key); exit(2);
}
static int hexeq(const uint8_t d[32], const char *hex) { char h[65]; ro_hex(d, 32, h); return !strcmp(h, hex); }

static void sha256_vectors(void) {
    uint8_t d[32];
    ro_sha256("", 0, d); CHECK(hexeq(d, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
    ro_sha256("abc", 3, d); CHECK(hexeq(d, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    ro_sha256("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", 56, d);
    CHECK(hexeq(d, "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"));
    char *million = malloc(1000000); memset(million, 'a', 1000000);
    ro_sha256(million, 1000000, d); CHECK(hexeq(d, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"));
    static const size_t steps[] = {1, 55, 56, 63, 64, 65, 4096};
    for (unsigned s = 0; s < sizeof steps / sizeof *steps; s++) {   /* streaming in pieces gives the same digest */
        RoSha256 c; ro_sha256_init(&c);
        for (size_t at = 0; at < 1000000; at += steps[s]) ro_sha256_update(&c, million + at, at + steps[s] > 1000000 ? 1000000 - at : steps[s]);
        uint8_t e[32]; ro_sha256_final(&c, e); CHECK(!memcmp(d, e, 32));
    }
    free(million);
    uint8_t back[32]; char h[65]; ro_hex(d, 32, h);
    CHECK(!ro_unhex(h, 64, back, 32) && !memcmp(back, d, 32));
    CHECK(ro_unhex(h, 63, back, 32) && ro_unhex("zz", 2, back, 1));
}

static void nrr(const uint8_t nro_hash[32]) {
    size_t size; uint8_t *b = load("user.nrr", &size);
    RoNrr r;
    CHECK_EQ(ro_nrr_parse(b, size, &r), 0);
    CHECK_EQ(r.num_hashes, expect("nrr_hashes")); CHECK(r.sorted); CHECK_EQ(r.kind, RO_NRR_USER);
    CHECK(ro_nrr_has(r.hashes, r.num_hashes, nro_hash));
    uint8_t other[32]; memcpy(other, nro_hash, 32); other[31] ^= 1;
    CHECK(!ro_nrr_has(r.hashes, r.num_hashes, other));
    CHECK_EQ(ro_nrr_check(&r, expect("program_id"), RO_NRR_USER), 0);
    CHECK_EQ(ro_nrr_check(&r, expect("program_id") + 1, RO_NRR_USER), RO_INVALID_NRR);
    CHECK_EQ(ro_nrr_check(&r, expect("program_id"), RO_NRR_JIT_PLUGIN), RO_INVALID_NRR_KIND);
    CHECK_EQ(ro_nrr_check(&r, 0, -1), 0);
    CHECK_EQ(ro_nrr_parse(b, size + 0x1000, &r), RO_INVALID_SIZE);      /* header size differs from the buffer */
    uint8_t *copy = malloc(size);
    memcpy(copy, b, size); copy[3] = '1'; CHECK_EQ(ro_nrr_parse(copy, size, &r), RO_INVALID_NRR);
    memcpy(copy, b, size); memset(copy + 0x344, 0xff, 4); CHECK_EQ(ro_nrr_parse(copy, size, &r), RO_INVALID_NRR);
    memcpy(copy, b, size); memset(copy + 0x340, 0, 4); CHECK_EQ(ro_nrr_parse(copy, size, &r), RO_INVALID_NRR);
    free(copy); free(b);
    b = load("unsorted.nrr", &size);
    CHECK_EQ(ro_nrr_parse(b, size, &r), 0); CHECK(!r.sorted);
    free(b);
}

static void nro(const uint8_t *image, size_t size) {
    RoNro n;
    uint64_t nro_size = expect("nro_size"), bss = expect("bss_size");
    CHECK_EQ(size, nro_size);
    CHECK_EQ(ro_nro_parse(image, nro_size, bss, &n), 0);
    CHECK_EQ(n.text_size, expect("ro")); CHECK_EQ(n.ro_off, expect("ro")); CHECK_EQ(n.data_off, expect("data"));
    CHECK_EQ(n.bss_size, bss); CHECK_EQ(n.mod0, expect("mod0")); CHECK(!memcmp(n.module_id, image + 0x40, 32));
    CHECK_EQ(ro_nro_parse(image, nro_size, bss + 0x1000, &n), RO_INVALID_NRO);
    CHECK_EQ(ro_nro_parse(image, nro_size + 0x1000, bss, &n), RO_INVALID_NRO);
    uint8_t *copy = malloc(size);
    static const struct { unsigned offset; uint32_t value; } broken[] = {
        {0x10, 0x314f524e}, {0x1c, 2}, {0x28, 0x5000}, {0x38, 0x2010}, {0x4, 0x8000}, {0x24, 0x3000}};
    for (unsigned i = 0; i < sizeof broken / sizeof *broken; i++) {
        memcpy(copy, image, size); memcpy(copy + broken[i].offset, &broken[i].value, 4);
        uint64_t b = broken[i].offset == 0x38 ? 0x2010 : bss;
        CHECK_EQ(ro_nro_parse(copy, nro_size, b, &n), RO_INVALID_NRO);
    }
    free(copy);
}

static void layout_and_catalog(const uint8_t nro_hash[32], const RoNro *n, RoLayout *l) {
    char err[256]; size_t size;
    char *fixups = (char *)load("m.fixups.tsv", &size);
    CHECK_EQ(ro_fixups_parse(fixups, l, err, sizeof err), 0);
    uint8_t *patched = load("m.patched.bin", &size); free(patched);
    l->file_size = size;
    CHECK_EQ(ro_layout_check(l, n, err, sizeof err), 0);
    CHECK_EQ(l->key_off, expect("key_off")); CHECK_EQ(l->patch_off, expect("patch_off"));
    for (unsigned k = 0; k < RO_KEY_SLOTS; k++) CHECK_EQ(l->key_index[k], k);
    RoLayout bad;
    char *edited = malloc(strlen(fixups) + 64);
    strcpy(edited, fixups); *strstr(edited, "# PATCH_OFF") = '!';
    CHECK(ro_fixups_parse(edited, &bad, err, sizeof err) != 0);
    strcpy(edited, fixups); strstr(edited, "KEY_KTLS_IDX\t1")[13] = '5';
    CHECK(ro_fixups_parse(edited, &bad, err, sizeof err) != 0 && strstr(err, "KTLS"));
    bad = *l; bad.key_off += 0x4000; CHECK(ro_layout_check(&bad, n, err, sizeof err) != 0);
    bad = *l; bad.file_size = bad.patch_off - 4; CHECK(ro_layout_check(&bad, n, err, sizeof err) != 0);
    RoNro odd = *n; odd.text_size = odd.ro_off = 0x5000; odd.data_off = 0x6000; bad = *l; bad.text_end = bad.ro_off = 0x5000; bad.data_off = 0x6000;
    CHECK(ro_layout_check(&bad, &odd, err, sizeof err) != 0 && strstr(err, "share"));
    free(edited); free(fixups);

    char *gates_text = (char *)load("m.gates.tsv", &size);
    RoGate *gates; unsigned count;
    CHECK_EQ(ro_gates_parse(gates_text, l, &gates, &count, err, sizeof err), 0);
    CHECK_EQ(count, expect("gates"));
    for (unsigned i = 0; i < count; i++) CHECK(ro_gate_find(gates, count, gates[i].ret) == &gates[i]);
    CHECK(count && ro_gate_find(gates, count, gates[0].ret + 4) == NULL);
    unsigned svc = 0, timer = 0; for (unsigned i = 0; i < count; i++) { svc += !gates[i].timer; timer += gates[i].timer; }
    CHECK_EQ(svc, 1); CHECK_EQ(timer, 1);
    free(gates); free(gates_text);
    char line[160];
    /* unknown kind, timer into x18, return point outside the patch area, the same return point twice, a short row */
    static const char *const wrong[] = {"%#llx\tbrk\t1\t0x108\n", "%#llx\tcntpct\t18\t0x110\n", "0x10\tsvc\t1\t0x108\n",
                                        "%#llx\tsvc\t1\t0x108\n%#llx\tsvc\t2\t0x10c\n", "%#llx\tsvc\t1\n"};
    for (unsigned i = 0; i < sizeof wrong / sizeof *wrong; i++) {
        snprintf(line, sizeof line, wrong[i], (unsigned long long)l->patch_off, (unsigned long long)l->patch_off);
        CHECK(ro_gates_parse(line, l, &gates, &count, err, sizeof err) != 0);
    }

    char *manifest = (char *)load("nro_manifest.tsv", &size);
    RoImage image;
    CHECK_EQ(ro_catalog_find(manifest, nro_hash, &image, err, sizeof err), 1);
    CHECK(!strcmp(image.name, "m")); CHECK_EQ(image.nro_size, expect("nro_size")); CHECK_EQ(image.bss_size, expect("bss_size"));
    CHECK(!memcmp(image.module_id, n->module_id, 32));
    uint8_t other[32] = {0};
    CHECK_EQ(ro_catalog_find(manifest, other, &image, err, sizeof err), 0);
    char *twice = malloc(2 * strlen(manifest) + 1); strcpy(twice, manifest); strcat(twice, strchr(manifest, '\n') + 1);
    CHECK_EQ(ro_catalog_find(twice, nro_hash, &image, err, sizeof err), -1);
    size_t header = (size_t)(strchr(manifest, '\n') + 1 - manifest);
    for (unsigned m = 0; m < 3; m++) {   /* an extra field, a bad module name, a bad hex digit */
        strcpy(twice, manifest);
        char *row = twice + header;
        if (m == 0) { row[strlen(row) - 1] = 0; strcat(row, "\textra\n"); }
        if (m == 1) strchr(row, '\t')[1] = '/';
        if (m == 2) row[0] = 'x';
        CHECK_EQ(ro_catalog_find(twice, nro_hash, &image, err, sizeof err), -1);
    }
    free(twice); free(manifest);
}

static void plan_and_guest(const RoNro *n, const RoLayout *l) {
    RoRange r[6];
    unsigned count = ro_plan(l, r);
    uint64_t map = ro_map_size(l);
    CHECK_EQ(map % RO_HOST_PAGE, 0);
    uint64_t covered = 0;
    for (unsigned i = 0; i < count; i++) { CHECK_EQ(r[i].off, covered); covered += r[i].size; CHECK_EQ(r[i].off % RO_HOST_PAGE, 0); }
    CHECK_EQ(covered, map);
    CHECK_EQ(r[0].prot, RO_PROT_R | RO_PROT_X); CHECK_EQ(r[0].size, 0x4000);
    CHECK_EQ(r[1].prot, RO_PROT_R); CHECK_EQ(r[1].off, 0x4000);
    CHECK_EQ(r[2].prot, RO_PROT_R | RO_PROT_W); CHECK_EQ(r[2].off, expect("data")); CHECK_EQ(r[2].off + r[2].size, l->key_off);
    CHECK_EQ(r[3].prot, RO_PROT_R); CHECK_EQ(r[3].off, l->key_off); CHECK_EQ(r[3].size, RO_KEY_PAGE_SIZE);
    CHECK_EQ(r[count - 1].prot, RO_PROT_R | RO_PROT_X); CHECK_EQ(r[count - 1].off, l->patch_off);
    RoLayout odd = {.text_end = 0x5000, .ro_off = 0x5000, .data_off = 0xd000, .key_off = 0x14000, .patch_off = 0x20000, .file_size = 0x20040};
    count = ro_plan(&odd, r);   /* text rounded up, data rounded down, the gap before the patch area inaccessible */
    CHECK_EQ(count, 6); CHECK_EQ(r[0].size, 0x8000); CHECK_EQ(r[1].off, 0x8000); CHECK_EQ(r[1].size, 0x4000);
    CHECK_EQ(r[2].off, 0xc000); CHECK_EQ(r[2].size, 0x8000); CHECK_EQ(r[3].off, 0x14000);
    CHECK_EQ(r[4].prot, 0); CHECK_EQ(r[4].off, 0x18000); CHECK_EQ(r[4].size, 0x8000); CHECK_EQ(r[5].size, 0x4000);

    RoGuestMemory g; CHECK_EQ(ro_guest_init(&g, n, l), 0);
    uint64_t base, size, data = n->data_off, end = (uint64_t)n->size + n->bss_size, lo, hi; unsigned state, perm, attr;
    ro_guest_query(&g, 0x100, &base, &size, &state, &perm, &attr);
    CHECK_EQ(base, 0); CHECK_EQ(size, n->text_size); CHECK_EQ(state, RO_STATE_ALIAS_CODE); CHECK_EQ(perm, 5);
    ro_guest_query(&g, n->ro_off + 0x10, &base, &size, &state, &perm, &attr);
    CHECK_EQ(base, n->ro_off); CHECK_EQ(size, data - n->ro_off); CHECK_EQ(perm, 1); CHECK_EQ(state, RO_STATE_ALIAS_CODE);
    ro_guest_query(&g, end - 1, &base, &size, &state, &perm, &attr);
    CHECK_EQ(base, data); CHECK_EQ(size, end - data); CHECK_EQ(perm, 3); CHECK_EQ(state, RO_STATE_ALIAS_CODE_DATA); CHECK_EQ(attr, 0);
    CHECK_EQ(ro_guest_set_permission(&g, data, 0x1000, 1, &lo, &hi), 0);
    CHECK_EQ(lo, data & ~0x3fffULL); CHECK_EQ(hi, (data + 0x1000 + 0x3fff) & ~0x3fffULL);
    CHECK_EQ(ro_guest_host_prot(&g, lo), RO_PROT_R | RO_PROT_W);   /* the other three pages are still writable */
    ro_guest_query(&g, data, &base, &size, &state, &perm, &attr); CHECK_EQ(size, 0x1000); CHECK_EQ(perm, 1);
    CHECK_EQ(ro_guest_set_permission(&g, data, end - data, 1, &lo, &hi), 0);
    CHECK_EQ(ro_guest_host_prot(&g, data), RO_PROT_R);   /* all guest pages read-only: the host page follows (padding has none) */
    CHECK_EQ(ro_guest_set_permission(&g, data, end - data, 3, &lo, &hi), 0);
    CHECK_EQ(ro_guest_set_permission(&g, data + 1, 0x1000, 1, &lo, &hi), RO_SVC_INVALID_ADDRESS);
    CHECK_EQ(ro_guest_set_permission(&g, data, 0, 1, &lo, &hi), RO_SVC_INVALID_SIZE);
    CHECK_EQ(ro_guest_set_permission(&g, data, 0x1000, 2, &lo, &hi), RO_SVC_INVALID_PERMISSION);
    CHECK_EQ(ro_guest_set_permission(&g, 0, 0x1000, 1, &lo, &hi), RO_SVC_INVALID_MEMORY);          /* text */
    CHECK_EQ(ro_guest_set_permission(&g, data, end - data + 0x1000, 1, &lo, &hi), RO_SVC_INVALID_MEMORY);
    CHECK_EQ(ro_guest_lock(&g, data, 0x1000, RO_ATTR_PERMISSION_LOCKED, RO_ATTR_PERMISSION_LOCKED), 0);
    CHECK_EQ(ro_guest_lock(&g, data, 0x1000, 8, 8), RO_SVC_INVALID_PERMISSION);
    CHECK_EQ(ro_guest_set_permission(&g, data, 0x1000, 3, &lo, &hi), RO_SVC_INVALID_MEMORY);
    ro_guest_query(&g, data, &base, &size, &state, &perm, &attr); CHECK_EQ(attr, RO_ATTR_PERMISSION_LOCKED); CHECK_EQ(size, 0x1000);
    ro_guest_free(&g);
}

static uint64_t fake_import(const char *name) { uint64_t h = 0; for (; *name; name++) h = h * 31 + (uint8_t)*name; return 0x500000000000ULL | (h & 0xffffff) << 4; }
static void *resolve(void *ctx, const RoSymbol *s, uint64_t defined) {
    (void)ctx;
    if (s->defined) return (void *)(uintptr_t)defined;
    return strcmp(s->name, "weak_optional_hook") ? (void *)(uintptr_t)fake_import(s->name) : NULL;
}
static void *resolve_strict(void *ctx, const RoSymbol *s, uint64_t defined) {
    return strcmp(s->name, "__cxa_guard_acquire") ? resolve(ctx, s, defined) : NULL;
}
static int tlsdesc(void *ctx, const RoSymbol *s, int64_t addend, uint64_t pair[2]) {
    (void)ctx; pair[0] = 0x7d5c; pair[1] = (s->defined ? s->value : 0) + (uint64_t)addend; return 0;
}
static uint64_t word(const uint8_t *image, uint64_t at) { uint64_t v; memcpy(&v, image + at, 8); return v; }
static int count_kinds(void *ctx, const RoReloc *r) { unsigned *k = ctx; k[r->type == 1027 ? 0 : r->type == 257 ? 1 : r->type == 1025 ? 2 : r->type == 1026 ? 3 : r->type == 1031 ? 4 : 5]++; return 0; }

static void dynamic_and_link(const uint8_t *nro_bytes, const RoNro *n) {
    uint64_t size = (uint64_t)n->size + n->bss_size, base = 0x700000000000ULL;
    uint8_t *image = calloc(size, 1); memcpy(image, nro_bytes, n->size);
    char err[256]; RoDynamic d;
    CHECK_EQ(ro_dynamic_parse(image, size, &d, err, sizeof err), 0);
    CHECK_EQ(d.nsym, expect("nsym")); CHECK_EQ(d.init, expect("init")); CHECK_EQ(d.init_array, expect("init_array"));
    CHECK_EQ(ro_symbol_find(image, size, &d, "nro_export_fn"), expect("sym_nro_export_fn"));
    RoSymbol s; CHECK(!ro_symbol(image, size, &d, (uint32_t)expect("sym_nro_export_fn"), &s)); CHECK_EQ(s.value, expect("export_fn"));
    CHECK_EQ(ro_symbol_find(image, size, &d, "pthread_mutex_lock"), -1);   /* an import, not a definition */
    CHECK_EQ(ro_symbol_find(image, size, &d, "absent"), -1);
    unsigned kinds[6] = {0};
    CHECK_EQ(ro_relocs_each(image, size, &d, n->data_off, size, count_kinds, kinds, err, sizeof err), 0);
    CHECK_EQ(kinds[0], expect("relr")); CHECK_EQ(kinds[1], 2); CHECK_EQ(kinds[2], 2); CHECK_EQ(kinds[3], 2); CHECK_EQ(kinds[4], 2); CHECK_EQ(kinds[5], 0);
    CHECK(ro_relocs_each(image, size, &d, n->data_off + 0x400, size, count_kinds, kinds, err, sizeof err) != 0);

    RoLinker linker = {NULL, resolve, NULL};
    RoLinkStats st;
    uint8_t *work = malloc(size); memcpy(work, image, size);
    CHECK(ro_link(work, size, base, &d, n->data_off, size, &linker, &st, err, sizeof err) != 0);
    CHECK(strstr(err, "2 TLSDESC") && strstr(err, "(local)"));
    linker.tlsdesc = tlsdesc;
    memcpy(work, image, size);
    CHECK_EQ(ro_link(work, size, base, &d, n->data_off, size, &linker, &st, err, sizeof err), 0);
    CHECK_EQ(st.relative, expect("relr")); CHECK_EQ(st.symbolic, 6); CHECK_EQ(st.cross, 4); CHECK_EQ(st.weak_zero, 1); CHECK_EQ(st.tlsdesc, 2);
    CHECK_EQ(word(work, expect("init_array")), base + word(image, expect("init_array")));
    CHECK_EQ(word(work, expect("far")), base + word(image, expect("far")));
    CHECK_EQ(word(work, expect("g_abs_import")), fake_import("_ZTVN10__cxxabiv117__class_type_infoE") + 16);
    CHECK_EQ(word(work, expect("g_abs_local")), base + expect("export_data"));
    CHECK_EQ(word(work, expect("g_glob")), fake_import("_ZN2nn3mem17StandardAllocator8AllocateEm"));
    CHECK_EQ(word(work, expect("g_weak")), 0);
    CHECK_EQ(word(work, expect("g_jump0")), fake_import("pthread_mutex_lock"));
    CHECK_EQ(word(work, expect("g_tls_local")), 0x7d5c); CHECK_EQ(word(work, expect("g_tls_local") + 8), 0x10);
    CHECK_EQ(word(work, expect("g_tls_sym") + 8), expect("tls_value"));
    linker.resolve = resolve_strict; memcpy(work, image, size);
    CHECK(ro_link(work, size, base, &d, n->data_off, size, &linker, &st, err, sizeof err) != 0 && strstr(err, "unresolved __cxa_guard_acquire"));
    /* A RELA entry aimed at a slot RELR already relocates: refused, the base would be added twice. */
    linker.resolve = resolve; memcpy(work, image, size);
    uint64_t target = expect("init_array"); memcpy(work + d.rela, &target, 8);
    CHECK(ro_link(work, size, base, &d, n->data_off, size, &linker, &st, err, sizeof err) != 0 && strstr(err, "twice"));
    /* An unaligned RELA entry: refused with error */
    memcpy(work, image, size);
    uint64_t unaligned = expect("init_array") + 1; memcpy(work + d.rela, &unaligned, 8);
    CHECK(ro_link(work, size, base, &d, n->data_off, size, &linker, &st, err, sizeof err) != 0 && strstr(err, "outside data"));
    free(work); free(image);
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: %s <directory>\n", argv[0]); return 2; }
    dir = argv[1];
    sha256_vectors();
    size_t size; uint8_t *bytes = load("m.nro", &size), hash[32];
    ro_sha256(bytes, size, hash);
    nrr(hash);
    nro(bytes, size);
    RoNro n; ro_nro_parse(bytes, size, expect("bss_size"), &n);
    RoLayout l; layout_and_catalog(hash, &n, &l);
    plan_and_guest(&n, &l);
    dynamic_and_link(bytes, &n);
    free(bytes);
    if (failures) { fprintf(stderr, "%u checks failed\n", failures); return 1; }
    puts("ro core ok");
    return 0;
}
