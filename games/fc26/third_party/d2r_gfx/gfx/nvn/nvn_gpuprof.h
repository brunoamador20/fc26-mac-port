/* Paired, relaxed Metal 4 encoder timestamps adapted from nxnative
 * Copyright (c) 2026 seedds. MIT: ../../LICENSE.nxnative.
 * FC26: a fresh heap per segment, captured by its completion handler; render
 * timestamp packets execute on the real encoder's thread. No queue/barrier,
 * segment splitting, dispatch reuse or render-stream policy changes.
 * DM_NVN_GPUPROF=first-last; DM_NVN_GPUPROF_FILE=/absolute/file.tsv.
 * `flag gpuprof 600` starts at the next submission boundary.
 * Off: no heap, Metal calls, file access or per-draw measurement work.
 */
enum { GP_MAX = 4096 };
typedef struct {
    uint64_t frame, pass, draw0;
    uint32_t w, h, fmt[8], depth, nc, draws, copies, dispatches;
    char kind, key[12];
} gp_label;
static _Atomic int g_gp_request = -1;
static _Atomic int g_gp_enabled;
static pthread_mutex_t g_gp_file_mu = PTHREAD_MUTEX_INITIALIZER;
static _Thread_local int g_gp_cur = -1;
static int g_gp_n, g_gp_dropped;
static long g_gp_first = -1, g_gp_last = -1;
static id<MTL4CounterHeap> g_gp_heap;
static _Thread_local __unsafe_unretained id g_gp_encoder;
static gp_label g_gp_labels[GP_MAX / 2];
static _Atomic uint64_t g_cur_frame;
static uint64_t g_stat_draw, g_stat_pass;
static void gp_config(void) {
    static int initialized;
    if (!initialized) {
        initialized = 1;
        const char *e = getenv("DM_NVN_GPUPROF");
        if (e) { g_gp_first = atol(e); const char *end = strchr(e, '-'); g_gp_last = end ? atol(end + 1) : g_gp_first; }
    }
    int frames = atomic_exchange_explicit(&g_gp_request, -1, memory_order_relaxed);
    if (frames >= 0) {
        g_gp_first = frames ? (long)atomic_load(&g_cur_frame) + 1 : -1;
        g_gp_last = g_gp_first + frames - 1;
        MLOG("[gpuprof] requested %d frames, range %ld..%ld", frames, g_gp_first, g_gp_last);
    }
    long f = (long)atomic_load(&g_cur_frame);
    g_gp_enabled = g_gp_first >= 0 && f >= g_gp_first && f <= g_gp_last;
}
/* Metadata belongs to the replay thread, including streamed draws. The worker
 * receives only the retained heap and index, never reads mutable labels. */
