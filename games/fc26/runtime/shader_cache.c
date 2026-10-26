/* FC 26 shader cache layer: identity, journal, size limit (shader_cache.h; docs/SHADERS_NUVEM.md). Plain C over POSIX:
   no Foundation, no CommonCrypto, so tests/test_shader_cache.py runs it on Linux. */
#if !defined(__APPLE__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE   /* st_mtim, flock, utimensat with -std=c11 on Linux */
#endif
#include "shader_cache.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif
#ifdef __APPLE__
#define MTIME_NS(st) ((int64_t)(st).st_mtimespec.tv_sec * 1000000000 + (int64_t)(st).st_mtimespec.tv_nsec)
#else
#define MTIME_NS(st) ((int64_t)(st).st_mtim.tv_sec * 1000000000 + (int64_t)(st).st_mtim.tv_nsec)
#endif

/* ---------- SHA-256 ---------- */
static const uint32_t K256[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
static void sha256_block(uint32_t h[8], const uint8_t *p) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3), s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], k = h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 = k + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i];
        uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        k = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += k;
}
void fc26_sha256_init(fc26_sha256 *s) {
    static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(s->h, iv, sizeof iv); s->bytes = 0; s->used = 0;
}
void fc26_sha256_update(fc26_sha256 *s, const void *data, size_t n) {
    const uint8_t *p = data;
    s->bytes += n;
    if (s->used) {
        size_t take = 64 - s->used < n ? 64 - s->used : n;
        memcpy(s->buf + s->used, p, take); s->used += take; p += take; n -= take;
        if (s->used < 64) return;
        sha256_block(s->h, s->buf); s->used = 0;
    }
    for (; n >= 64; p += 64, n -= 64) sha256_block(s->h, p);
    memcpy(s->buf, p, n); s->used = n;
}
void fc26_sha256_final(fc26_sha256 *s, uint8_t out[32]) {
    uint64_t bits = s->bytes * 8;
    s->buf[s->used++] = 0x80;
    if (s->used > 56) { memset(s->buf + s->used, 0, 64 - s->used); sha256_block(s->h, s->buf); s->used = 0; }
    memset(s->buf + s->used, 0, 56 - s->used);
    for (int i = 0; i < 8; i++) s->buf[56 + i] = (uint8_t)(bits >> (56 - 8 * i));
    sha256_block(s->h, s->buf);
    for (int i = 0; i < 8; i++) { out[4 * i] = (uint8_t)(s->h[i] >> 24); out[4 * i + 1] = (uint8_t)(s->h[i] >> 16); out[4 * i + 2] = (uint8_t)(s->h[i] >> 8); out[4 * i + 3] = (uint8_t)s->h[i]; }
}
void fc26_hex(const uint8_t *p, size_t n, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) { out[2 * i] = digits[p[i] >> 4]; out[2 * i + 1] = digits[p[i] & 15]; }
    out[2 * n] = 0;
}
int fc26_sha256_file(const char *path, char hex[65]) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fc26_sha256 s; fc26_sha256_init(&s);
    uint8_t buf[1 << 16]; size_t got;
    while ((got = fread(buf, 1, sizeof buf, f))) fc26_sha256_update(&s, buf, got);
    int bad = ferror(f); fclose(f);
    if (bad) return -1;
    uint8_t md[32]; fc26_sha256_final(&s, md); fc26_hex(md, 32, hex);
    return 0;
}

