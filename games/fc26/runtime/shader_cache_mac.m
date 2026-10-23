/* FC 26: the shader cache layer (runtime/shader_cache.c) wired into the kit's runtime translation and warm-up.
   docs/SHADERS_NUVEM.md has the design and the Mac checks. The graphics layer calls these through weak imports at five
   places: totk_shader_rt.m totk_rt_dir (fc26_shader_cache_open, once, before the folder is used), totk_rt_variant
   (fc26_shader_cache_used when a cached variant serves, fc26_shader_cache_saved after a new translation, both under its
   translation lock), nvn_mtl.m warm_start (fc26_shader_prefill before the warm-up is planned, fc26_shader_warm_gate after
   its first list). FC26_SHADER_CACHE=0 leaves the kit's cache exactly as it was (none of this runs).
   TODO(mac): compiled by the macOS CI only; the steps that run it with the game are in docs/SHADERS_NUVEM.md. */
#import <Foundation/Foundation.h>
#include "runtime.h"
#include "shader_cache.h"
#include <limits.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

NSString *totk_rt_variant(NSString *shader, int stage, const uint8_t *control, const uint8_t *code, NSDictionary *answers, NSArray *local);
int totk_depth_near_minus_w(void);   /* hle_nvn.c */
int mtl_warm_wait(int timeout_ms);   /* nvn_mtl.m */

#define SCLOG(...) do { flockfile(stderr); fprintf(stderr, "[fc26-shader-cache] " __VA_ARGS__); fputc('\n', stderr); funlockfile(stderr); } while (0)

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static char g_cache[PATH_MAX], g_journal[PATH_MAX], g_id_path[PATH_MAX];
static int g_on;           /* open ran: the journal and use marks are kept */
static int g_maintainer;   /* this run holds the folder's lock: it may discard, trim and prefill */
static fc26_sc_identity g_id;

static int layer_off(void) { const char *e = getenv("FC26_SHADER_CACHE"); return e && !strcmp(e, "0"); }
static uint64_t now_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

/* The work folder: the executable is <work>/build/fc26-native (totk_shader_rt.m root_dir, the same rule). */
static NSString *root_dir(void) {
    char path[PATH_MAX]; uint32_t n = sizeof path;
    if (_NSGetExecutablePath(path, &n)) return nil;
    return [[@(path) stringByResolvingSymlinksInPath].stringByDeletingLastPathComponent stringByDeletingLastPathComponent];
}
/* The translator the kit's service_start will run (same choice: TOTK_SHADER_XLATE, TOTK_SHADER_SERVICE=python, else the
   native build/shader-service/totk_xlate). */
static NSString *translator_path(NSString *root) {
    const char *xe = getenv("TOTK_SHADER_XLATE"), *want = getenv("TOTK_SHADER_SERVICE");
    if (xe && *xe) return @(xe);
    if (want && !strcmp(want, "python")) return [root stringByAppendingString:@"/build/totk_xlate/totk_xlate.dll"];
    return [root stringByAppendingString:@"/build/shader-service/totk_xlate"];
}
static int copy_field(char *dst, size_t cap, const char *src) {
    int n = snprintf(dst, cap, "%s", src);
    for (char *p = dst; *p; p++) if (*p == '\n' || *p == '\r') *p = '_';
    return n > 0 && (size_t)n < cap ? 0 : -1;
}

