/* hwopus: nn::codec::detail::IHardwareOpusDecoderManager over IPC, decoded with libopus on the host (switchbrew
   "Audio services", hwopus; read 2026-10-23). On the Switch hwopus is libopus running on the audio DSP.
   runtime/opus_codec.c already answers the sdk's single-stream nn::codec::*HardwareOpusDecoder* functions by name; this
   service answers what reaches the IPC layer instead (multistream, the Ex variants, a function those names miss).
   The software nn::codec Opus API (OpusDecoder / OpusEncoder: DecodeOpusInterleaved, EncodeOpusInterleaved, bit rate,
   complexity, ...) is libopus inside the sdk, "separate from" hwopus (switchbrew), and runs natively: nothing here.
   A frame is Nintendo's: an 8-byte big-endian header {payload size, final range}, then the Opus packet; one call decodes
   one frame into interleaved PCM16 and returns {s32 bytes consumed (header included), s32 samples per channel}, as
   opus_codec.c does. The work buffer (transfer memory) is reserved by the game but unused: the host keeps the state. */
#include "runtime.h"
#include "ipc.h"
#include <opus.h>
#include <opus_multistream.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define RESULT(module, description) ((uint32_t)(module) | ((uint32_t)(description) << 9))
/* Codec is module 111; switchbrew lists no codec result, and the game only needs a failure: the descriptions are the
   host's choice (docs/SERVICOS_NUVEM.md). */
#define HWOPUS_INVALID_ARGUMENT RESULT(111, 1)
#define HWOPUS_BAD_FRAME RESULT(111, 2)
enum { MULTISTREAM_SIZE = 0x110, MULTISTREAM_EX_SIZE = 0x118, MAPPING_OFFSET = 0x10, MAPPING_EX_OFFSET = 0x18 };

typedef struct {
    int rate, channels, streams, coupled;   /* streams == 0: a single-stream decoder */
    unsigned char mapping[255];
} Format;
typedef struct {
    Format f;
    OpusDecoder *single;
    OpusMSDecoder *multi;
    pthread_mutex_t lock;
} Decoder;

static int valid_rate(int rate) { return rate == 48000 || rate == 24000 || rate == 16000 || rate == 12000 || rate == 8000; }
static int valid_format(const Format *f) {
    if (!valid_rate(f->rate)) return 0;
    if (!f->streams) return f->channels == 1 || f->channels == 2;
    if (f->channels < 1 || f->channels > 255 || f->coupled < 0 || f->coupled > f->streams || f->streams + f->coupled > 255) return 0;
    for (int i = 0; i < f->channels; i++) if (f->mapping[i] != 255 && f->mapping[i] >= f->streams + f->coupled) return 0;
    return 1;
}
static uint32_t work_size(const Format *f) {
    if (!valid_format(f)) return 0;
    int size = f->streams ? opus_multistream_decoder_get_size(f->streams, f->coupled) : opus_decoder_get_size(f->channels);
    return size > 0 ? (uint32_t)size + 0x1000 : 0;   /* the client aligns it to pages (switchbrew) */
}
/* {s32 sample rate, s32 channel count} at off (OpenHardwareOpusDecoder, GetWorkBufferSize, OpusParametersEx). */
static Format single_format(const IpcRequest *rq, uint32_t off) {
    Format f; memset(&f, 0, sizeof f);
    f.rate = IPC_ARG(rq, int32_t, off); f.channels = IPC_ARG(rq, int32_t, off + 4);
    return f;
}
/* OpusMultiStreamParameters(Ex) in a type-0x19 buffer: rate, channels, streams, coupled streams, [Ex: use-large-frame,
   padding], u8 channel mapping[0x100]. */
static int multistream_format(const IpcRequest *rq, int ex, Format *f) {
    uint64_t need = ex ? MULTISTREAM_EX_SIZE : MULTISTREAM_SIZE;
    if (!rq->nx || rq->x[0].size < need) return 0;
    const uint8_t *p = ipc_guest(rq->x[0].addr, need);
    int32_t v[4]; memcpy(v, p, sizeof v);
    memset(f, 0, sizeof *f);
    f->rate = v[0]; f->channels = v[1]; f->streams = v[2]; f->coupled = v[3];
    if (f->channels < 1 || f->channels > 255 || f->streams < 1) return 0;
    memcpy(f->mapping, p + (ex ? MAPPING_EX_OFFSET : MAPPING_OFFSET), (size_t)f->channels);
    return 1;
}