/* ---------- keys and names ---------- */
static uint32_t u32_at(const uint8_t *p, size_t off) { uint32_t v; memcpy(&v, p + off, 4); return v; }
uint32_t fc26_sc_control_key_len(const uint8_t *control) {
    uint32_t n = u32_at(control, 0x20);
    return n >= 0x7cc && n < 0x880 ? n : 0x880;
}
int fc26_sc_shader_key(const uint8_t *control, const uint8_t *code, char key[65]) {
    uint32_t len = u32_at(control, 0x704);
    if (!len || len > FC26_SC_CODE_MAX) return -1;
    fc26_sha256 s; fc26_sha256_init(&s);
    uint32_t n = fc26_sc_control_key_len(control);   /* nvn_mtl.m ctl_key_update: without +0x7d0..+0x7e7 */
    fc26_sha256_update(&s, control, n < FC26_SC_KEY_SKIP_LO ? n : FC26_SC_KEY_SKIP_LO);
    if (n > FC26_SC_KEY_SKIP_HI) fc26_sha256_update(&s, control + FC26_SC_KEY_SKIP_HI, n - FC26_SC_KEY_SKIP_HI);
    fc26_sha256_update(&s, code, len);
    uint8_t md[32]; fc26_sha256_final(&s, md); fc26_hex(md, 32, key);
    return 0;
}
static int lower_hex(const char *s, size_t n) {
    for (size_t i = 0; i < n; i++) if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return 0;
    return 1;
}
int fc26_sc_is_key(const char *s) { return s && strlen(s) == 64 && lower_hex(s, 64); }
int fc26_sc_variant_key(const char *variant, char key[65]) {
    if (!variant || strlen(variant) != 77 || variant[64] != '-' || !lower_hex(variant, 64) || !lower_hex(variant + 65, 12)) return -1;
    memcpy(key, variant, 64); key[64] = 0;
    return 0;
}
int fc26_sc_shader_file(const char *name, char key[65]) {
    if (strlen(name) < 66 || !lower_hex(name, 64) || (name[64] != '.' && name[64] != '-')) return 0;
    if (key) { memcpy(key, name, 64); key[64] = 0; }
    return 1;
}

/* ---------- small file helpers ---------- */
static int join(char *out, const char *dir, const char *name) {
    int n = snprintf(out, PATH_MAX, "%s/%s", dir, name);
    return n > 0 && n < PATH_MAX ? 0 : -1;
}
static int regular(const char *path, struct stat *st) { return !lstat(path, st) && S_ISREG(st->st_mode); }
/* Whole file into memory (at most max bytes); NULL on failure. */
static uint8_t *read_all(const char *path, size_t max, size_t *len) {
    struct stat st; FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fstat(fileno(f), &st) || st.st_size < 0 || (uint64_t)st.st_size > max) { fclose(f); errno = EFBIG; return NULL; }
    uint8_t *p = malloc((size_t)st.st_size + 1);
    if (!p) { fclose(f); errno = ENOMEM; return NULL; }
    size_t got = fread(p, 1, (size_t)st.st_size, f); fclose(f);
    if (got != (size_t)st.st_size) { free(p); errno = EIO; return NULL; }
    p[got] = 0; *len = got;
    return p;
}
/* Written under a temporary name and renamed: a reader sees the old file or the whole new one. */
static _Atomic uint64_t g_tmp_seq;
static int write_atomic(const char *path, const void *a, size_t na, const void *b, size_t nb, const void *c, size_t nc) {
    char tmp[PATH_MAX];
    int n = snprintf(tmp, sizeof tmp, "%s.tmp.%ld.%llu", path, (long)getpid(), (unsigned long long)atomic_fetch_add(&g_tmp_seq, 1));
    if (n <= 0 || n >= (int)sizeof tmp) return -1;
    FILE *f = fopen(tmp, "wb");
    if (!f) return -1;
    int ok = fwrite(a, 1, na, f) == na && (!nb || fwrite(b, 1, nb, f) == nb) && (!nc || fwrite(c, 1, nc, f) == nc);
    ok = !fclose(f) && ok;
    if (!ok || rename(tmp, path)) { unlink(tmp); return -1; }
    return 0;
}
static int ensure_dir(const char *dir) { return !mkdir(dir, 0755) || errno == EEXIST ? 0 : -1; }