void fc26_shader_cache_open(NSString *dir, const char *chain) {
    static int once;
    if (once++ || !dir.length) return;
    if (layer_off()) { SCLOG("off (FC26_SHADER_CACHE=0): the kit's cache only"); return; }
    NSString *journal = getenv("FC26_SHADER_JOURNAL") && *getenv("FC26_SHADER_JOURNAL") ? @(getenv("FC26_SHADER_JOURNAL"))
                      : [dir.stringByDeletingLastPathComponent stringByAppendingPathComponent:@"fc26-journal"];
    if (copy_field(g_cache, sizeof g_cache, dir.fileSystemRepresentation) || copy_field(g_journal, sizeof g_journal, journal.fileSystemRepresentation) ||
        snprintf(g_id_path, sizeof g_id_path, "%s/" FC26_SC_ID_FILE, g_cache) >= (int)sizeof g_id_path) { SCLOG("path too long: %s", dir.UTF8String); return; }
    [NSFileManager.defaultManager createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
    g_on = 1;

    /* What the translations here depend on. A missing tool is not a reason to empty the cache: report it and keep it. */
    NSString *root = root_dir();
    if (!root) { SCLOG("cannot find the executable's folder: cache left as it is"); return; }
    NSString *xlate = translator_path(root), *sc = [root stringByAppendingString:@"/build/spirv-cross/spirv-cross"];
    uint64_t t0 = now_ns();
    g_id.schema = FC26_SC_SCHEMA;
    const char *dm = getenv("TOTK_SHADER_DEBUGMODE");
    if (copy_field(g_id.chain, sizeof g_id.chain, chain) || copy_field(g_id.request, sizeof g_id.request, FC26_SC_REQUEST_REV) ||
        copy_field(g_id.debug_mode, sizeof g_id.debug_mode, !dm ? "default" : *dm ? dm : "empty")) { SCLOG("identity field too long: cache left as it is"); return; }
    g_id.depth_minus_w = totk_depth_near_minus_w();
    if (fc26_sha256_file(xlate.fileSystemRepresentation, g_id.translator) || fc26_sha256_file(sc.fileSystemRepresentation, g_id.spirv_cross)) {
        SCLOG("translator %s or SPIRV-Cross %s missing (make shader-tools): cache left as it is, nothing translated before play",
              xlate.UTF8String, sc.UTF8String);
        return;
    }
    int fd = fc26_sc_lock(g_cache);
    if (fd < 0) { SCLOG("another run holds %s: no discard, trim or prefill this time", g_cache); return; }
    g_maintainer = 1;   /* fd stays open: the lock lasts until the process ends (O_CLOEXEC: not the translator's) */

    fc26_sc_identity old; int r = fc26_sc_identity_read(g_id_path, &old);
    const char *why = r == -1 ? NULL : r ? "unreadable identity" : fc26_sc_identity_diff(&old, &g_id);
    if (r == -1) {   /* no identity: a new folder, or translations from before this layer (their translator is unknown) */
        fc26_sc_group *g; size_t n; uint64_t total, fixed;
        if (!fc26_sc_scan(g_cache, NULL, &g, &n, &total, &fixed)) { if (n) why = "no identity"; free(g); }
    }
    if (why) {
        long gone = fc26_sc_discard(g_cache);
        SCLOG("cache identity differs (%s): %ld translation files removed; the journal re-translates them before play", why, gone);
    }
    if (fc26_sc_identity_write(g_id_path, &g_id)) SCLOG("cannot write %s", g_id_path);
    int old_chains = fc26_sc_remove_old_chains(dir.stringByDeletingLastPathComponent.fileSystemRepresentation, dir.lastPathComponent.UTF8String);
    if (old_chains) SCLOG("removed %d folder(s) of older translation chains", old_chains);

    int bad; uint64_t limit = fc26_sc_limit_bytes(getenv("FC26_SHADER_CACHE_MAX_MIB"), &bad);
    if (bad) SCLOG("FC26_SHADER_CACHE_MAX_MIB=%s not understood (MiB, 0 = no limit): %u MiB", getenv("FC26_SHADER_CACHE_MAX_MIB"), FC26_SC_DEFAULT_LIMIT_MIB);
    fc26_sc_trim_report tr;
    if (fc26_sc_trim(g_cache, g_journal, limit, &tr)) { SCLOG("cannot read %s to apply the size limit", g_cache); return; }
    SCLOG("cache %s: %zu shaders, %.1f MiB with the journal (limit %s); %zu least recently used removed%s; identity %.12s/%.12s %s depth_minus_w=%d (%.0f ms)",
          g_cache, tr.shaders - tr.evicted, tr.after / 1048576.0, limit ? [NSString stringWithFormat:@"%llu MiB", (unsigned long long)(limit >> 20)].UTF8String : "none",
          tr.evicted, tr.evicted ? [NSString stringWithFormat:@" (%.1f MiB before)", tr.before / 1048576.0].UTF8String : "",
          g_id.translator, g_id.spirv_cross, g_id.chain, g_id.depth_minus_w, (now_ns() - t0) / 1e6);
}

void fc26_shader_cache_used(NSString *shader) {
    if (!g_on) return;
    static NSMutableSet<NSString *> *seen;
    pthread_mutex_lock(&g_lock);
    if (!seen) seen = [NSMutableSet set];
    BOOL first = ![seen containsObject:shader];
    if (first) [seen addObject:shader];
    pthread_mutex_unlock(&g_lock);
    if (first) fc26_sc_touch(g_cache, g_journal, shader.UTF8String);   /* once per shader per run */
}

void fc26_shader_cache_saved(NSString *shader, int stage, const uint8_t *control, const uint8_t *code, NSDictionary *request) {
    if (!g_on || !shader || !control || !code) return;
    static int said_key, said_put, said_row, said_depth;
    const char *key = shader.UTF8String;
    int put = fc26_sc_journal_put_shader(g_journal, key, stage, control, code);
    if (put == -2 && !said_key++) SCLOG("shader %s: the key rule here (shader_cache.c) differs from nvn_mtl.m ctl_key_len: not journaled", key);
    else if (put == -1 && !said_put++) SCLOG("cannot journal shader %s (stage %d) in %s", key, stage, g_journal);
    if (put < 0) return;
    NSMutableDictionary *state = [NSMutableDictionary dictionary];   /* the bind state the variant was translated for */
    for (NSString *k in @[@"tex", @"img", @"attr", @"fout", @"local"]) if (request[k]) state[k] = request[k];
    NSData *data = [NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingSortedKeys error:nil];
    NSString *json = data ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
    NSString *variant = request[@"variant"];
    int depth = [request[@"depth_minus_w"] boolValue];
    pthread_mutex_lock(&g_lock);
    int added = json && [variant isKindOfClass:NSString.class] ? fc26_sc_journal_add_row(g_journal, key, variant.UTF8String, depth, json.UTF8String) : -1;
    pthread_mutex_unlock(&g_lock);
    if (added < 0 && !said_row++) SCLOG("cannot journal variant %s", [variant description].UTF8String);
    if (g_maintainer && depth != g_id.depth_minus_w && !said_depth++) {
        /* The depth mode changed after the cache was opened: variants of both modes are mixed now. Without an identity the
           next start empties the cache and re-translates the journal with the mode the game sets then. */
        unlink(g_id_path);
        SCLOG("the game changed the depth mode during the run (depth_minus_w %d -> %d): the cache is rebuilt at the next start", g_id.depth_minus_w, depth);
    }
}

static int collect_row(void *ctx, const char *variant, int depth_minus_w, const char *json) {
    (void)depth_minus_w;   /* the translation takes the mode the game set in this run (totk_rt_variant) */
    NSString *v = @(variant), *j = @(json);
    if (v && j) [(__bridge NSMutableArray *)ctx addObject:@[v, j]];
    return 0;
}
/* Journaled variants this translator has not translated (a new translator, a cache copied without its translations):
   translated now through the kit's own path (totk_rt_variant), so the warm-up that follows compiles them before play. A
   variant whose translation stopped an earlier prefill (its <variant>.prefill marker is still there) is skipped: it is
   translated, or stops the game, only if the game uses it. */
void fc26_shader_prefill(NSString *dir) {
    (void)dir;   /* the caller passes totk_rt_dir(): that call is what opens the cache */
    const char *e = getenv("FC26_SHADER_PREFILL"), *nt = getenv("TOTK_SHADER_NO_TRANSLATE");
    if (!g_on || !g_maintainer || (e && !strcmp(e, "0")) || (nt && !strcmp(nt, "1"))) return;
    char (*keys)[65]; long nk = fc26_sc_journal_keys(g_journal, &keys);
    if (nk <= 0) return;
    NSMutableArray<NSArray *> *todo = [NSMutableArray array];   /* @[key, variant, json] */
    NSUInteger skipped = 0, damaged = 0;
    NSFileManager *fm = NSFileManager.defaultManager;
    for (long i = 0; i < nk; i++) @autoreleasepool {
        NSString *key = @(keys[i]);
        NSMutableArray<NSArray *> *rows = [NSMutableArray array];
        fc26_sc_journal_rows(g_journal, keys[i], collect_row, (__bridge void *)rows);
        for (NSArray *row in rows) {
            if ([fm fileExistsAtPath:[NSString stringWithFormat:@"%s/%@_b.metal", g_cache, row[0]]]) continue;
            if ([fm fileExistsAtPath:[NSString stringWithFormat:@"%s/%@.prefill", g_cache, row[0]]]) { skipped++; continue; }
            [todo addObject:@[key, row[0], row[1]]];
        }
    }
    if (!todo.count) {
        if (skipped) SCLOG("prefill: %lu variant(s) skipped (an earlier prefill stopped on them; see their .prefill markers)", (unsigned long)skipped);
        free(keys); return;
    }
    SCLOG("prefill: %lu journaled variant(s) of %ld shader(s) are not translated for this translator: translating them before play",
          (unsigned long)todo.count, nk);
    static const char *stage_label = "Translating the saved shaders";
    uint64_t t0 = now_ns(); NSUInteger translated = 0, other = 0, done = 0;
    fc26_sc_shader s = {0}; NSString *current = nil; int usable = 0;   /* rows come grouped by shader */
    for (NSArray *row in todo) @autoreleasepool {
        NSString *key = row[0], *variant = row[1];
        if (![key isEqualToString:current]) {
            fc26_sc_shader_free(&s); current = key;
            char why[96];
            usable = !fc26_sc_journal_get_shader(g_journal, key.UTF8String, &s, why, sizeof why);
            if (!usable && damaged++ < 8) SCLOG("prefill: journaled shader %s unusable (%s): skipped", key.UTF8String, why);
        }
        if (!usable) continue;
        NSDictionary *state = [NSJSONSerialization JSONObjectWithData:[row[2] dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
        if (![state isKindOfClass:NSDictionary.class]) { damaged++; continue; }
        NSMutableDictionary *answers = [NSMutableDictionary dictionary];
        for (NSString *k in @[@"tex", @"img", @"attr", @"fout"]) answers[k] = [state[k] isKindOfClass:NSDictionary.class] ? state[k] : @{};
        NSArray *local = [state[@"local"] isKindOfClass:NSArray.class] ? state[@"local"] : nil;
        NSString *mark = [NSString stringWithFormat:@"%s/%@.prefill", g_cache, variant];
        [NSData.data writeToFile:mark atomically:NO];   /* removed below; left behind if this translation stops the game */
        NSString *got = totk_rt_variant(key, s.stage, s.control, s.code, answers, local);
        unlink(mark.fileSystemRepresentation);
        if ([got isEqualToString:variant]) translated++;
        else if (got) { if (other++ < 8) SCLOG("prefill: %s served by %s (an existing variant matches its bind state)", variant.UTF8String, got.UTF8String); }
        if (++done % 16 == 0 || done == todo.count) runtime_boot_count(stage_label, done, todo.count);
    }
    fc26_sc_shader_free(&s); free(keys);
    double secs = (now_ns() - t0) / 1e9;
    SCLOG("prefill: %lu translated, %lu served by another variant, %lu unusable, %lu skipped, in %.1f s (%.1f ms each)",
          (unsigned long)translated, (unsigned long)other, (unsigned long)damaged, (unsigned long)skipped, secs, done ? secs * 1e3 / done : 0.0);
}

/* FC26_SHADER_WARM=all (default): the first shader use waits until the warm-up has compiled every cached shader and
   recorded pipeline, at most FC26_SHADER_WARM_TIMEOUT_S; "kit": only the kit's own waits (its first list here, its first
   world frame in hle_nvn.c). The warm-up runs before the game's first draw, so nothing it knows compiles during play. */
void fc26_shader_warm_gate(void) {
    if (layer_off()) return;
    int bad; const char *mode = getenv("FC26_SHADER_WARM"), *limit = getenv("FC26_SHADER_WARM_TIMEOUT_S");
    int all = fc26_sc_warm_all(mode, &bad);
    if (bad) SCLOG("FC26_SHADER_WARM=%s not understood (all | kit): all", mode);
    if (!all) return;
    int seconds = fc26_sc_warm_timeout_s(limit, &bad);
    if (bad) SCLOG("FC26_SHADER_WARM_TIMEOUT_S=%s not understood (1..3600): %d", limit, seconds);
    int ms = mtl_warm_wait(seconds * 1000);
    SCLOG("warm-up: the first shader use waited %d ms for every cached shader and recorded pipeline%s", ms ? ms - 1 : 0,
          ms > seconds * 1000 ? " (time limit: the rest goes on in the background)" : "");
}