static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static void decode(Decoder *d, const IpcRequest *rq, IpcResponse *rs, int reset, int perf) {
    if (!rq->na || !rq->nb) runtime_fail("hwopus decode: no input or output buffer");
    const IpcBuffer in_b = rq->a[0], out_b = rq->b[0];
    if (in_b.size < 8) { rs->result = HWOPUS_BAD_FRAME; return; }
    const uint8_t *in = ipc_guest(in_b.addr, in_b.size);
    int16_t *out = ipc_guest(out_b.addr, out_b.size);
    uint32_t n = be32(in), range = be32(in + 4);
    if (n > in_b.size - 8 || n > INT_MAX) { rs->result = HWOPUS_BAD_FRAME; return; }
    uint64_t capacity = out_b.size / (sizeof(int16_t) * (uint64_t)d->f.channels);
    if (capacity > INT_MAX) capacity = INT_MAX;
    pthread_mutex_lock(&d->lock);
    if (reset) {
        if (d->multi) opus_multistream_decoder_ctl(d->multi, OPUS_RESET_STATE);
        else opus_decoder_ctl(d->single, OPUS_RESET_STATE);
    }
    dm_guest_write_prepare(out, (size_t)out_b.size);
    int got = d->multi ? opus_multistream_decode(d->multi, in + 8, (opus_int32)n, out, (int)capacity, 0)
                       : opus_decode(d->single, in + 8, (opus_int32)n, out, (int)capacity, 0);
    opus_uint32 final = 0;
    if (got >= 0) {
        if (d->multi) opus_multistream_decoder_ctl(d->multi, OPUS_GET_FINAL_RANGE(&final));
        else opus_decoder_ctl(d->single, OPUS_GET_FINAL_RANGE(&final));
    }
    pthread_mutex_unlock(&d->lock);
    if (got < 0) { fprintf(stderr, "[totk-audio] hwopus decode: %s\n", opus_strerror(got)); rs->result = HWOPUS_BAD_FRAME; return; }
    /* A header range of 0 is not a recorded value (opus_codec.c): only a nonzero one is checked. */
    if (n && range && final != range) {
        fprintf(stderr, "[totk-audio] hwopus: Opus final range %#x != stream %#x\n", final, range);
        runtime_fail("Opus stream integrity");
    }
    int32_t consumed = (int32_t)(8 + n), samples = got;
    IPC_OUT(rs, consumed); IPC_OUT(rs, samples);
    if (perf) { uint64_t time = 0; IPC_OUT(rs, time); }   /* ignored by official user-processes (switchbrew) */
}
static void decoder_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IHardwareOpusDecoder */
    Decoder *d = s->state;
    switch (rq->cmd) {
    case 0: case 2: decode(d, rq, rs, 0, 0); return;                            /* DecodeInterleaved(ForMultiStream)Old */
    case 1: case 3: return;                                                     /* SetContext(ForMultiStream): unused */
    case 4: case 5: decode(d, rq, rs, 0, 1); return;                            /* ...WithPerfOld */
    case 6: case 7: case 8: case 9:                                             /* ...WithPerfAndResetOld, DecodeInterleaved(ForMultiStream) */
        decode(d, rq, rs, IPC_ARG(rq, uint8_t, 0) != 0, 1); return;
    default: ipc_unimplemented(s, rq);
    }
}
static void decoder_close(void *p) {
    Decoder *d = p;
    if (d->multi) opus_multistream_decoder_destroy(d->multi);
    if (d->single) opus_decoder_destroy(d->single);
    pthread_mutex_destroy(&d->lock);
    free(d);
}
static void open_decoder(const Format *f, uint32_t size, const IpcRequest *rq, IpcResponse *rs) {
    uint32_t need = work_size(f);
    if (!need || size < need || !rq->ncopy) {
        fprintf(stderr, "[totk-audio] hwopus open refused: %d Hz x%d, %d streams (%d coupled), work buffer %#x of %#x, %u handles\n",
                f->rate, f->channels, f->streams, f->coupled, size, need, rq->ncopy);
        rs->result = HWOPUS_INVALID_ARGUMENT; return;
    }
    Decoder *d = calloc(1, sizeof *d);
    if (!d) runtime_fail("hwopus decoder allocation");
    d->f = *f;
    int err = OPUS_OK;
    if (f->streams) d->multi = opus_multistream_decoder_create(f->rate, f->channels, f->streams, f->coupled, f->mapping, &err);
    else d->single = opus_decoder_create(f->rate, f->channels, &err);
    if ((!d->multi && !d->single) || err != OPUS_OK) runtime_fail("libopus decoder creation");
    if (pthread_mutex_init(&d->lock, NULL)) runtime_fail("hwopus decoder mutex");
    rs->move[rs->nmove++] = runtime_ipc_new_session("IHardwareOpusDecoder", decoder_handler, d, decoder_close);
    fprintf(stderr, "[totk-audio] hwopus decoder %d Hz x%d%s\n", f->rate, f->channels, f->streams ? " (multistream)" : "");
}
static void manager_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IHardwareOpusDecoderManager */
    Format f;
    switch (rq->cmd) {
    case 0: f = single_format(rq, 0); open_decoder(&f, IPC_ARG(rq, uint32_t, 8), rq, rs); return;   /* OpenHardwareOpusDecoder */
    case 1: case 5: case 8: { f = single_format(rq, 0); uint32_t n = work_size(&f); IPC_OUT(rs, n); return; }   /* GetWorkBufferSize(Ex)(Ex) */
    case 4: f = single_format(rq, 0); open_decoder(&f, IPC_ARG(rq, uint32_t, 0x10), rq, rs); return;   /* OpenHardwareOpusDecoderEx */
    case 2: case 6:                                                             /* OpenHardwareOpusDecoderForMultiStream(Ex) */
        if (!multistream_format(rq, rq->cmd == 6, &f)) { rs->result = HWOPUS_INVALID_ARGUMENT; return; }
        open_decoder(&f, IPC_ARG(rq, uint32_t, 0), rq, rs); return;
    case 3: case 7: case 9: {                                                   /* GetWorkBufferSizeForMultiStream(Ex)(Ex) */
        uint32_t n = multistream_format(rq, rq->cmd != 3, &f) ? work_size(&f) : 0;
        IPC_OUT(rs, n); return;
    }
    default: ipc_unimplemented(s, rq);
    }
}

__attribute__((constructor)) static void register_hwopus(void) { runtime_ipc_register("hwopus", manager_handler, NULL, NULL); }