/* ---------- identity ---------- */
#define ID_MAGIC "fc26-shader-cache-identity"
static int one_line(const char *v) { return v && *v && !strpbrk(v, "\r\n"); }
int fc26_sc_identity_write(const char *path, const fc26_sc_identity *id) {
    if (!one_line(id->chain) || !one_line(id->translator) || !one_line(id->spirv_cross) || !one_line(id->request) || !one_line(id->debug_mode))
        return -1;
    char text[1024];
    int n = snprintf(text, sizeof text, ID_MAGIC " %d\nchain %s\ntranslator %s\nspirv_cross %s\nrequest %s\ndebug_mode %s\ndepth_minus_w %d\n",
                     id->schema, id->chain, id->translator, id->spirv_cross, id->request, id->debug_mode, id->depth_minus_w ? 1 : 0);
    if (n <= 0 || n >= (int)sizeof text) return -1;
    return write_atomic(path, text, (size_t)n, NULL, 0, NULL, 0);
}
static int field(char *dst, size_t cap, const char *value) {
    size_t n = strlen(value);
    if (!n || n >= cap) return -1;
    memcpy(dst, value, n + 1);
    return 0;
}
int fc26_sc_identity_read(const char *path, fc26_sc_identity *id) {
    size_t len; char *text = (char *)read_all(path, 4096, &len);
    if (!text) return errno == ENOENT ? -1 : -2;
    memset(id, 0, sizeof *id);
    int seen = 0, bad = 0, line_no = 0;
    for (char *save = NULL, *line = strtok_r(text, "\n", &save); line && !bad; line = strtok_r(NULL, "\n", &save), line_no++) {
        char *sp = strchr(line, ' ');
        if (!sp) { bad = 1; break; }
        *sp = 0; const char *name = line, *value = sp + 1;
        if (line_no == 0) {
            char *end; long schema = strtol(value, &end, 10);
            if (strcmp(name, ID_MAGIC) || *end || end == value || schema <= 0 || schema > 1000) bad = 1; else id->schema = (int)schema;
            continue;
        }
        if (!strcmp(name, "chain")) { bad = field(id->chain, sizeof id->chain, value); seen |= 1; }
        else if (!strcmp(name, "translator")) { bad = field(id->translator, sizeof id->translator, value); seen |= 2; }
        else if (!strcmp(name, "spirv_cross")) { bad = field(id->spirv_cross, sizeof id->spirv_cross, value); seen |= 4; }
        else if (!strcmp(name, "request")) { bad = field(id->request, sizeof id->request, value); seen |= 8; }
        else if (!strcmp(name, "debug_mode")) { bad = field(id->debug_mode, sizeof id->debug_mode, value); seen |= 16; }
        else if (!strcmp(name, "depth_minus_w")) { if (strcmp(value, "0") && strcmp(value, "1")) bad = 1; id->depth_minus_w = value[0] == '1'; seen |= 32; }
        else bad = 1;
    }
    free(text);
    return !bad && line_no > 0 && seen == 63 ? 0 : -2;
}
const char *fc26_sc_identity_diff(const fc26_sc_identity *a, const fc26_sc_identity *b) {
    if (a->schema != b->schema) return "schema";
    if (strcmp(a->chain, b->chain)) return "chain";
    if (strcmp(a->translator, b->translator)) return "translator";
    if (strcmp(a->spirv_cross, b->spirv_cross)) return "spirv_cross";
    if (strcmp(a->request, b->request)) return "request";
    if (strcmp(a->debug_mode, b->debug_mode)) return "debug_mode";
    if (!a->depth_minus_w != !b->depth_minus_w) return "depth_minus_w";
    return NULL;
}

