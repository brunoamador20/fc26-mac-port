/* Breath of the Wild game-code patches (botw.md): exclusive loads with acquire, the real-time frame step, and the
   TOTK_JQ_CHECK diagnostics. The functions the shared runtime calls for the output size and keys 3 / 4 answer
   "not available" until BotW's own sites are found. */
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "game_patches.h"
#include "game_version.h"

/* Real-time frame step (TOTK_REALTIME=0: as shipped). ksys::VFR (singleton pointer main+0x2d1e170, built at main+0x183eb98)
   keeps one frame ratio at +0x3c: the frame's length in 30 fps frames. Every per-core step the game reads derives from it:
   delta frames (+0x108, about 1,500 readers) = time-speed multiplier x ratio, delta time (+0x138) = that x 1/30 s (+0x158).
   The per-frame update main+0x1c01180 sets the ratio from the present interval (interval / 2: 1.0 at the shipped 30 fps)
   and writes +0x3c only when it changes, so the game ran at twice its speed at 60 fps. Two of its instructions now take the
   ratio from the loader's data page after main, which the host refreshes at each present with the measured frame time x 30
   (the page layout of Tears of the Kingdom's patch: low float ratio, high float seconds):
     main+0x1c0120c  fcmp s1, s0       -> adrp x9, <data page>
     main+0x1c01214  b.eq #0x1c01220   -> ldr s1, [x9]
   and the store of s1 to +0x3c after them now runs every frame. The interval bookkeeping (+0x28 changed, +0x30 / +0x34
   interval ratio and interval, +0x38 / +0x40 previous) stays as shipped.
   One more reader steps by the interval itself instead of the ratio: a fade (0 -> 1 in 5 frames at 30 fps; main+0x1821548
   reads the VFR's interval, +0x48 per core) adds max(interval, 1) x 0.5 x 0.2 per frame. It now adds ratio x 0.2, the
   same value at the shipped 30 fps:
     main+0x1821568  ldr w8, [x8]               -> adrp x8, <data page>
     main+0x182156c  cmp w8, #0                 -> ldr s0, [x8]
     main+0x1821570  csinc w8, w8, wzr, ne      -> nop
     main+0x1821574  ucvtf s0, w8               -> nop
     main+0x1821588  fmul s0, s0, s11 (x 0.5)   -> nop
   (x8 is reloaded two instructions later, the flags are not read again.) MacNativeGames games/botw/scripts/
   verify_realtime_patch.py runs both with Unicorn. */
static _Atomic uint64_t *frame_step_data;
static uint8_t *frame_step_main;
static uint64_t last_present_ns, report_ns, report_frames;
static double frame_samples[5], report_seconds, report_game, report_short_ms, report_long_ms;
static unsigned frame_sample_count, frame_sample_next, report_short, report_long;
static _Atomic uint32_t pinned_step_us;
enum { VFR_INSTANCE = 0x2d1e170, VFR_RATIO = 0x3c, VFR_DELTA_TIME = 0x138 };

static int realtime_enabled(void) { const char *e = getenv("TOTK_REALTIME"); return !(e && !strcmp(e, "0")); }
static uint64_t frame_step_bits(float seconds) {
    float ratio = seconds * 30.0f; uint32_t lo, hi;
    memcpy(&lo, &ratio, 4); memcpy(&hi, &seconds, 4);
    return (uint64_t)lo | ((uint64_t)hi << 32);
}
/* Diagnostics (TOTK_INPUT_FILE "framestep <ms>"): pin the frame step to a fixed length, 0 back to real time. */
void runtime_frame_step_pin(double ms) {
    uint32_t us = ms > 0 ? (uint32_t)(ms * 1000.0 + 0.5) : 0;
    atomic_store(&pinned_step_us, us);
    if (frame_step_data && us) atomic_store_explicit(frame_step_data, frame_step_bits((float)(us / 1e6)), memory_order_release);
    if (!us) fprintf(stderr, "[botw] frame step back to real time\n");
    else fprintf(stderr, "[botw] frame step pinned at %.3f ms (ratio %.3f, diagnostics)%s\n", us / 1000.0, us / 1e6 * 30.0,
                 frame_step_data ? "" : " -- but the real-time patch is off, nothing changes");
}
/* Every 30 s one line: frames and their real time, the game time the steps added up to, what the game actually reads (the
   VFR's ratio and core 0's delta time), and the intervals outside 1/120..1/15 s with what clamping each of them on its own
   would have added or dropped. */
