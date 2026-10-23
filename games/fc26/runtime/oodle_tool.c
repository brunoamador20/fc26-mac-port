/* fc26-native <rewritten> oodle: the game's own OodleLZ_Decompress as a pipe service, for scripts/shader_seed.py (offline
   shader pre-translation, docs/SHADER_SEED.md). Frostbite's .cas blocks are Oodle (BRIEFING: the game decompresses them,
   the host only hands bytes over); this mode runs that same decoder on the loaded, relocated main module, without
   starting the game (no constructors, no nnMain, no services). FC26_OODLE_OFFSET=<hex>: the function's main offset, which
   the script finds by its "OodleLZ_Decompress" log name and checks.
   Request (stdin, little-endian): u32 'OODL', u32 compressed size, u32 raw size, the compressed bytes.
   Reply (stdout): i64 OodleLZ_Decompress's result (the raw size on success), then that many raw bytes. EOF ends it. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define OODLE_MAGIC 0x4c444f4fu   /* "OODL" */
#define OODLE_MAX (16u << 20)
#define OODLE_DECODER_MEMORY (32u << 20)

typedef int64_t (*OodleLZ_Decompress)(const void *comp, int64_t comp_len, void *raw, int64_t raw_len, int fuzz, int crc,
                                      int verbosity, void *dec_base, int64_t dec_size, void *callback, void *user,
                                      void *decoder_memory, int64_t decoder_memory_size, int thread_phase);

static int read_all(void *p, size_t n) {
    uint8_t *b = p;
    while (n) { ssize_t r = read(0, b, n); if (r <= 0) return -1; b += r; n -= (size_t)r; }
    return 0;
}
static void write_all(const void *p, size_t n) {
    const uint8_t *b = p;
    while (n) { ssize_t w = write(1, b, n); if (w <= 0) runtime_fail("oodle: write reply"); b += w; n -= (size_t)w; }
}

void runtime_oodle_tool(void) {
    const char *e = getenv("FC26_OODLE_OFFSET");
    if (!e) runtime_fail("oodle needs FC26_OODLE_OFFSET=<hex main offset of OodleLZ_Decompress>");
    uint64_t off = strtoull(e, NULL, 16);
    uint8_t *main_base = runtime_module_base("main");
    if (!main_base || !off || off & 3) runtime_fail("oodle: bad offset");
    uint32_t first; memcpy(&first, main_base + off, 4);
    if ((first & 0xffc07fffu) != 0xa9807bfdu) runtime_fail("oodle: offset is not a function entry (stp x29, x30, [sp, #-n]!)");
    runtime_thread_init();   /* the rewritten code keeps x18 and the TLS registers in this thread's slots */
    OodleLZ_Decompress fn = (OodleLZ_Decompress)(void *)(main_base + off);
    uint8_t *comp = malloc(OODLE_MAX), *raw = malloc(OODLE_MAX), *mem = malloc(OODLE_DECODER_MEMORY);
    if (!comp || !raw || !mem) runtime_fail("oodle: buffers");
    for (;;) {
        uint32_t h[3];
        if (read_all(h, sizeof h)) break;
        if (h[0] != OODLE_MAGIC || !h[1] || !h[2] || h[1] > OODLE_MAX || h[2] > OODLE_MAX) runtime_fail("oodle: bad request");
        if (read_all(comp, h[1])) runtime_fail("oodle: short request");
        /* As Frostbite calls it (main+0x8af1180 in 1.0.0): no fuzz safety, no CRC, quiet, caller's decoder memory,
           OodleLZ_Decode_Unthreaded (3). */
        int64_t got = fn(comp, h[1], raw, h[2], 0, 0, 0, NULL, 0, NULL, NULL, mem, OODLE_DECODER_MEMORY, 3);
        write_all(&got, sizeof got);
        if (got == (int64_t)h[2]) write_all(raw, h[2]);
    }
    free(comp); free(raw); free(mem);
}
