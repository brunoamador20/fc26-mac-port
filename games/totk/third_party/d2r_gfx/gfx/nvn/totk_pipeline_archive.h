// TOTK: the pipeline archive (2026-10-20). Pipelines are compiled once into GPU code and kept in Metal binary archives
// in the translation cache; later pipeline creations take their code from them instead of compiling.
// Why: iOS warmed every prepared pipeline at start and kept them all (about 450 MB of a 3.84 GB footprint on an
// iPhone 14, whose limit is 4 GB), because a pipeline met for the first time in play compiles on the device (50-700 ms
// hitches), and the system's own shader cache is cleared by reboots and updates. With valid archives the full warm-up
// is skipped (the pipeline lists are made, quickly, from the archives) and the rest is made when first drawn.
// - On everywhere; TOTK_PIPELINE_ARCHIVE=0 turns it off.
// - Folder pipelines/ in the cache: every written archive is a file of its own and is never written again; new pipelines
//   of a run go into a fresh archive that becomes the next file. (An archive opened from a file and serialized again
//   kept only what was added after opening it: 2,291 pipelines added in batches came back as 208, 2026-10-20.)
// - Valid for one OS version, GPU and translation chain (pipelines/identity.json); otherwise the folder is removed.
// Included by nvn_mtl.m after MLOG and g_dev.
#pragma once
#import <Metal/Metal.h>
#include <pthread.h>
#include <stdatomic.h>
#include "dmsh_chain.h"
#include "totk_shader_rt.h"

static NSArray<id<MTLBinaryArchive>> *g_par_read;   // the written files, for lookups
static id<MTLBinaryArchive> g_par_new;              // this run's additions, written as the next file
static pthread_mutex_t g_par_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_par_valid;                             // matching files were found: the full warm-up is not needed
static uint64_t g_par_added, g_par_unsaved, g_par_add_failed;
static _Atomic int g_par_saving;
/* A new file every 32 additions: opening an archive costs memory that grows about with the square of the pipelines in
   that file and is never given back, even when the archive is released (2026-10-20, a trivial shader on an M4: 32 per
   file 1 MB, 64 3 MB, 256 46 MB, 512 229 MB, 1,024 777 MB; Metal clones every pipeline description of the file into one
   flatbuffer in -[_MTLBinaryArchive getScriptsWithAIRNTObject:]). Many small files keep it near 1 MB per 32 pipelines. */
enum { PAR_SAVE_EVERY = 32 };
static _Atomic int par_filling;   // the background fill writes its own files (warm_fill_archive)
static __thread int par_on_fill_thread;   // set on that fill's own thread: it adds in place