/* ---------- discarding ---------- */
long fc26_sc_discard(const char *cache_dir) {
    DIR *d = opendir(cache_dir);
    if (!d) return -1;
    long removed = 0; struct dirent *e; char path[PATH_MAX]; struct stat st;
    while ((e = readdir(d))) {
        if (!fc26_sc_shader_file(e->d_name, NULL) && strcmp(e->d_name, "seed-installed.json")) continue;
        if (join(path, cache_dir, e->d_name) || !regular(path, &st)) continue;
        if (!unlink(path)) removed++;
    }
    closedir(d);
    return removed;
}
static int try_lock_path(const char *dir) {
    char path[PATH_MAX];
    if (join(path, dir, FC26_SC_LOCK_FILE)) return -1;
    int fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0) return -1;
    if (flock(fd, LOCK_EX | LOCK_NB)) { close(fd); return -1; }
    return fd;
}
int fc26_sc_remove_old_chains(const char *parent, const char *current_name, const char *current_chain) {
    DIR *d = opendir(parent);
    if (!d) return 0;
    int removed = 0; struct dirent *e; char dir[PATH_MAX], path[PATH_MAX]; struct stat st;
    while ((e = readdir(d))) {
        if (strncmp(e->d_name, "rt-", 3) || !strcmp(e->d_name, current_name)) continue;
        if (join(dir, parent, e->d_name) || lstat(dir, &st) || !S_ISDIR(st.st_mode)) continue;
        if (join(path, dir, FC26_SC_ID_FILE) || !regular(path, &st)) continue;   /* not ours: left alone */
        fc26_sc_identity other;   /* only another chain is older; the same chain under another name is a parallel cache */
        if (fc26_sc_identity_read(path, &other) || !current_chain || !strcmp(other.chain, current_chain)) continue;
        int fd = try_lock_path(dir);
        if (fd < 0) continue;   /* a run is using it */
        fc26_sc_discard(dir);
        static const char *const ours[] = {FC26_SC_ID_FILE, "pso_collected.tsv", FC26_SC_LOCK_FILE};
        for (size_t i = 0; i < sizeof ours / sizeof *ours; i++) if (!join(path, dir, ours[i])) unlink(path);
        close(fd);
        if (!rmdir(dir)) removed++;
    }
    closedir(d);
    return removed;
}

