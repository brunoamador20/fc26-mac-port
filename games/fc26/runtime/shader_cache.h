/* FC 26: the shader cache layer around the kit's runtime translation (third_party/d2r_gfx/gfx/nvn/totk_shader_rt.m).
   The kit already keeps every translated variant on disk (<cache>/<key>.variants, <variant>_b.metal / _b.json) and warms
   them at the next start (nvn_mtl.m warm_start). This layer adds what FC 26 needs on top (docs/SHADERS_NUVEM.md):
   - an identity of the translation (translator, SPIRV-Cross, chain, request, debug mode, depth mode): a cache made by
     another one is emptied instead of being used;
   - a journal of every shader the game handed NVN (control section + code, and each bind state it was translated for),
     kept apart from the translations, so a new translator re-translates them at the next start, before play;
   - a size limit (least recently used shaders go first) and a lock (one run trims at a time).
   Plain C (POSIX) so the logic is tested on Linux (tests/test_shader_cache.py); runtime/shader_cache_mac.m wires it in. */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define FC26_SC_SCHEMA 1                /* this layer's own files (identity, journal): bump when their format changes */
#define FC26_SC_REQUEST_REV "kit-1"     /* the request totk_rt_variant sends the translator: bump when its fields change */
#define FC26_SC_ID_FILE "fc26-cache.id"
#define FC26_SC_LOCK_FILE "fc26-cache.lock"
#define FC26_SC_CONTROL_LEN 0x880u      /* the control bytes the kit reads (key, stage, c1, thread group size) */
#define FC26_SC_CODE_MAX (16u << 20)    /* the kit's own bound on a shader's code length (totk_rt_variant) */
#define FC26_SC_DEFAULT_LIMIT_MIB 2048u
#define FC26_SC_DEFAULT_WARM_TIMEOUT_S 300

/* SHA-256 (FIPS 180-4): the kit hashes with CommonCrypto, which Linux does not have. */
typedef struct { uint32_t h[8]; uint64_t bytes; uint8_t buf[64]; size_t used; } fc26_sha256;
void fc26_sha256_init(fc26_sha256 *s);
void fc26_sha256_update(fc26_sha256 *s, const void *data, size_t n);
void fc26_sha256_final(fc26_sha256 *s, uint8_t out[32]);
void fc26_hex(const uint8_t *p, size_t n, char *out);          /* out holds 2n + 1 */
int fc26_sha256_file(const char *path, char hex[65]);           /* 0, or -1 when it cannot be read */

/* The shader key, as nvn_mtl.m prog_get computes it: SHA-256 of the control section's first control_key_len bytes and
   of the code's first <u32 at control+0x704> bytes. control_key_len is nvn_mtl.m ctl_key_len (keep the two equal). */
uint32_t fc26_sc_control_key_len(const uint8_t *control);
int fc26_sc_shader_key(const uint8_t *control, const uint8_t *code, char key[65]);   /* 0, -1 implausible code length */
int fc26_sc_is_key(const char *s);                                                  /* 64 lowercase hex digits */
int fc26_sc_variant_key(const char *variant, char key[65]);   /* "<key>-<12 hex>" (totk_rt_variant's names): 0, else -1 */
/* A file of one shader: its name starts with the key and a '.' or '-' (<key>.variants, <key>-<suffix>_b.metal, .code,
   .spv, .res.json, temporaries; journal <key>.shader / .rows). Returns 1 and the key, else 0. */
int fc26_sc_shader_file(const char *name, char key[65]);

/* What a translation depends on besides the shader and its bind state (those name the variant). */
typedef struct {
    int schema;               /* FC26_SC_SCHEMA */
    char chain[64];           /* DMSH_CHAIN: the translation chain the runtime expects */
    char translator[72];      /* SHA-256 of the translator program */
    char spirv_cross[72];     /* SHA-256 of spirv-cross */
    char request[24];         /* FC26_SC_REQUEST_REV */
    char debug_mode[24];      /* TOTK_SHADER_DEBUGMODE, "default" when unset */
    int depth_minus_w;        /* nvnDeviceSetDepthMode(NEAR_IS_MINUS_W): every vertex shader is translated with it */
} fc26_sc_identity;
int fc26_sc_identity_write(const char *path, const fc26_sc_identity *id);   /* 0, -1 */
int fc26_sc_identity_read(const char *path, fc26_sc_identity *id);         /* 0, -1 missing, -2 not an identity */
const char *fc26_sc_identity_diff(const fc26_sc_identity *a, const fc26_sc_identity *b);   /* NULL when equal, else the first field that differs */