static int par_enabled(void) {
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("TOTK_PIPELINE_ARCHIVE");
        on = !(e && !strcmp(e, "0"));
    }
    return on;
}
// The first run without valid archives: fill them in the background without keeping the pipelines (iOS; the full
// warm-up and the archive together passed the 4 GB limit). TOTK_PIPELINE_ARCHIVE_FILL=1 does the same on a Mac.
static int par_fill_light(void) {
#if TARGET_OS_IPHONE
    return 1;
#else
    const char *e = getenv("TOTK_PIPELINE_ARCHIVE_FILL"); return e && !strcmp(e, "1");
#endif
}
static NSString *par_dir(void) { return [totk_rt_dir() stringByAppendingPathComponent:@"pipelines"]; }
static NSString *par_stamp_path(void) { return [par_dir() stringByAppendingPathComponent:@"identity.json"]; }
static NSDictionary *par_identity(id<MTLDevice> dev) {
    return @{@"schema": @2, @"chain": @DMSH_CHAIN, @"gpu": dev.name ?: @"?",
             @"os": NSProcessInfo.processInfo.operatingSystemVersionString ?: @"?"};
}
static id<MTLBinaryArchive> par_new_archive(id<MTLDevice> dev, NSString *path, NSError **e) {
    MTLBinaryArchiveDescriptor *d = [MTLBinaryArchiveDescriptor new];
    if (path) d.url = [NSURL fileURLWithPath:path];
    return [dev newBinaryArchiveWithDescriptor:d error:e];
}
// Opens the archives once; nil when off. A folder of another OS version, GPU or chain is removed, and so is a file
// Metal cannot read.
static NSArray<id<MTLBinaryArchive>> *par_list(id<MTLDevice> dev) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        if (!par_enabled()) return;
        NSFileManager *fm = NSFileManager.defaultManager; NSError *e = nil;
        NSData *sd = [NSData dataWithContentsOfFile:par_stamp_path()];
        NSDictionary *stamp = sd ? [NSJSONSerialization JSONObjectWithData:sd options:0 error:nil] : nil;
        [fm removeItemAtPath:[totk_rt_dir() stringByAppendingPathComponent:@"pipelines.metalarchive"] error:nil];   // single-file layout of earlier tests
        [fm removeItemAtPath:[totk_rt_dir() stringByAppendingPathComponent:@"pipelines.json"] error:nil];
        NSMutableArray<id<MTLBinaryArchive>> *read = [NSMutableArray array]; uint64_t bytes = 0;
        if ([stamp isEqual:par_identity(dev)]) {
            for (NSString *name in [[fm contentsOfDirectoryAtPath:par_dir() error:nil] sortedArrayUsingSelector:@selector(compare:)]) {
                if (![name hasSuffix:@".metalarchive"]) continue;
                NSString *path = [par_dir() stringByAppendingPathComponent:name];
                id<MTLBinaryArchive> a = par_new_archive(dev, path, &e);
                if (a) { [read addObject:a]; bytes += [[fm attributesOfItemAtPath:path error:nil] fileSize]; }
                else { MLOG("管线存档：%s 读不了（%s），删掉", name.UTF8String, e.localizedDescription.UTF8String); [fm removeItemAtPath:path error:nil]; }
            }
        } else if ([fm fileExistsAtPath:par_dir()]) {
            MLOG("管线存档：系统版本、GPU 或翻译链变了，删掉重建");
            [fm removeItemAtPath:par_dir() error:nil];
        }
        [fm createDirectoryAtPath:par_dir() withIntermediateDirectories:YES attributes:nil error:nil];
        g_par_new = par_new_archive(dev, nil, &e);
        if (!g_par_new) { MLOG("【红】管线存档：建不了（%s），照旧", e.localizedDescription.UTF8String); return; }
        g_par_read = read; g_par_valid = read.count > 0;
        if (g_par_valid) MLOG("管线存档：已载入 %lu 个文件（%.1f MB，系统 %s），跳过全量预热，其余管线用到时从存档取",
                              (unsigned long)read.count, bytes / 1048576.0, [stamp[@"os"] UTF8String]);
        else MLOG("管线存档：没有可用的存档，这次%s", par_fill_light() ? "在后台把管线清单收进存档（不常驻）" : "全量预热并把管线收进存档");
    });
    pthread_mutex_lock(&g_par_mu);   // par_save_now replaces g_par_new and extends g_par_read
    NSArray *list = g_par_new ? [g_par_read arrayByAddingObject:g_par_new] : nil;
    pthread_mutex_unlock(&g_par_mu);
    return list;
}
static void par_note_failure(NSError *e) {
    if (g_par_add_failed++ < 4) MLOG("【红】管线存档：收不进去（%s）", e.localizedDescription.UTF8String);
}
// This run's additions become the next file (a temporary name, then renamed); they are looked up from that file from
// now on, and the following additions go into a fresh archive.
static BOOL par_save_now(id<MTLDevice> dev, const char *why, NSError **err) {
    uint64_t t0 = clock_gettime_nsec_np(CLOCK_UPTIME_RAW); NSError *e = nil; BOOL ok = NO;
    pthread_mutex_lock(&g_par_mu);
    uint64_t count = g_par_unsaved;
    NSString *path = [par_dir() stringByAppendingPathComponent:[NSString stringWithFormat:@"%016llx.metalarchive",
                                                                 (unsigned long long)clock_gettime_nsec_np(CLOCK_REALTIME)]];
    NSString *temp = [path stringByAppendingString:@".tmp"];
    if (g_par_new && count) {
        ok = [g_par_new serializeToURL:[NSURL fileURLWithPath:temp] error:&e];
        if (ok) ok = rename(temp.fileSystemRepresentation, path.fileSystemRepresentation) == 0;
        if (ok) {
            NSData *stamp = [NSJSONSerialization dataWithJSONObject:par_identity(dev) options:NSJSONWritingSortedKeys error:nil];
            [stamp writeToFile:par_stamp_path() atomically:YES];
            id<MTLBinaryArchive> written = par_new_archive(dev, path, nil), fresh = par_new_archive(dev, nil, nil);
            if (written && fresh) { g_par_read = [g_par_read arrayByAddingObject:written]; g_par_new = fresh; }
            g_par_unsaved = 0;
        } else unlink(temp.fileSystemRepresentation);
    }
    pthread_mutex_unlock(&g_par_mu);
    if (ok && (g_par_read.count % 16 == 1 || count < PAR_SAVE_EVERY)) {   // every 16th file, and the last one of a batch
        NSDictionary *a = [NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
        MLOG("管线存档：写入第 %lu 个文件，%llu 条管线（%s），%.2f MB，用时 %.2f s；共 %llu 条", (unsigned long)g_par_read.count,
             (unsigned long long)count, why, [a fileSize] / 1048576.0, (clock_gettime_nsec_np(CLOCK_UPTIME_RAW) - t0) / 1e9,
             (unsigned long long)g_par_added);
    }
    if (err) *err = e;
    return ok || !count;
}
// In the background. Metal's compiler service can drop the connection while it writes (XPC_ERROR_CONNECTION_INTERRUPTED,
// 2026-10-20): a failed write is tried again 30 s later, three times at most.
static void par_save_try(id<MTLDevice> dev, const char *why, int attempt) {
    if (!g_par_new || atomic_exchange(&g_par_saving, 1)) return;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, attempt > 1 ? 30 * (int64_t)NSEC_PER_SEC : 0),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSError *e = nil; BOOL ok = par_save_now(dev, why, &e);
        if (!ok) MLOG("%s管线存档：写不了（%s）%s", attempt < 3 ? "" : "【红】", e ? e.localizedDescription.UTF8String : "改名失败",
                      attempt < 3 ? "，30 秒后再试" : "，这次不再试，新管线够数时再写");
        atomic_store(&g_par_saving, 0);
        if (!ok && attempt < 3) par_save_try(dev, why, attempt + 1);
    });
}
static void par_save(id<MTLDevice> dev, const char *why) { par_save_try(dev, why, 1); }
static void par_added(id<MTLDevice> dev) {
    g_par_added++; g_par_unsaved++;
    if (g_par_unsaved >= PAR_SAVE_EVERY && !par_filling) par_save(dev, "游戏中新编的管线");
}
// Called for a pipeline the archives did not have (pso_new / cs_new in nvn_mtl.m), after it was compiled. Adding it
// compiles it once more for the archive, through the same Metal compiler service the game's own compiles use: added at
// once (even on a background queue) it made a world entry with 102 new pipelines take 1.7 s instead of 0.4 s on the
// Mac (2026-10-21). So additions wait in a list and are made one at a time only while the game is idle (in the world,
// no pipeline compiled for PAR_IDLE_NS; par_game_idle in nvn_mtl.m). The background fill adds in place (its own thread).
enum { PAR_IDLE_NS = 3000000000u };
static _Atomic uint64_t g_par_last_compile_ns;   // set by pso_new / cs_new when they compiled
static int par_game_idle(void);                  // nvn_mtl.m: in the world, warm-up done, no compile for PAR_IDLE_NS
static NSMutableArray *g_par_pending;             // MTLRenderPipelineDescriptor / MTLComputePipelineDescriptor copies
static _Atomic int g_par_draining;
static dispatch_queue_t par_queue(void) {
    static dispatch_queue_t q; static dispatch_once_t once;
    dispatch_once(&once, ^{ q = dispatch_queue_create("dm.nvn.pipeline-archive", dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL, QOS_CLASS_BACKGROUND, 0)); });
    return q;
}
static void par_add_now(id<MTLDevice> dev, id desc) {
    NSError *e = nil;
    pthread_mutex_lock(&g_par_mu);
    BOOL ok = [desc isKindOfClass:MTLRenderPipelineDescriptor.class] ? [g_par_new addRenderPipelineFunctionsWithDescriptor:desc error:&e]
                                                                      : [g_par_new addComputePipelineFunctionsWithDescriptor:desc error:&e];
    if (ok) par_added(dev);
    pthread_mutex_unlock(&g_par_mu);
    if (!ok) par_note_failure(e);
}
// Every second while additions wait: when the game is idle, add one, then look again at once.
static void par_drain(id<MTLDevice> dev) {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)NSEC_PER_SEC), par_queue(), ^{
        for (;;) {
            if (!par_game_idle()) { par_drain(dev); return; }
            id desc = nil;
            pthread_mutex_lock(&g_par_mu);
            if (g_par_pending.count) { desc = g_par_pending.firstObject; [g_par_pending removeObjectAtIndex:0]; }
            pthread_mutex_unlock(&g_par_mu);
            if (!desc) { atomic_store(&g_par_draining, 0); return; }
            @autoreleasepool { par_add_now(dev, desc); }
        }
    });
}
static void par_enqueue(id<MTLDevice> dev, id desc) {
    pthread_mutex_lock(&g_par_mu);
    if (!g_par_pending) g_par_pending = [NSMutableArray array];
    [g_par_pending addObject:desc];
    pthread_mutex_unlock(&g_par_mu);
    if (!atomic_exchange(&g_par_draining, 1)) par_drain(dev);
}
static void par_add_render(id<MTLDevice> dev, MTLRenderPipelineDescriptor *d) {
    if (!g_par_new) return;
    if (par_on_fill_thread) par_add_now(dev, d); else par_enqueue(dev, [d copy]);
}
static void par_add_compute(id<MTLDevice> dev, MTLComputePipelineDescriptor *d) {
    if (!g_par_new) return;
    if (par_on_fill_thread) par_add_now(dev, d); else par_enqueue(dev, [d copy]);
}