static int gp_prepare(char kind, MTL4RenderPassDescriptor *d) {
    if (!g_gp_enabled) return -1;
    if (g_gp_cur >= 0) MDIE("GPUPROF: overlapping encoder metadata");
    if (g_gp_n == GP_MAX / 2) { g_gp_dropped++; return -1; }
    if (!g_gp_heap) {
        MTL4CounterHeapDescriptor *hd = [MTL4CounterHeapDescriptor new];
        hd.type = MTL4CounterHeapTypeTimestamp; hd.count = GP_MAX;
        NSError *error = nil;
        g_gp_heap = [g_dev newCounterHeapWithDescriptor:hd error:&error];
        if (!g_gp_heap) { MLOG("【红】GPUPROF heap: %s", error.description.UTF8String); g_gp_enabled = 0; return -1; }
    }
    int i = g_gp_n++; gp_label *p = &g_gp_labels[i]; memset(p, 0, sizeof *p);
    p->kind = kind; p->frame = atomic_load(&g_cur_frame); p->pass = g_stat_pass; p->draw0 = g_stat_draw;
    if (d) {
        for (int c = 0; c < 8; c++) { MTLRenderPassColorAttachmentDescriptor *a = d.colorAttachments[c];
            if (!a.texture) continue;
            p->fmt[c] = (uint32_t)a.texture.pixelFormat; p->nc++;
            if (!p->w) { p->w = (uint32_t)MAX(a.texture.width >> a.level, 1); p->h = (uint32_t)MAX(a.texture.height >> a.level, 1); }
        }
        MTLRenderPassDepthAttachmentDescriptor *z = d.depthAttachment;
        if (z.texture) { p->depth = (uint32_t)z.texture.pixelFormat;
            if (!p->w) { p->w = (uint32_t)MAX(z.texture.width >> z.level, 1); p->h = (uint32_t)MAX(z.texture.height >> z.level, 1); }
        }
    }
    g_gp_cur = i; return i;
}
static void gp_stamp(id e, char kind, id<MTL4CounterHeap> heap, int index, int end) {
    if (kind == 'R' || kind == 'O') [(id<MTL4RenderCommandEncoder>)e writeTimestampWithGranularity:MTL4TimestampGranularityRelaxed afterStage:end ? MTLRenderStageFragment : MTLRenderStageVertex intoHeap:heap atIndex:index];
    else [(id<MTL4ComputeCommandEncoder>)e writeTimestampWithGranularity:MTL4TimestampGranularityRelaxed intoHeap:heap atIndex:index];
}
static void gp_begin(id e, char kind, MTL4RenderPassDescriptor *d) {
    if (!e) return;
    int i = gp_prepare(kind, d); if (i >= 0) { g_gp_encoder = e; gp_stamp(e, kind, g_gp_heap, 2 * i, 0); }
}
static int gp_end(id e) {
    if (g_gp_cur < 0 || e != g_gp_encoder) return -1;
    int i = g_gp_cur; gp_label *p = &g_gp_labels[i];
    p->draws = p->kind == 'O' ? 1 : (uint32_t)(g_stat_draw - p->draw0);
    g_gp_cur = -1;
    /* Metal does not write an after-fragment timestamp for a clear-only pass
       (proved on M1: start is valid, end stays zero). Its end is instead marked
       on the command buffer immediately AFTER endEncoding, including stores. */
    if (p->kind == 'R' && !p->draws) return 2 * i + 1;
    gp_stamp(e, p->kind, g_gp_heap, 2 * i + 1, 1); return -1;
}
static void gp_clear_end(id<MTL4CommandBuffer> cb, int index) {
    if (index >= 0) [cb writeTimestampIntoHeap:g_gp_heap atIndex:(NSUInteger)index];
}
/* For copy/compute encoders, record the first texture destination. Buffer-only
 * encoders have no image dimensions or pixel format (zero in the capture). */