/* ---------- journal ---------- */
#define SHADER_MAGIC "FC26SHD1"
enum { SHADER_HEADER = 24, SHADER_FORMAT = 1 };
static int check_shader(int stage, uint32_t code_len, uint32_t c1_off) {
    if (stage != 0 && stage != 1 && stage != 5) return -1;                      /* vertex, fragment, compute (totk_rt_variant) */
    if (!code_len || code_len > FC26_SC_CODE_MAX || c1_off > code_len) return -1;
    if (stage != 5 && c1_off < 0x30) return -1;                                 /* graphics code starts with a 0x30-byte header */
    return 0;
}
int fc26_sc_journal_put_shader(const char *journal, const char *key, int stage, const uint8_t *control, const uint8_t *code) {
    char name[80], path[PATH_MAX], check[65];
    uint32_t code_len = u32_at(control, 0x704), c1_off = u32_at(control, 0x700);
    if (!fc26_sc_is_key(key) || check_shader(stage, code_len, c1_off)) return -1;
    if (fc26_sc_shader_key(control, code, check) || strcmp(check, key)) return -2;   /* the key rule differs from nvn_mtl.m's */
    snprintf(name, sizeof name, "%s.shader", key);
    if (ensure_dir(journal) || join(path, journal, name)) return -1;
    if (!access(path, F_OK)) return 0;
    uint8_t head[SHADER_HEADER];
    uint32_t words[4] = {SHADER_FORMAT, (uint32_t)stage, FC26_SC_CONTROL_LEN, code_len};
    memcpy(head, SHADER_MAGIC, 8); memcpy(head + 8, words, sizeof words);
    return write_atomic(path, head, sizeof head, control, FC26_SC_CONTROL_LEN, code, code_len) ? -1 : 1;
}
static int fail_why(char *why, size_t n, const char *text) { if (why && n) snprintf(why, n, "%s", text); return -1; }
/* check_key 0: the bytes may hash to another key (fc26_sc_journal_rekey reads entries named by an older key rule). */
static int load_shader(const char *journal, const char *key, int check_key, fc26_sc_shader *out, char *why, size_t why_len) {
    char name[80], path[PATH_MAX], check[65]; size_t len;
    memset(out, 0, sizeof *out);
    if (!fc26_sc_is_key(key)) return fail_why(why, why_len, "not a shader key");
    snprintf(name, sizeof name, "%s.shader", key);
    if (join(path, journal, name)) return fail_why(why, why_len, "path too long");
    uint8_t *data = read_all(path, SHADER_HEADER + FC26_SC_CONTROL_LEN + (size_t)FC26_SC_CODE_MAX, &len);
    if (!data) return fail_why(why, why_len, "cannot read");
    uint32_t w[4];
    if (len < SHADER_HEADER + FC26_SC_CONTROL_LEN || memcmp(data, SHADER_MAGIC, 8)) { free(data); return fail_why(why, why_len, "not a journaled shader"); }
    memcpy(w, data + 8, sizeof w);
    const uint8_t *control = data + SHADER_HEADER, *code = control + FC26_SC_CONTROL_LEN;
    if (w[0] != SHADER_FORMAT || w[2] != FC26_SC_CONTROL_LEN) { free(data); return fail_why(why, why_len, "unknown format"); }
    if (w[3] != u32_at(control, 0x704) || len != SHADER_HEADER + FC26_SC_CONTROL_LEN + (size_t)w[3] ||
        check_shader((int)w[1], w[3], u32_at(control, 0x700))) { free(data); return fail_why(why, why_len, "inconsistent lengths or stage"); }
    if (fc26_sc_shader_key(control, code, check) || (check_key && strcmp(check, key))) { free(data); return fail_why(why, why_len, "bytes do not hash to the key"); }
    out->stage = (int)w[1]; out->code_len = w[3]; out->c1_off = u32_at(control, 0x700);
    out->data = data; out->control = control; out->code = code;
    return 0;
}
int fc26_sc_journal_get_shader(const char *journal, const char *key, fc26_sc_shader *out, char *why, size_t why_len) {
    return load_shader(journal, key, 1, out, why, why_len);
}
void fc26_sc_shader_free(fc26_sc_shader *s) { free(s->data); memset(s, 0, sizeof *s); }