static void frame_step_report(uint64_t now_ns) {
    if (!report_ns) { report_ns = now_ns; return; }
    if (now_ns - report_ns < 30000000000ull) return;
    float ratio = -1, delta = -1;
    uint64_t vfr = *(const uint64_t *)(const void *)(frame_step_main + VFR_INSTANCE);
    if (vfr) {
        memcpy(&ratio, (const void *)(uintptr_t)(vfr + VFR_RATIO), 4);
        uint64_t p = *(const uint64_t *)(uintptr_t)(vfr + VFR_DELTA_TIME);
        if (p) memcpy(&delta, (const void *)(uintptr_t)p, 4);
    }
    double span = (double)(now_ns - report_ns) * 1e-9;
    char game[96];
    if (atomic_load(&pinned_step_us)) snprintf(game, sizeof game, "step pinned");
    else snprintf(game, sizeof game, "steps add up to %.2f s (%.4f of the frames' time)", report_game, report_seconds > 0 ? report_game / report_seconds : 0);
    fprintf(stderr, "[botw] real-time frame step: %llu frames in %.1f s (%.1f fps, %.2f ms apart on average), %s; the game's VFR ratio "
                    "%.3f, delta time %.2f ms; %u intervals under 1/120 s (clamping each: +%.0f ms), %u over 1/15 s (-%.0f ms)\n",
            (unsigned long long)report_frames, span, report_frames / span, report_frames ? report_seconds / report_frames * 1e3 : 0, game,
            ratio, delta * 1e3, report_short, report_short_ms, report_long, report_long_ms);
    report_ns = now_ns; report_frames = 0; report_seconds = report_game = report_short_ms = report_long_ms = 0; report_short = report_long = 0;
}
void runtime_frame_step_update(uint64_t now_ns) {
    if (!frame_step_data || !now_ns) return;
    frame_step_report(now_ns);
    uint64_t prev = last_present_ns;
    last_present_ns = now_ns;
    if (!prev) return;
    double dt = (double)(now_ns - prev) * 1e-9;
    if (dt > 0.25 || dt < 0.001) { frame_sample_count = frame_sample_next = 0; return; }
    report_frames++; report_seconds += dt;
    if (dt < 1.0 / 120.0) { report_short++; report_short_ms += (1.0 / 120.0 - dt) * 1e3; }
    if (dt > 1.0 / 15.0) { report_long++; report_long_ms += (dt - 1.0 / 15.0) * 1e3; }
    if (atomic_load_explicit(&pinned_step_us, memory_order_relaxed)) return;
    /* The raw intervals are averaged and the average is clamped, not each interval: at about 95 fps under the 120 Hz
       clock, intervals shorter than 1/120 s alternate with longer ones, and raising each short one to 1/120 s made the
       game run 6% fast (measured: botw.md). Averaged, the steps add up to the real time while the average stays inside
       1/120..1/15 s; a hitch is spread over the next frames instead of being cut. */
    frame_samples[frame_sample_next++ % 5] = dt;
    if (frame_sample_count < 5) frame_sample_count++;
    double sum = 0;
    for (unsigned i = 0; i < frame_sample_count; i++) sum += frame_samples[i];
    double step = sum / frame_sample_count;
    if (step < 1.0 / 120.0) step = 1.0 / 120.0;
    if (step > 1.0 / 15.0) step = 1.0 / 15.0;
    report_game += step;
    atomic_store_explicit(frame_step_data, frame_step_bits((float)step), memory_order_release);
}
static uint32_t adrp_reg(unsigned rd, uint64_t site, uint64_t target) {
    int64_t pages = (int64_t)(target >> 12) - (int64_t)(site >> 12);
    if (pages < -(1 << 20) || pages >= (1 << 20)) runtime_fail("real-time frame-step data outside ADRP range");
    uint32_t imm = (uint32_t)pages & 0x1fffff;
    return 0x90000000u | ((imm & 3u) << 29) | ((imm >> 2) << 5) | (rd & 31u);
}
static void patch_realtime(Module *m) {
    /* The loader reserved a writable page immediately after main's image; nothing else uses it in this game. */
    uint64_t data_off = (m->file_size + 0x3fff) & ~0x3fffULL;
    if (data_off + 0x4000 != m->size || data_off & 0xfff) runtime_fail("real-time frame-step page layout");
    /* Every word of both sequences, the replaced ones and their neighbours, must be the 1.6.0 original. */
    static const struct { uint32_t off, original; } check[] = {
        {0x1c0120cu, 0x1e202020u}, {0x1c01210u, 0x3900a008u}, {0x1c01214u, 0x54000060u}, {0x1c01218u, 0xbd003c01u},
        {0x1821564u, 0xf9400108u}, {0x1821568u, 0xb9400108u}, {0x182156cu, 0x7100011fu}, {0x1821570u, 0x1a9f1508u},
        {0x1821574u, 0x1e230100u}, {0x1821578u, 0x1e2c100bu}, {0x182157cu, 0xb0006f68u}, {0x1821580u, 0xbd409109u},
        {0x1821584u, 0xbd435ee1u}, {0x1821588u, 0x1e2b0800u}, {0x182158cu, 0x1e290800u},
    };
    for (size_t i = 0; i < sizeof check / sizeof *check; i++) {
        uint32_t w; memcpy(&w, m->base + check[i].off, 4);
        if (w != check[i].original) {
            fprintf(stderr, "[botw] real-time frame step main+%#x: found %08x expected %08x\n", check[i].off, w, check[i].original);
            runtime_fail("real-time frame step requires the 1.6.0 VFR update instructions");
        }
    }
    const uint64_t page = (uintptr_t)m->base + data_off;
    const uint32_t nop = 0xd503201fu;
    const struct { uint32_t off, word; } put[] = {
        {0x1c0120cu, adrp_reg(9, (uintptr_t)m->base + 0x1c0120c, page)}, {0x1c01214u, 0xbd400121u},   /* ldr s1, [x9] */
        {0x1821568u, adrp_reg(8, (uintptr_t)m->base + 0x1821568, page)}, {0x182156cu, 0xbd400100u},   /* ldr s0, [x8] */
        {0x1821570u, nop}, {0x1821574u, nop}, {0x1821588u, nop},
    };
    for (size_t i = 0; i < sizeof put / sizeof *put; i++) memcpy(m->base + put[i].off, &put[i].word, 4);
    frame_step_main = m->base;
    frame_step_data = (_Atomic uint64_t *)(void *)(m->base + data_off);
    atomic_store(frame_step_data, frame_step_bits(1.0f / 30.0f));
    fprintf(stderr, "[botw] real-time frame step: the VFR ratio and one interval-stepped fade follow the measured frame time "
                    "(%zu instructions, %zu verified); initial 33.33 ms, sampled at each present (TOTK_REALTIME=0: as shipped)\n",
            sizeof put / sizeof *put, sizeof check / sizeof *check);
}
/* Diagnostics (TOTK_JQ_CHECK=1): random crashes look like one job run twice (two threads in the same skinning job, a list
   item consumed twice). brk instructions replace a few instructions of sead::JobQueue::run (main+0x12c0dc0) and of the
   worker manager's wake (main+0x13a0150) and sync (main+0x13a03d0); the SIGTRAP handler (loader.c crash -> botw_jq_hook)
   does the replaced instruction and checks:
   - TAKE / DONE (job load, the instruction after its invoke): an index past the queue's count or total, and a job another
     thread is running at the same time;
   - SYNC_PRE / SYNC_POST (around the wait on a worker's idle event): the wait returning while that worker still runs a
     queue, with the event's state before the wait (2 = already signaled: a stale signal; 1 = woken while busy);
   - SYNC_END: any worker still busy or with queues in its ring when the sync returns (the assertion the release build
     compiled out: its loads of each worker's status are still there);
   - WAKE_SKIP: a worker with an empty ring whose idle event the wake leaves alone while that worker runs a queue. */
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ucontext.h>
uint32_t runtime_thread_current_handle(void);
enum { JQ_TAKE, JQ_DONE, SYNC_PRE, SYNC_POST, SYNC_END, WAKE_SKIP, JQ_SITES };
static const struct { uint32_t off, word; const char *what; } g_jq_site[JQ_SITES] = {
    {0x12c1010u, 0xf8686920u, "job load (ldr x0, [x9, x8])"},
    {0x12c1020u, 0x9100075au, "after a job (add x26, x26, #1)"},
    {0x13a0438u, 0xaa1403e0u, "sync: before the idle wait (mov x0, x20)"},
    {0x13a0440u, 0x3607ff20u, "sync: after the idle wait (tbz w0, #0)"},
    {0x13a0508u, 0xb9009a7fu, "sync: end (str wzr, [x19, #0x98])"},
    {0x13a0378u, 0x34000169u, "wake: ring check (cbz w9)"},
};
static uint8_t *g_jq_main; static int g_jq_on;
static struct { _Atomic uint64_t thread, job, jq, since; _Atomic uint32_t index, handle; } g_jq_run[64];
static _Atomic uint64_t g_jq_n, g_jq_bad, g_jq_dup, g_sync_waits, g_sync_busy, g_sync_end_busy, g_wake_skip_busy;
static struct { uint32_t state, status, ring; uint64_t jq; } g_pre[64];   /* per thread slot (no __thread: its first use may allocate) */
/* Exclusive loads with acquire (TOTK_EXCL_ACQUIRE, botw.md): sead's spin locks in this game take the lock with a plain
   ldxr / stxr and only put a dmb ish before the release, so nothing orders the loads inside the critical section after the
   lock is taken. The ARMv8 model lets such a load be satisfied before the ldxr observes the lock free (a control dependency
   does not order loads); the Switch's Cortex-A57 rarely does it, Apple's cores do: two threads read the same "next job"
   index of a sead::JobQueue a few microseconds apart and run the same job twice (TOTK_JQ_CHECK). Every plain ldxr / ldxp
   that opens a real exclusive window (a store-exclusive on the same base register within 16 instructions) gets the acquire
   bit (ldaxr / ldaxp): one bit, the same registers and size, only stronger ordering. */
