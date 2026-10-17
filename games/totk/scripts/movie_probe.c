/* Probe for the host VP9 movie::Decoder (runtime/movie_host.c) through its entries, driven the way main's movie player
   drives the library (main+0x240d570 event loop, +0x240e118 feeding, +0x240dc78 frame fetch): every VP9 frame of an IVF
   file (the blood-moon cutscene, ffmpeg -c copy) goes in, every output must equal ffmpeg's own VP9 decode (packed NV12,
   a decoder independent of libvpx) byte for byte, outputs are held until all output slots are taken so inputs have to
   wait, end of stream comes out last. Also: client events (format changed before the first output), output format keys,
   output size, error statuses, decoders of other types left to the original code, destruction. Stand-ins replace the
   guest's movie::Buffer, movie::MediaData and nn::os events.
   Two runs: "buffers" hands frames over as soon as they are decoded (TOTK_MOVIE_PACE=0) and holds all output slots;
   "paced" runs a fake clock at 95 game frames per second (movie_host_tick at every frame), with 3 s at 15 frames per
   second in between (a loading hitch): every frame handed over is at most two frame periods late, at most one per game
   frame, frames are dropped only in the slow part, none is late once the game is fast again (no catch-up), and the
   17.3 s movie takes 17.3 s.
   usage: movie-probe <frames.ivf> <reference.nv12> <width> <height> <frames> buffers|paced
   TOTK_PROBE_NEGATIVE=1 (U and V swapped), =2 (no format-changed event) and =3 (paced run without pacing) must fail. */
#include "../runtime/movie_host.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Noreturn void runtime_fail(const char *s) { fprintf(stderr, "movie probe: runtime_fail: %s\n", s); exit(3); }
void *runtime_symbol(const char *name) { (void)name; return NULL; }
static int checks;
static void need(int c, const char *fmt, ...) {
    checks++; if (c) return;
    va_list ap; va_start(ap, fmt); fprintf(stderr, "movie probe: FAILED: "); vfprintf(stderr, fmt, ap); fputc('\n', stderr); va_end(ap); exit(1);
}

/* ---- stand-ins for the guest ---- */
typedef struct { int offset, size; void *data; size_t cap; } Buf;
static void buf_set_range(void *b, int o, int s) { ((Buf *)b)->offset = o; ((Buf *)b)->size = s; }
static void buf_set_data(void *b, void *d, size_t c) { ((Buf *)b)->data = d; ((Buf *)b)->cap = c; }
static void *buf_base(const void *b) { return ((const Buf *)b)->data; }
static size_t buf_capacity(const void *b) { return ((const Buf *)b)->cap; }
typedef struct { char key[32]; int kind, v[4]; const char *s; } Entry;
typedef struct { Entry e[32]; int n; } Md;
static Entry *md_slot(Md *m, const char *k) { for (int i = 0; i < m->n; i++) if (!strcmp(m->e[i].key, k)) return &m->e[i]; if (m->n == 32) runtime_fail("md full"); Entry *e = &m->e[m->n++]; snprintf(e->key, sizeof e->key, "%s", k); return e; }
static const Entry *md_get(const Md *m, const char *k) { for (int i = 0; i < m->n; i++) if (!strcmp(m->e[i].key, k)) return &m->e[i]; return NULL; }
static bool md_find_int32(const void *m, const char *k, int *v) { const Entry *e = md_get(m, k); if (!e || e->kind != 1) return false; *v = e->v[0]; return true; }
static bool md_find_string(const void *m, const char *k, const char **v) { const Entry *e = md_get(m, k); if (!e || e->kind != 2) return false; *v = e->s; return true; }
static void md_set_int32(void *m, const char *k, int v) { Entry *e = md_slot(m, k); e->kind = 1; e->v[0] = v; }
static void md_set_rect(void *m, const char *k, int l, int t, int r, int b) { Entry *e = md_slot(m, k); e->kind = 3; e->v[0] = l; e->v[1] = t; e->v[2] = r; e->v[3] = b; }
static void md_set_string(void *m, const char *k, const char *v) { Entry *e = md_slot(m, k); e->kind = 2; e->s = v; }
typedef struct { int count; } Event;
static void signal_event(void *ev) { ((Event *)ev)->count++; }
/* the library's own code, for decoders the host leaves to it */
static int orig_ctor_calls, orig_d0_calls, orig_start_calls;
static void orig_ctor(void *obj, int t, int f, int m, int p) { (void)t; (void)f; (void)m; (void)p; orig_ctor_calls++; ((void **)obj)[0] = (void *)0x1; ((void **)obj)[1] = (void *)0x2; }
static void orig_d0(void *obj) { orig_d0_calls++; (void)obj; }
static int orig_start(void *obj) { (void)obj; orig_start_calls++; return 0x7777; }
static int orig_other(void) { return 0x7776; }
static char fake_vtable[0xa8];
static uint64_t fake_ns = 1000000000ull;
static uint64_t fake_clock(void) { return fake_ns; }

