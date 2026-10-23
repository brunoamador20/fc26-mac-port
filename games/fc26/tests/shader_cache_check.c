/* Command-line harness over runtime/shader_cache.c for tests/test_shader_cache.py: one subcommand per function, results
   on stdout. Runs on Linux and on the Mac; no game data (the tests make synthetic shaders and folders). */
#include "shader_cache.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static uint8_t *load(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *p = malloc(len > 0 ? (size_t)len : 1);
    if (!p || fread(p, 1, (size_t)len, f) != (size_t)len) { fprintf(stderr, "cannot read %s\n", path); exit(2); }
    fclose(f); *n = (size_t)len;
    return p;
}
static const char *opt(const char *s) { return strcmp(s, "-") ? s : NULL; }
static int print_row(void *ctx, const char *variant, int depth, const char *json) {
    (void)ctx; printf("%s %d %s\n", variant, depth, json);
    return 0;
}
struct id_writer_arg { const char *path; int iters; _Atomic int *failures; };
static void *id_writer_fn(void *p) {
    struct id_writer_arg *a = p;
    fc26_sc_identity id = {.schema = 1, .depth_minus_w = 0};
    snprintf(id.chain, sizeof id.chain, "chain");
    snprintf(id.translator, sizeof id.translator, "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    snprintf(id.spirv_cross, sizeof id.spirv_cross, "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    snprintf(id.request, sizeof id.request, "kit-1");
    snprintf(id.debug_mode, sizeof id.debug_mode, "default");
    for (int i = 0; i < a->iters; i++) {
        if (fc26_sc_identity_write(a->path, &id)) atomic_fetch_add(a->failures, 1);
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *c = argv[1];
    if (!strcmp(c, "sha256") && argc == 4) {   /* sha256 <file> <chunk>: fed in pieces of chunk bytes */
        size_t n; uint8_t *p = load(argv[2], &n), md[32]; size_t chunk = (size_t)atol(argv[3]); char hex[65];
        fc26_sha256 s; fc26_sha256_init(&s);
        for (size_t at = 0; at < n; at += chunk) fc26_sha256_update(&s, p + at, n - at < chunk ? n - at : chunk);
        fc26_sha256_final(&s, md); fc26_hex(md, 32, hex);
        char whole[65]; if (fc26_sha256_file(argv[2], whole) || strcmp(whole, hex)) { puts("file-mismatch"); return 1; }
        puts(hex); free(p); return 0;
    }
    if (!strcmp(c, "key") && argc == 4) {   /* key <control> <code> */
        size_t nc, nd; uint8_t *ctl = load(argv[2], &nc), *code = load(argv[3], &nd); char key[65];
        if (nc < FC26_SC_CONTROL_LEN) return 2;
        printf("%u ", fc26_sc_control_key_len(ctl));
        puts(fc26_sc_shader_key(ctl, code, key) ? "invalid" : key);
        free(ctl); free(code);
        return 0;
    }
    if (!strcmp(c, "names") && argc == 3) {   /* names <text>: is_key, variant_key, shader_file */
        char key[65] = "";
        printf("is_key %d\n", fc26_sc_is_key(argv[2]));
        printf("variant %s\n", fc26_sc_variant_key(argv[2], key) ? "-" : key);
        key[0] = 0; int file = fc26_sc_shader_file(argv[2], key);   /* before printf: argument order is unspecified */
        printf("file %d %s\n", file, key[0] ? key : "-");
        return 0;
    }
    if (!strcmp(c, "id-write") && argc == 10) {   /* id-write <path> <schema> <chain> <translator> <spirv> <request> <debug> <depth> */
        fc26_sc_identity id = {.schema = atoi(argv[3]), .depth_minus_w = atoi(argv[9])};
        snprintf(id.chain, sizeof id.chain, "%s", argv[4]); snprintf(id.translator, sizeof id.translator, "%s", argv[5]);
        snprintf(id.spirv_cross, sizeof id.spirv_cross, "%s", argv[6]); snprintf(id.request, sizeof id.request, "%s", argv[7]);
        snprintf(id.debug_mode, sizeof id.debug_mode, "%s", argv[8]);
        printf("%d\n", fc26_sc_identity_write(argv[2], &id));
        return 0;
    }
    if (!strcmp(c, "concurrent-id-write") && argc == 5) {   /* concurrent-id-write <path> <threads> <iters> */
        int threads = atoi(argv[3]), iters = atoi(argv[4]);
        _Atomic int failures = 0;
        pthread_t *th = malloc((size_t)threads * sizeof *th);
        struct id_writer_arg arg = {argv[2], iters, &failures};
        for (int i = 0; i < threads; i++) pthread_create(&th[i], NULL, id_writer_fn, &arg);
        for (int i = 0; i < threads; i++) pthread_join(th[i], NULL);
        free(th);
        printf("failures %d\n", atomic_load(&failures));
        return 0;
    }
    if (!strcmp(c, "id-read") && argc == 3) {
        fc26_sc_identity id; int r = fc26_sc_identity_read(argv[2], &id);
        if (r) { puts(r == -1 ? "missing" : "invalid"); return 0; }
        printf("%d %s %s %s %s %s %d\n", id.schema, id.chain, id.translator, id.spirv_cross, id.request, id.debug_mode, id.depth_minus_w);
        return 0;
    }
    if (!strcmp(c, "id-diff") && argc == 4) {
        fc26_sc_identity a, b;
        if (fc26_sc_identity_read(argv[2], &a) || fc26_sc_identity_read(argv[3], &b)) { puts("unreadable"); return 0; }
        const char *d = fc26_sc_identity_diff(&a, &b); puts(d ? d : "same");
        return 0;
    }
    if (!strcmp(c, "discard") && argc == 3) { printf("%ld\n", fc26_sc_discard(argv[2])); return 0; }
    if (!strcmp(c, "old-chains") && argc == 4) { printf("%d\n", fc26_sc_remove_old_chains(argv[2], argv[3])); return 0; }
    if (!strcmp(c, "put") && argc == 7) {   /* put <journal> <key> <stage> <control> <code> */
        size_t nc, nd; uint8_t *ctl = load(argv[5], &nc), *code = load(argv[6], &nd);
        printf("%d\n", fc26_sc_journal_put_shader(argv[2], argv[3], atoi(argv[4]), ctl, code));
        free(ctl); free(code);
        return 0;
    }
    if (!strcmp(c, "get") && argc == 4) {
        fc26_sc_shader s; char why[128];
        if (fc26_sc_journal_get_shader(argv[2], argv[3], &s, why, sizeof why)) { printf("fail %s\n", why); return 0; }
        printf("ok %d %u %u\n", s.stage, s.code_len, s.c1_off);
        fc26_sc_shader_free(&s);
        return 0;
    }
    if (!strcmp(c, "add-row") && argc == 7) {   /* add-row <journal> <key> <variant> <depth> <json> */
        printf("%d\n", fc26_sc_journal_add_row(argv[2], argv[3], argv[4], atoi(argv[5]), argv[6]));
        return 0;
    }
    if (!strcmp(c, "rekey") && argc == 4) { printf("%ld\n", fc26_sc_journal_rekey(argv[2], opt(argv[3]))); return 0; }   /* rekey <journal> <cache|-> */
    if (!strcmp(c, "rows") && argc == 4) { int n = fc26_sc_journal_rows(argv[2], argv[3], print_row, NULL); printf("rows %d\n", n); return 0; }
    if (!strcmp(c, "keys") && argc == 3) {
        char (*keys)[65]; long n = fc26_sc_journal_keys(argv[2], &keys);
        for (long i = 0; i < n; i++) puts(keys[i]);
        printf("keys %ld\n", n); free(keys);
        return 0;
    }
    if (!strcmp(c, "touch") && argc == 5) { fc26_sc_touch(argv[2], opt(argv[3]), argv[4]); return 0; }
    if (!strcmp(c, "scan") && argc == 4) {
        fc26_sc_group *g; size_t n; uint64_t total, fixed;
        if (fc26_sc_scan(argv[2], opt(argv[3]), &g, &n, &total, &fixed)) { puts("fail"); return 0; }
        for (size_t i = 0; i < n; i++) printf("%s %llu %lld\n", g[i].key, (unsigned long long)g[i].bytes, (long long)g[i].last_use_ns);
        printf("total %llu fixed %llu\n", (unsigned long long)total, (unsigned long long)fixed);
        free(g);
        return 0;
    }
    if (!strcmp(c, "plan") && argc >= 4) {   /* plan <limit> <total> <key>:<bytes>:<last use ns> ... */
        size_t n = (size_t)argc - 4; fc26_sc_group *g = calloc(n ? n : 1, sizeof *g);
        for (size_t i = 0; i < n; i++) {
            char *s = argv[4 + i], *a = strchr(s, ':'), *b = a ? strchr(a + 1, ':') : NULL;
            if (!a || !b) return 2;
            *a = 0; snprintf(g[i].key, sizeof g[i].key, "%s", s);
            g[i].bytes = strtoull(a + 1, NULL, 10); g[i].last_use_ns = strtoll(b + 1, NULL, 10);
        }
        uint64_t after; size_t k = fc26_sc_trim_plan(g, n, strtoull(argv[3], NULL, 10), strtoull(argv[2], NULL, 10), &after);
        for (size_t i = 0; i < k; i++) printf("evict %s\n", g[i].key);
        printf("after %llu\n", (unsigned long long)after);
        free(g);
        return 0;
    }
    if (!strcmp(c, "trim") && argc == 5) {
        fc26_sc_trim_report r;
        int ret = fc26_sc_trim(argv[2], opt(argv[3]), strtoull(argv[4], NULL, 10), &r);
        printf("%d shaders %zu evicted %zu before %llu after %llu\n", ret, r.shaders, r.evicted, (unsigned long long)r.before, (unsigned long long)r.after);
        return 0;
    }
    if (!strcmp(c, "evict") && argc == 5) { printf("%d\n", fc26_sc_evict(argv[2], opt(argv[3]), argv[4])); return 0; }
    if (!strcmp(c, "lock") && argc == 3) {   /* lock <dir>: holds the lock until stdin closes */
        int fd = fc26_sc_lock(argv[2]);
        printf("%s\n", fd >= 0 ? "locked" : "busy"); fflush(stdout);
        if (fd >= 0) { char b[16]; while (read(0, b, sizeof b) > 0) {} close(fd); }
        return 0;
    }
    if (!strcmp(c, "settings") && argc == 5) {   /* settings <limit MiB> <warm> <timeout s>, "-" for unset */
        int b1, b2, b3;
        uint64_t limit = fc26_sc_limit_bytes(opt(argv[2]), &b1); int all = fc26_sc_warm_all(opt(argv[3]), &b2), t = fc26_sc_warm_timeout_s(opt(argv[4]), &b3);
        printf("%llu %d %d %d %d %d\n", (unsigned long long)limit, b1, all, b2, t, b3);
        return 0;
    }
    fprintf(stderr, "unknown command %s\n", c);
    return 2;
}