static int rows_path(char *path, const char *journal, const char *key) {
    char name[80];
    snprintf(name, sizeof name, "%s.rows", key);
    return join(path, journal, name);
}
/* Each well-formed row of text (NUL-terminated, changed in place), in order. */
static int each_row(char *text, fc26_sc_row_fn fn, void *ctx) {
    int rows = 0;
    for (char *line = text, *next; line && *line; line = next) {
        next = strchr(line, '\n');
        if (!next) break;
        *next++ = 0;
        if (strncmp(line, "V\t", 2)) continue;
        char *variant = line + 2, *t1 = strchr(variant, '\t'); if (!t1) continue;
        *t1 = 0; char *depth = t1 + 1, *t2 = strchr(depth, '\t'); if (!t2) continue;
        *t2 = 0; const char *json = t2 + 1;
        char key[65];
        if (fc26_sc_variant_key(variant, key) || (strcmp(depth, "0") && strcmp(depth, "1")) || !*json) continue;
        rows++;
        if (fn && fn(ctx, variant, depth[0] == '1', json)) break;
    }
    return rows;
}
struct has_row { const char *variant; int found; };
static int row_is(void *ctx, const char *variant, int depth, const char *json) {
    (void)depth; (void)json;
    struct has_row *h = ctx;
    if (!strcmp(variant, h->variant)) { h->found = 1; return 1; }
    return 0;
}
int fc26_sc_journal_add_row(const char *journal, const char *key, const char *variant, int depth_minus_w, const char *json) {
    char path[PATH_MAX], vkey[65]; size_t len = 0;
    if (!fc26_sc_is_key(key) || fc26_sc_variant_key(variant, vkey) || strcmp(vkey, key) || !json || !*json || strpbrk(json, "\t\r\n")) return -1;
    if (ensure_dir(journal) || rows_path(path, journal, key)) return -1;
    char *text = (char *)read_all(path, 64u << 20, &len);
    if (text) {
        while (len > 0 && text[len - 1] != '\n') len--;
        text[len] = 0;
        char *copy = strdup(text);
        if (!copy) { free(text); return -1; }
        struct has_row h = {variant, 0};
        each_row(copy, row_is, &h); free(copy);
        if (h.found) { free(text); return 0; }
    } else if (errno != ENOENT) return -1;
    size_t n = strlen(variant) + strlen(json) + 8;
    char *line = malloc(n);
    if (!line) { free(text); return -1; }
    int w = snprintf(line, n, "V\t%s\t%d\t%s\n", variant, depth_minus_w ? 1 : 0, json);
    if (w <= 0 || (size_t)w >= n) { free(line); free(text); return -1; }
    int r = text ? write_atomic(path, text, len, line, (size_t)w, NULL, 0)
                 : write_atomic(path, line, (size_t)w, NULL, 0, NULL, 0);
    free(line); free(text);
    return r ? -1 : 1;
}
int fc26_sc_journal_rows(const char *journal, const char *key, fc26_sc_row_fn fn, void *ctx) {
    char path[PATH_MAX]; size_t len;
    if (!fc26_sc_is_key(key) || rows_path(path, journal, key)) return -1;
    char *text = (char *)read_all(path, 64u << 20, &len);
    if (!text) return errno == ENOENT ? 0 : -1;
    int rows = each_row(text, fn, ctx);
    free(text);
    return rows;
}
static int cmp_key(const void *a, const void *b) { return strcmp((const char *)a, (const char *)b); }
long fc26_sc_journal_keys(const char *journal, char (**keys)[65]) {
    *keys = NULL;
    DIR *d = opendir(journal);
    if (!d) return errno == ENOENT ? 0 : -1;
    size_t n = 0, cap = 0; struct dirent *e; char key[65];
    while ((e = readdir(d))) {
        if (!fc26_sc_shader_file(e->d_name, key) || strcmp(e->d_name + 64, ".shader")) continue;
        if (n == cap) {
            cap = cap ? cap * 2 : 256;
            char (*grown)[65] = realloc(*keys, cap * sizeof **keys);
            if (!grown) { closedir(d); free(*keys); *keys = NULL; return -1; }
            *keys = grown;
        }
        memcpy((*keys)[n++], key, 65);
    }
    closedir(d);
    if (n) qsort(*keys, n, sizeof **keys, cmp_key);
    return (long)n;
}