static void gp_texture(id e, id<MTLTexture> t) {
    if (g_gp_cur < 0 || e != g_gp_encoder || !t) return;
    gp_label *p = &g_gp_labels[g_gp_cur]; if (p->w) return;
    p->w = (uint32_t)t.width; p->h = (uint32_t)t.height; p->fmt[0] = (uint32_t)t.pixelFormat;
}
static void gp_note_key(const char *key) {
    if (g_gp_cur < 0 || !key) return;
    gp_label *p = &g_gp_labels[g_gp_cur];
    if (!p->key[0]) { memcpy(p->key, key, 8); p->key[8] = 0; }
}
static void gp_finish(TotkCommitOptions *options) {
    if (!g_gp_heap) return;
    if (g_gp_cur >= 0) MDIE("GPUPROF: commit with an open encoder");
    id<MTL4CounterHeap> heap = g_gp_heap; int n = g_gp_n, dropped = g_gp_dropped;
    gp_label *labels = malloc((size_t)n * sizeof *labels);
    if (!labels) MDIE("GPUPROF: label allocation failed");
    memcpy(labels, g_gp_labels, (size_t)n * sizeof *labels);
    g_gp_heap = nil; g_gp_n = g_gp_dropped = 0;
    double hz = (double)[g_dev queryTimestampFrequency];
    [options addFeedbackHandler:^(id<MTL4CommitFeedback> feedback) {
        @autoreleasepool {
            NSData *data = [heap resolveCounterRange:NSMakeRange(0, 2 * n)];
            /* Use the SDK entry type rather than assume its byte layout. */
            const MTL4TimestampHeapEntry *t = data.bytes;
            if (feedback.error || hz <= 0 || data.length < (NSUInteger)(2 * n) * sizeof *t) {
                MLOG("【红】GPUPROF: invalid results (%s)", feedback.error.description.UTF8String); free(labels); return;
            }

            pthread_mutex_lock(&g_gp_file_mu);
            const char *path = getenv("DM_NVN_GPUPROF_FILE"); FILE *file = path ? fopen(path, "a") : NULL;
            if (!file) MLOG("【红】GPUPROF: output unavailable (set DM_NVN_GPUPROF_FILE)");
            int invalid = 0;
            for (int i = 0; i < n; i++) {
                uint64_t a = t[2*i].timestamp, b = t[2*i+1].timestamp;
                if (!a || !b || b < a) {
                    static unsigned invalid_reported;
                    if (invalid_reported++ < 16) {
                        const gp_label *p = &labels[i];
                        MLOG("[gpuprof-invalid] frame %llu kind %c draws %u %ux%u key %s begin %llu end %llu",
                            (unsigned long long)p->frame, p->kind, p->draws, p->w, p->h, p->key,
                            (unsigned long long)a, (unsigned long long)b);
                    }
                    invalid++; continue;
                }
                const gp_label *p = &labels[i];
                if (file) fprintf(file, "%llu\t%llu\t%c\t%.6f\t%u\t%u\t%u\t%u,%u,%u,%u,%u,%u,%u,%u\t%u\t%u\t%u\t%u\t%s\n",
                    (unsigned long long)p->frame, (unsigned long long)p->pass, p->kind, (b-a)/hz*1e3,
                    p->draws, p->w, p->h, p->fmt[0],p->fmt[1],p->fmt[2],p->fmt[3],p->fmt[4],p->fmt[5],p->fmt[6],p->fmt[7],
                    p->depth, p->nc, p->copies, p->dispatches, p->key[0] ? p->key : "-");
            }
            if (file) fclose(file);
            MLOG("[gpuprof] frame %llu: %d encoders, dropped %d, invalid %d", (unsigned long long)labels[0].frame, n, dropped, invalid);
            pthread_mutex_unlock(&g_gp_file_mu); free(labels);
        }
    }];
}

/* The presentation command buffer has its own thread and allocator. Use its
 * feedback span (including the copy to the window and overlays), without
 * touching replay-thread metadata. P is always host presentation work. */
static void gp_queue_report(TotkCommitOptions *options, char kind, uint64_t frame,
                              uint32_t w, uint32_t h, uint32_t fmt, uint32_t draws, uint32_t copies, uint32_t dispatches) {
    if (!atomic_load(&g_gp_enabled)) return;
    [options addFeedbackHandler:^(id<MTL4CommitFeedback> f) {
        if (f.error || f.GPUEndTime < f.GPUStartTime) return;
        pthread_mutex_lock(&g_gp_file_mu);
        const char *path = getenv("DM_NVN_GPUPROF_FILE"); FILE *file = path ? fopen(path, "a") : NULL;
        if (file) { fprintf(file, "%llu\t0\t%c\t%.6f\t%u\t%u\t%u\t%u,0,0,0,0,0,0,0\t0\t1\t%u\t%u\t%s\n",
            (unsigned long long)frame, kind, (f.GPUEndTime-f.GPUStartTime)*1e3, draws, w, h, fmt, copies, dispatches, kind == 'P' ? "present" : "upload"); fclose(file); }
        pthread_mutex_unlock(&g_gp_file_mu);
    }];
}