static int excl_ld(uint32_t w) { return (w & 0x3ffffc00u) == 0x085f7c00u || (w & 0xbfff8000u) == 0x887f0000u; }   /* ldxr{b,h} / ldxp */
static int excl_st(uint32_t w) { return (w & 0x3fe07c00u) == 0x08007c00u || (w & 0xbfe00000u) == 0x88200000u; }   /* st{l}xr{b,h} / st{l}xp */
static unsigned excl_acquire(uint8_t *code, size_t n) {
    unsigned done = 0; uint32_t *w = (uint32_t *)(void *)code; size_t words = n / 4;
    for (size_t i = 0; i < words; i++) {
        if (!excl_ld(w[i])) continue;
        uint32_t rn = (w[i] >> 5) & 31;
        for (size_t j = i + 1; j < words && j <= i + 16; j++) if (excl_st(w[j]) && ((w[j] >> 5) & 31) == rn) { w[i] |= 0x8000u; done++; break; }
    }
    return done;
}
void runtime_game_patches(Module *m) {
    fprintf(stderr, "[botw] %s game-code patches\n", TOTK_GAME_VERSION);
    if (realtime_enabled()) patch_realtime(m);
    else fprintf(stderr, "[botw] real-time frame step off (TOTK_REALTIME=0): the game advances by its present interval\n");
    { const char *a = getenv("TOTK_EXCL_ACQUIRE");
      if (!a || strcmp(a, "0")) {
          unsigned t = excl_acquire(m->base, m->text_end), p = excl_acquire(m->base + m->patch_off, m->file_size - m->patch_off);
          fprintf(stderr, "[botw] exclusive loads with acquire: %u in the code, %u in the rewriter's patch area (TOTK_EXCL_ACQUIRE=0: as shipped)\n", t, p);
      } else fprintf(stderr, "[botw] exclusive loads as shipped (TOTK_EXCL_ACQUIRE=0)\n"); }
    const char *e = getenv("TOTK_JQ_CHECK"); if (!e || !*e || !strcmp(e, "0")) return;
    for (int i = 0; i < JQ_SITES; i++) { uint32_t w; memcpy(&w, m->base + g_jq_site[i].off, 4);
        if (w != g_jq_site[i].word) { fprintf(stderr, "[botw] TOTK_JQ_CHECK: main+%#x is %08x, not %08x (%s): not armed\n", g_jq_site[i].off, w, g_jq_site[i].word, g_jq_site[i].what); return; } }
    for (int i = 0; i < JQ_SITES; i++) { uint32_t b = 0xd4200000u | ((0x7a1u + (uint32_t)i) << 5); memcpy(m->base + g_jq_site[i].off, &b, 4); }
    g_jq_main = m->base; g_jq_on = 1;
    fprintf(stderr, "[botw] TOTK_JQ_CHECK: job-queue and worker sync checks armed at %d sites\n", JQ_SITES);
}
static int jq_slot(uint64_t th) {
    for (int k = 0; k < 64; k++) if (atomic_load(&g_jq_run[k].thread) == th) return k;
    for (int k = 0; k < 64; k++) { uint64_t z = 0; if (atomic_compare_exchange_strong(&g_jq_run[k].thread, &z, th)) return k; }
    return -1;
}
static double jq_ms(uint64_t since) { static mach_timebase_info_data_t tb; if (!tb.denom) mach_timebase_info(&tb); return since ? (double)(mach_absolute_time() - since) * tb.numer / tb.denom / 1e6 : -1; }
#define U32(a) (*(const uint32_t *)(uintptr_t)(a))
#define U64(a) (*(const uint64_t *)(uintptr_t)(a))
int botw_jq_hook(void *context) {   /* SIGTRAP from loader.c crash(): 1 = it was one of ours, handled */
    if (!g_jq_on) return 0;
    ucontext_t *u = context; uint64_t pc = u->uc_mcontext->__ss.__pc, *x = u->uc_mcontext->__ss.__x;
    int site = -1; for (int i = 0; i < JQ_SITES; i++) if (pc == (uintptr_t)g_jq_main + g_jq_site[i].off) site = i;
    if (site < 0) return 0;
    uint64_t th = 0; pthread_threadid_np(NULL, &th); uint32_t h = runtime_thread_current_handle();
    uint64_t next_pc = pc + 4;
    switch (site) {
    case JQ_TAKE: {
        int k = jq_slot(th);
        uint64_t jq = x[21], job = U64(x[9] + x[8]); uint32_t i = (uint32_t)x[25];
        uint32_t count = U32(jq + 0x80), total = U32(jq + 0x90), next = U32(jq + 0x94);
        x[0] = job; atomic_fetch_add(&g_jq_n, 1);
        if ((i >= count || i >= total) && atomic_fetch_add(&g_jq_bad, 1) < 40)
            fprintf(stderr, "[jq-check] thread %#x runs index %u of queue %#llx: count %u total %u next %u end %lld (job %#llx)\n",
                    h, i, (unsigned long long)jq, count, total, next, (long long)x[22], (unsigned long long)job);
        for (int j = 0; j < 64; j++) if (j != k && job && atomic_load(&g_jq_run[j].job) == job && atomic_fetch_add(&g_jq_dup, 1) < 40)
            fprintf(stderr, "[jq-check] job %#llx index %u of queue %#llx started by thread %#x while thread %#x runs it (index %u of queue %#llx, for %.3f ms); count %u total %u next %u\n",
                    (unsigned long long)job, i, (unsigned long long)jq, h, atomic_load(&g_jq_run[j].handle), atomic_load(&g_jq_run[j].index),
                    (unsigned long long)atomic_load(&g_jq_run[j].jq), jq_ms(atomic_load(&g_jq_run[j].since)), count, total, next);
        if (k >= 0) { atomic_store(&g_jq_run[k].jq, jq); atomic_store(&g_jq_run[k].index, i); atomic_store(&g_jq_run[k].handle, h);
                      atomic_store(&g_jq_run[k].since, mach_absolute_time()); atomic_store(&g_jq_run[k].job, job); }
        break; }
    case JQ_DONE: {
        int k = jq_slot(th); x[26] += 1; if (k >= 0) atomic_store(&g_jq_run[k].job, 0);
        uint64_t n = atomic_load(&g_jq_n);
        if ((n & 0x3ffff) == 0)
            fprintf(stderr, "[jq-check] %llu jobs run, %llu past the count / total, %llu run twice at once; %llu sync waits, %llu returned while the worker ran, %llu syncs ended with a worker busy, %llu wakes left a busy worker's idle event\n",
                    (unsigned long long)n, (unsigned long long)atomic_load(&g_jq_bad), (unsigned long long)atomic_load(&g_jq_dup),
                    (unsigned long long)atomic_load(&g_sync_waits), (unsigned long long)atomic_load(&g_sync_busy),
                    (unsigned long long)atomic_load(&g_sync_end_busy), (unsigned long long)atomic_load(&g_wake_skip_busy));
        break; }
    case SYNC_PRE: {   /* x20 = worker + 0x170 (its idle event) */
        uint64_t w = x[20] - 0x170; int k = jq_slot(th);
        if (k >= 0) { g_pre[k].state = U32(x[20]); g_pre[k].status = U32(w + 0x100); g_pre[k].jq = U64(w + 0x130); g_pre[k].ring = U32(w + 0x120); }
        x[0] = x[20]; break; }
    case SYNC_POST: {
        uint64_t w = x[20] - 0x170; int k = jq_slot(th);
        if (x[0] & 1) {
            __typeof__(g_pre[0]) pre = {0}; if (k >= 0) pre = g_pre[k];
            atomic_fetch_add(&g_sync_waits, 1);
            uint32_t status = U32(w + 0x100); uint64_t jq = U64(w + 0x130);
            if ((status != 0 || jq != 0) && atomic_fetch_add(&g_sync_busy, 1) < 40)
                fprintf(stderr, "[jq-check] sync (thread %#x): the wait on worker %#llx (core %u) returned while it runs queue %#llx (status %u, ring %u, event %u); before the wait: event %u, status %u, queue %#llx, ring %u\n",
                        h, (unsigned long long)w, U32(w + 0xfc), (unsigned long long)jq, status, U32(w + 0x120), U32(x[20]),
                        pre.state, pre.status, (unsigned long long)pre.jq, pre.ring);
        } else next_pc = (uintptr_t)g_jq_main + 0x13a0424u;
        break; }
    case SYNC_END: {   /* x19 = the worker manager */
        uint64_t mgr = x[19]; uint32_t n = U32(mgr + 0x78); uint64_t arr = U64(mgr + 0x80);
        for (uint32_t i = 0; i < n && i < 8; i++) { uint64_t w = U64(arr + 8 * i); uint32_t status = U32(w + 0x100), ring = U32(w + 0x120); uint64_t jq = U64(w + 0x130);
            if ((status != 0 || ring != 0 || jq != 0) && atomic_fetch_add(&g_sync_end_busy, 1) < 40)
                fprintf(stderr, "[jq-check] sync (thread %#x) returns while worker %u (core %u) has status %u, queue %#llx, ring %u, idle event %u\n",
                        h, i, U32(w + 0xfc), status, (unsigned long long)jq, ring, U32(w + 0x170)); }
        *(uint32_t *)(uintptr_t)(mgr + 0x98) = 0; break; }
    case WAKE_SKIP: {  /* x20 = the worker, w9 = its ring count */
        uint64_t w = x[20];
        if ((uint32_t)x[9] == 0) {
            uint32_t status = U32(w + 0x100); uint64_t jq = U64(w + 0x130);
            if ((status != 0 || jq != 0) && atomic_fetch_add(&g_wake_skip_busy, 1) < 40)
                fprintf(stderr, "[jq-check] wake (thread %#x): worker core %u has an empty ring but runs queue %#llx (status %u, idle event %u): its idle event stays as it is\n",
                        h, U32(w + 0xfc), (unsigned long long)jq, status, U32(w + 0x170));
            next_pc = (uintptr_t)g_jq_main + 0x13a03a4u;
        }
        break; }
    }
    u->uc_mcontext->__ss.__pc = next_pc; return 1;
}
#undef U32
#undef U64
int runtime_output_res(unsigned *w, unsigned *h) { (void)w; (void)h; return 0; }
uint64_t runtime_output_res_extra_bytes(void) { return 0; }
int runtime_output_res_toggle(void) { return 0; }
int runtime_output_mode_cycle(void) { fprintf(stderr, "[botw] key 3: no 2K modes yet\n"); return 0; }
float runtime_aspect_now(void) { return 0; }
int runtime_aspect_toggle(void) { return 0; }