/* ---------- use and size ---------- */
void fc26_sc_touch(const char *cache_dir, const char *journal, const char *key) {
    char path[PATH_MAX], name[80];
    if (!fc26_sc_is_key(key)) return;
    if (journal && !rows_path(path, journal, key) && !utimensat(AT_FDCWD, path, NULL, 0)) return;
    snprintf(name, sizeof name, "%s.variants", key);
    if (!join(path, cache_dir, name)) utimensat(AT_FDCWD, path, NULL, 0);
}
typedef struct { char key[65]; uint64_t bytes; int64_t mtime; } file_rec;
static int cmp_rec(const void *a, const void *b) { return strcmp(((const file_rec *)a)->key, ((const file_rec *)b)->key); }
/* Adds every regular file of dir: shader files to recs, the rest to *fixed. -1 when dir cannot be read. */
static int scan_dir(const char *dir, file_rec **recs, size_t *n, size_t *cap, uint64_t *total, uint64_t *fixed) {
    DIR *d = opendir(dir);
    if (!d) return -1;
    struct dirent *e; char path[PATH_MAX], key[65]; struct stat st;
    while ((e = readdir(d))) {
        if (join(path, dir, e->d_name) || !regular(path, &st)) continue;
        *total += (uint64_t)st.st_size;
        if (!fc26_sc_shader_file(e->d_name, key)) { *fixed += (uint64_t)st.st_size; continue; }
        if (*n == *cap) {
            *cap = *cap ? *cap * 2 : 1024;
            file_rec *grown = realloc(*recs, *cap * sizeof **recs);
            if (!grown) { closedir(d); return -1; }
            *recs = grown;
        }
        file_rec *r = &(*recs)[(*n)++];
        memcpy(r->key, key, 65); r->bytes = (uint64_t)st.st_size; r->mtime = MTIME_NS(st);
    }
    closedir(d);
    return 0;
}
int fc26_sc_scan(const char *cache_dir, const char *journal, fc26_sc_group **groups, size_t *n, uint64_t *total, uint64_t *fixed) {
    file_rec *recs = NULL; size_t nr = 0, cap = 0;
    *groups = NULL; *n = 0; *total = *fixed = 0;
    if (scan_dir(cache_dir, &recs, &nr, &cap, total, fixed) ||
        (journal && scan_dir(journal, &recs, &nr, &cap, total, fixed) && errno != ENOENT)) { free(recs); return -1; }
    if (nr) qsort(recs, nr, sizeof *recs, cmp_rec);
    fc26_sc_group *g = nr ? malloc(nr * sizeof *g) : NULL;
    if (nr && !g) { free(recs); return -1; }
    size_t ng = 0;
    for (size_t i = 0; i < nr; i++) {
        if (!ng || strcmp(g[ng - 1].key, recs[i].key)) { memcpy(g[ng].key, recs[i].key, 65); g[ng].bytes = 0; g[ng].last_use_ns = INT64_MIN; ng++; }
        g[ng - 1].bytes += recs[i].bytes;
        if (recs[i].mtime > g[ng - 1].last_use_ns) g[ng - 1].last_use_ns = recs[i].mtime;
    }
    free(recs);
    *groups = g; *n = ng;
    return 0;
}
static int cmp_age(const void *a, const void *b) {
    const fc26_sc_group *x = a, *y = b;
    if (x->last_use_ns != y->last_use_ns) return x->last_use_ns < y->last_use_ns ? -1 : 1;
    return strcmp(x->key, y->key);
}
size_t fc26_sc_trim_plan(fc26_sc_group *groups, size_t n, uint64_t total, uint64_t limit, uint64_t *after) {
    *after = total;
    if (!limit || total <= limit || !n) return 0;
    uint64_t target = limit - limit / 10;
    qsort(groups, n, sizeof *groups, cmp_age);
    size_t k = 0;
    while (k < n && *after > target) *after -= groups[k++].bytes;
    return k;
}
/* Removes the files of dir whose shader key is in keys (sorted). */
static int unlink_keys(const char *dir, char (*keys)[65], size_t nk) {
    DIR *d = opendir(dir);
    if (!d) return 0;
    int removed = 0; struct dirent *e; char path[PATH_MAX], key[65]; struct stat st;
    while ((e = readdir(d))) {
        if (!fc26_sc_shader_file(e->d_name, key) || !bsearch(key, keys, nk, sizeof *keys, cmp_key)) continue;
        if (!join(path, dir, e->d_name) && regular(path, &st) && !unlink(path)) removed++;
    }
    closedir(d);
    return removed;
}
int fc26_sc_evict(const char *cache_dir, const char *journal, const char *key) {
    char one[1][65];
    if (!fc26_sc_is_key(key)) return 0;
    memcpy(one[0], key, 65);
    return unlink_keys(cache_dir, one, 1) + (journal ? unlink_keys(journal, one, 1) : 0);
}
struct rekey_rows { const char *journal, *key; int failed; };
static int move_row(void *ctx, const char *variant, int depth_minus_w, const char *json) {
    struct rekey_rows *m = ctx; char renamed[80];
    snprintf(renamed, sizeof renamed, "%s%s", m->key, variant + 64);   /* "<key>-<12 hex>": the suffix names the bind state */
    if (fc26_sc_journal_add_row(m->journal, m->key, renamed, depth_minus_w, json) < 0) m->failed = 1;
    return 0;
}
long fc26_sc_journal_rekey(const char *journal, const char *cache_dir) {
    char (*keys)[65]; long n = fc26_sc_journal_keys(journal, &keys), moved = 0;
    if (n < 0) return -1;
    for (long i = 0; i < n; i++) {
        fc26_sc_shader s; char key[65], why[64];
        if (load_shader(journal, keys[i], 0, &s, why, sizeof why)) continue;   /* damaged: the prefill reports it */
        if (fc26_sc_shader_key(s.control, s.code, key) || !strcmp(key, keys[i])) { fc26_sc_shader_free(&s); continue; }
        struct rekey_rows m = {journal, key, 0};
        int put = fc26_sc_journal_put_shader(journal, key, s.stage, s.control, s.code);   /* 0: another old entry made it */
        fc26_sc_shader_free(&s);
        if (put < 0 || fc26_sc_journal_rows(journal, keys[i], move_row, &m) < 0 || m.failed) continue;   /* kept: tried again next start */
        memmove(keys[moved++], keys[i], 65);   /* keys stay sorted: unlink_keys looks them up */
    }
    if (moved) { unlink_keys(journal, keys, (size_t)moved); if (cache_dir) unlink_keys(cache_dir, keys, (size_t)moved); }
    free(keys);
    return moved;
}
int fc26_sc_trim(const char *cache_dir, const char *journal, uint64_t limit, fc26_sc_trim_report *r) {
    fc26_sc_group *g; size_t n; uint64_t total, fixed;
    memset(r, 0, sizeof *r); r->limit = limit;
    if (fc26_sc_scan(cache_dir, journal, &g, &n, &total, &fixed)) return -1;
    r->shaders = n; r->before = r->after = total;
    size_t k = fc26_sc_trim_plan(g, n, total, limit, &r->after);
    if (k) {
        char (*keys)[65] = malloc(k * sizeof *keys);
        if (!keys) { free(g); r->after = total; return -1; }
        for (size_t i = 0; i < k; i++) memcpy(keys[i], g[i].key, 65);
        qsort(keys, k, sizeof *keys, cmp_key);
        unlink_keys(cache_dir, keys, k);
        if (journal) unlink_keys(journal, keys, k);
        free(keys);
    }
    r->evicted = k;
    free(g);
    return 0;
}
int fc26_sc_lock(const char *cache_dir) { return try_lock_path(cache_dir); }

/* ---------- settings ---------- */
uint64_t fc26_sc_limit_bytes(const char *value, int *bad) {
    *bad = 0;
    if (!value) return (uint64_t)FC26_SC_DEFAULT_LIMIT_MIB << 20;
    char *end; unsigned long long mib = strtoull(value, &end, 10);
    if (end == value || *end || *value == '-' || mib > (1ull << 20)) { *bad = 1; return (uint64_t)FC26_SC_DEFAULT_LIMIT_MIB << 20; }
    return (uint64_t)mib << 20;
}
int fc26_sc_warm_all(const char *value, int *bad) {
    *bad = 0;
    if (!value || !strcmp(value, "all")) return 1;
    if (!strcmp(value, "kit")) return 0;
    *bad = 1;
    return 1;
}
int fc26_sc_warm_timeout_s(const char *value, int *bad) {
    *bad = 0;
    if (!value) return FC26_SC_DEFAULT_WARM_TIMEOUT_S;
    char *end; long s = strtol(value, &end, 10);
    if (end == value || *end || s < 1 || s > 3600) { *bad = 1; return FC26_SC_DEFAULT_WARM_TIMEOUT_S; }
    return (int)s;
}