/* ---- entries ---- */
typedef void (*ctor_t)(void *, int, int, int, int); typedef void (*obj_t)(void *);
typedef int (*md_t)(void *, void *); typedef int (*int_t)(void *); typedef int (*pp_t)(void *, int *, int *);
typedef int (*ib_t)(void *, int, void *); typedef int (*send_t)(void *, int, int, int, int64_t, unsigned);
typedef int (*acq_t)(void *, int *, int64_t *, unsigned *, int *); typedef int (*i_t)(void *, int);
#define E(t, w) ((t)movie_host_entry(w))

static uint8_t *read_file(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc((size_t)sz); if (!b || fread(b, 1, (size_t)sz, f) != (size_t)sz) { perror(path); exit(2); }
    fclose(f); *n = (size_t)sz; return b;
}

int main(int argc, char **argv) {
    if (argc != 7 || (strcmp(argv[6], "buffers") && strcmp(argv[6], "paced"))) { fprintf(stderr, "usage: movie-probe <frames.ivf> <reference.nv12> <width> <height> <frames> buffers|paced\n"); return 2; }
    int W = atoi(argv[3]), H = atoi(argv[4]), NF = atoi(argv[5]); size_t fb = (size_t)W * H * 3 / 2;
    const int paced = !strcmp(argv[6], "paced"); const uint64_t TICK = 1000000000ull / 95;
    const char *neg = getenv("TOTK_PROBE_NEGATIVE");   /* 3: the paced run with pacing off must fail */
    setenv("TOTK_MOVIE_PACE", paced && !(neg && !strcmp(neg, "3")) ? "1" : "0", 1); movie_host_set_clock(fake_clock);
    int64_t t_first = -1, pts_first = 0, late_max = 0, late_fast_max = 0; int ticks = 0, delivered = 0, last_k = -1;
    int64_t *alltimes = calloc((size_t)NF, sizeof *alltimes); int nall = 0;
    MovieGuest api = {signal_event, buf_set_range, buf_set_data, buf_base, buf_capacity, md_find_int32, md_find_string,
                      md_set_int32, md_set_rect, md_set_string, fake_vtable + 0x10, {0}};
    for (int i = 0; i < MOVIE_ENTRIES; i++) api.orig[i] = (void *)orig_other;
    api.orig[MOVIE_CTOR] = (void *)orig_ctor; api.orig[MOVIE_D0] = (void *)orig_d0; api.orig[MOVIE_START] = (void *)orig_start;
    movie_host_set_guest(&api);
    size_t ivf_n, ref_n; uint8_t *ivf = read_file(argv[1], &ivf_n), *ref = read_file(argv[2], &ref_n);
    need(ivf_n > 32 && !memcmp(ivf, "DKIF", 4) && !memcmp(ivf + 8, "VP90", 4), "IVF header");
    need(ref_n == fb * (size_t)NF, "reference holds %d frames of %zu bytes", NF, fb);

    /* names: every entry is reachable by its mangled name, other names are not taken */
    need(runtime_movie_override("_ZN5movie7Decoder5StartEv") == movie_host_entry(MOVIE_START), "override by name");
    need(runtime_movie_override("_ZN5movie9Extractor4ReadEPNS_6BufferE") == NULL, "extractor left alone");

    /* a decoder of another type goes to the library, and so do its methods */
    void *other[2] = {0}; E(ctor_t, MOVIE_CTOR)(other, 1, 4, 1, 16);
    need(orig_ctor_calls == 1 && other[0] == (void *)0x1, "AVC decoder constructed by the library");
    need(E(int_t, MOVIE_START)(other) == 0x7777 && orig_start_calls == 1, "its Start goes to the library");

    void *dec[2] = {0}; E(ctor_t, MOVIE_CTOR)(dec, 3, 4, 1, 16);
    need(dec[0] == fake_vtable + 0x10 && dec[1] != NULL, "VP9 decoder: library vtable, host state at +8");
    need(E(int_t, MOVIE_START)(dec) == 0x2002, "Start before Configure is refused");
    Event ev[4] = {{0}}; void *events[4] = {&ev[0], &ev[1], &ev[2], &ev[3]};
    need(E(md_t, MOVIE_REGISTER_EVENTS)(dec, events) == 0, "RegisterClientEvents");
    Md bad = {0}; md_set_string(&bad, "mime", "video/avc"); md_set_int32(&bad, "width", W); md_set_int32(&bad, "height", H);
    need(E(md_t, MOVIE_CONFIGURE)(dec, &bad) == 0x2001, "AVC format refused by the VP9 decoder");
    need(E(md_t, MOVIE_CONFIGURE)(dec, NULL) == 0x100b, "null format");
    Md fmt = {0}; md_set_string(&fmt, "mime", "video/x-vnd.on2.vp9"); md_set_int32(&fmt, "width", W); md_set_int32(&fmt, "height", H);
    need(E(md_t, MOVIE_CONFIGURE)(dec, &fmt) == 0, "Configure");
    int size = 0, count = 0; need(E(pp_t, MOVIE_GET_OUTPUT_SIZE)(dec, &size, &count) == 0 && size == (int)fb && count == 1, "output size %d count %d", size, count);
    need(E(int_t, MOVIE_START)(dec) == 0 && ev[0].count == 1, "Start signals input available");

    int64_t times[64]; int in_free[16], nfree = 0, held[16], nheld = 0, next = 0, compared = 0, eos_sent = 0, eos_seen = 0, peak_held = 0, frame_of[16] = {0};
    size_t pos = 32; uint8_t *dst = malloc(fb); Buf ob = {0};
    for (int guard = 0; !eos_seen || nheld; guard++) {
        need(guard < 100000, "decode loop makes progress");
        uint64_t tick = TICK;
        if (paced && t_first >= 0 && fake_ns >= (uint64_t)t_first + 5000000000ull && fake_ns < (uint64_t)t_first + 8000000000ull) tick = 1000000000ull / 15;
        int got_this_tick = 0;
        if (paced) { fake_ns += tick; ticks++; movie_host_tick(); }   /* one game frame: present */
        for (;;) {   /* input event handler: every free input index */
            int idx = -1, rem = 0, st = E(pp_t, MOVIE_ACQUIRE_INPUT)(dec, &idx, &rem);
            if (st) { need(st == 0x1011 && idx == -1, "no input: 0x1011"); break; }
            in_free[nfree++] = idx;
        }
        while (nfree && !eos_sent) {   /* feeder: one sample per free input buffer */
            int idx = in_free[0]; memmove(in_free, in_free + 1, (size_t)--nfree * sizeof in_free[0]);
            Buf ib = {0}; need(E(ib_t, MOVIE_GET_INPUT)(dec, idx, &ib) == 0 && ib.data && ib.cap >= (2u << 20), "input buffer %d", idx);
            if (pos + 12 <= ivf_n) {
                uint32_t n; int64_t pts; memcpy(&n, ivf + pos, 4); memcpy(&pts, ivf + pos + 4, 8); pos += 12;
                need(pos + n <= ivf_n && n <= ib.cap, "IVF frame size");
                memcpy(ib.data, ivf + pos, n); pos += n; times[next % 64] = pts * 1000; next++; if (nall < NF) alltimes[nall++] = pts * 1000;
                need(E(send_t, MOVIE_SEND_INPUT)(dec, idx, 0, (int)n, pts * 1000, 0) == 0, "SendInputBufferForDecode");
            } else {
                need(E(send_t, MOVIE_SEND_INPUT)(dec, idx, 0, 0, 0, 4) == 0, "end of stream input"); eos_sent = 1;
            }
        }
        for (;;) {   /* output event handler: queue every ready output */
            int idx = -1, rem = 0; int64_t t = 0; unsigned fl = 0;
            int st = E(acq_t, MOVIE_ACQUIRE_OUTPUT)(dec, &idx, &t, &fl, &rem);
            if (st) { need(st == 0x100e && idx == -1, "no output: 0x100e"); break; }
            need(ev[2].count >= 1, "format changed signalled before the first output");
            if (fl & 4) { need(paced ? last_k == NF - 1 : compared + nheld == NF, "end of stream after all %d frames (got %d, last %d)", NF, compared + nheld, last_k); need(E(i_t, MOVIE_RELEASE_OUTPUT)(dec, idx) == 0, "release EOS"); eos_seen = 1; break; }
            int k = 0; while (k < nall && alltimes[k] != t) k++;
            need(k < nall && k > last_k, "output time %lld is a later frame than %d (frame %d)", (long long)t, last_k, k);
            if (!paced) need(k == compared + nheld, "output %d is frame %d", compared + nheld, k);
            if (paced) {   /* at most two frame periods late (a frame period: 1/30 s); within two game frames while the game is fast */
                if (t_first < 0) { t_first = (int64_t)fake_ns; pts_first = t; }
                int64_t due = t_first + (t - pts_first) * 1000, late = (int64_t)fake_ns - due, period = 1000000000 / 30;
                need(late >= 0 && late <= 2 * period, "frame %d handed over %lld us after its time", k, (long long)(late / 1000));
                int fast_again = due > t_first + 8200000000ll || due < t_first + 4900000000ll;
                if (fast_again) need(late <= 2 * (int64_t)TICK, "frame %d handed over %lld us late while the game is fast (catch-up)", k, (long long)(late / 1000));
                if (late > late_max) late_max = late; if (fast_again && late > late_fast_max) late_fast_max = late;
            }
            if (paced) { need(got_this_tick == 0, "at most one frame handed over per game frame (frame %d)", k); got_this_tick++; }
            last_k = k; delivered++; frame_of[idx] = k;
            held[nheld++] = idx; if (nheld > peak_held) peak_held = nheld;
        }
        /* renderer: present the oldest frame once every output slot is held, or when the input side has nothing left to do */
        while (nheld && (paced || nheld >= 8 || !nfree || eos_sent)) {
            buf_set_data(&ob, dst, fb); buf_set_range(&ob, 0, (int)fb);
            need(E(ib_t, MOVIE_GET_OUTPUT)(dec, held[0], &ob) == 0 && ob.offset == 0 && ob.size == (int)fb, "GetOutputBuffer frame %d", compared);
            size_t fk = (size_t)frame_of[held[0]];
            if (memcmp(dst, ref + fb * fk, fb)) {
                size_t k = 0; while (dst[k] == ref[fb * fk + k]) k++;
                need(0, "frame %zu differs from ffmpeg's decode at byte %zu (%s plane): %u vs %u", fk, k, k < (size_t)W * H ? "Y" : "UV", dst[k], ref[fb * fk + k]);
            }
            checks++;
            need(E(i_t, MOVIE_RELEASE_OUTPUT)(dec, held[0]) == 0, "ReleaseOutputBufferIndex"); compared++;
            memmove(held, held + 1, (size_t)--nheld * sizeof held[0]);
            break;   /* back to the event handlers: releasing may have decoded waiting inputs */
        }
    }
    need(paced ? compared == delivered && compared < NF : compared == NF, "frames compared %d (delivered %d of %d)", compared, delivered, NF);
    if (!paced) need(peak_held == 8, "all 8 output slots were held at once (peak %d): inputs had to wait", peak_held);
    else {
        double span = (double)(fake_ns - (uint64_t)t_first) / 1e9, movie = (double)(times[(NF - 1) % 64] - pts_first) / 1e6;
        need(span >= movie && span <= movie + 0.1, "paced playback took %.3f s of game time for a %.3f s movie", span, movie);
        fprintf(stderr, "movie probe: paced: %.3f s movie in %.3f s, %d game frames (3 s of them at 15 fps); %d of %d frames shown, %d dropped while slow; latest handover %.1f ms after due (%.1f ms while fast)\n",
                movie, span, ticks, delivered, NF, NF - delivered, late_max / 1e6, late_fast_max / 1e6);
    }
    Md of = {0}; need(E(md_t, MOVIE_GET_OUTPUT_FORMAT)(dec, &of) == 0, "GetOutputFormat");
    int v; const Entry *crop = md_get(&of, "crop");
    need(md_find_int32(&of, "width", &v) && v == W && md_find_int32(&of, "height", &v) && v == H && md_find_int32(&of, "stride", &v) && v == W, "output width / height / stride");
    need(crop && crop->kind == 3 && crop->v[0] == 0 && crop->v[1] == 0 && crop->v[2] == W - 1 && crop->v[3] == H - 1, "output crop");
    need(md_find_int32(&of, "nv12-uv-offset", &v) && v == W * H, "nv12 UV offset");
    need(E(ib_t, MOVIE_GET_INPUT)(dec, 0, NULL) == 0x100b, "GetInputBuffer null buffer");
    need(E(int_t, MOVIE_FLUSH)(dec) == 0 && E(int_t, MOVIE_STOP)(dec) == 0, "Flush, Stop");
    E(obj_t, MOVIE_D0)(dec);
    need(orig_d0_calls == 1 && dec[1] == NULL && dec[0] == fake_vtable + 0x10, "delete: host state freed, the library frees the object");
    need(E(int_t, MOVIE_START)(dec) == 0x7777, "a deleted decoder's address is no longer a host decoder");
    printf("{\"probe\":\"movie\",\"run\":\"%s\",\"frames\":%d,\"checks\":%d,\"ok\":true}\n", argv[6], compared, checks);
    return 0;
}