/* The translations of a cache folder whose identity is not the current one: every shader file and the seed receipt go;
   the warm lists (pso_collected.tsv) stay (they name variants, and a variant's name does not depend on the translator).
   Returns the number of files removed, -1 when the folder cannot be read. */
long fc26_sc_discard(const char *cache_dir);
/* Older chains' folders next to the current one (rt-<chain>): removed when this layer stamped them (they hold
   FC26_SC_ID_FILE) and no run holds their lock; anything else there is left alone. Returns the number removed. */
int fc26_sc_remove_old_chains(const char *parent, const char *current_name);

/* The journal: <journal>/<key>.shader = "FC26SHD1", u32 format 1, u32 stage, u32 control length (0x880), u32 code
   length, the control section, the code ([0, u32 at control+0x704): what the kit hashes and translates). */
int fc26_sc_journal_put_shader(const char *journal, const char *key, int stage, const uint8_t *control, const uint8_t *code);   /* 1 written, 0 already there, -1 */
typedef struct { int stage; uint32_t code_len, c1_off; uint8_t *data; const uint8_t *control, *code; } fc26_sc_shader;
/* Reads and checks a journaled shader (format, stage, lengths, and that its bytes still hash to key). 0, else -1 and why. */
int fc26_sc_journal_get_shader(const char *journal, const char *key, fc26_sc_shader *out, char *why, size_t why_len);
void fc26_sc_shader_free(fc26_sc_shader *s);
/* <journal>/<key>.rows: one line per variant the runtime translated, "V\t<variant>\t<depth_minus_w>\t<json>", json being
   the request's bind state (no tab or newline in it). Added once per variant: 1 added, 0 already there, -1. */
int fc26_sc_journal_add_row(const char *journal, const char *key, const char *variant, int depth_minus_w, const char *json);
typedef int (*fc26_sc_row_fn)(void *ctx, const char *variant, int depth_minus_w, const char *json);   /* non-0 stops */
int fc26_sc_journal_rows(const char *journal, const char *key, fc26_sc_row_fn fn, void *ctx);          /* rows, -1 */
/* The journaled shaders (keys with a .shader file), sorted; free(*keys). Returns the count, -1. */
long fc26_sc_journal_keys(const char *journal, char (**keys)[65]);

/* Size limit, least recently used first. A shader's last use is the newest modification time of its files in either
   folder; fc26_sc_touch marks a use (the journal's rows, else the cache's index). */
void fc26_sc_touch(const char *cache_dir, const char *journal, const char *key);
typedef struct { char key[65]; uint64_t bytes; int64_t last_use_ns; } fc26_sc_group;
/* Every shader's files and bytes (groups, sorted by key; free(*groups)), all bytes of both folders (total) and the
   bytes no shader owns (warm lists, identity...). 0, -1 when the cache folder cannot be read. */
int fc26_sc_scan(const char *cache_dir, const char *journal, fc26_sc_group **groups, size_t *n, uint64_t *total, uint64_t *fixed);
/* Above limit (0: none), the oldest shaders go until the total is at most 9/10 of it. Sorts groups oldest first and
   returns how many of the first ones to remove; *after is the total then. */
size_t fc26_sc_trim_plan(fc26_sc_group *groups, size_t n, uint64_t total, uint64_t limit, uint64_t *after);
int fc26_sc_evict(const char *cache_dir, const char *journal, const char *key);   /* files removed */
typedef struct { size_t shaders, evicted; uint64_t before, after, limit; } fc26_sc_trim_report;
int fc26_sc_trim(const char *cache_dir, const char *journal, uint64_t limit, fc26_sc_trim_report *r);   /* 0, -1 */

/* One run maintains the folder at a time: a lock held until the process ends. The descriptor, or -1 when another run
   holds it (or it cannot be made). */
int fc26_sc_lock(const char *cache_dir);

/* Settings (environment values; *bad set when the value is not understood and the default is used):
   FC26_SHADER_CACHE_MAX_MIB (default FC26_SC_DEFAULT_LIMIT_MIB, 0 = no limit), FC26_SHADER_WARM ("all": the first
   shader use waits until every cached shader and recorded pipeline is compiled, the default; "kit": the kit's own
   gates only), FC26_SHADER_WARM_TIMEOUT_S (1..3600, default FC26_SC_DEFAULT_WARM_TIMEOUT_S). */
uint64_t fc26_sc_limit_bytes(const char *value, int *bad);
int fc26_sc_warm_all(const char *value, int *bad);
int fc26_sc_warm_timeout_s(const char *value, int *bad);
