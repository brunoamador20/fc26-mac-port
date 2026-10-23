// The eight NVN entry points FC 26's video module needs that the layer lacked (third_party/d2r_gfx/gfx/nvn/fc26_nvn_ext.c)
// and the copy stride arithmetic (nvn_copy_stride.h), built without macOS: the .c is included so its static
// implementations and registration entries are visible. nvn_rec stands in for hle_nvn.c's command recorder.
// Modes: "run" (every check, one "ok" line each), "negative-stride" (must stop), "grid-log" (enable the grid three times).
#include "../third_party/d2r_gfx/gfx/nvn/fc26_nvn_ext.c"
#include "../third_party/d2r_gfx/gfx/nvn/nvn_copy_stride.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t g_rec[64]; static uint32_t g_rec_op; static size_t g_rec_payload; static int g_rec_calls;
void *nvn_rec(NVNcommandBuffer *c, uint32_t op, size_t payload) {
    (void)c;
    if (payload > sizeof g_rec) { fprintf(stderr, "payload %zu\n", payload); exit(1); }
    g_rec_op = op; g_rec_payload = payload; g_rec_calls++; memset(g_rec, 0xee, sizeof g_rec);
    return g_rec;
}
int runtime_core_away(void) { return 0; }
void runtime_core_back(int *away) { (void)away; }

static int g_fail;
#define CHECK(cond, ...) do { if (cond) { printf("ok "); printf(__VA_ARGS__); printf("\n"); } \
                              else { printf("FAIL %s:%d ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

static void registration(void) {
    const nvn_impl *e[] = {&e_nvnBufferBuilderGetMemoryOffset, &e_nvnBufferBuilderGetSize, &e_nvnEventGetMemoryOffset, &e_nvnSamplerPoolGetMemoryOffset,
                           &e_nvnTexturePoolGetMemoryOffset, &e_nvnTextureBuilderGetRawStorageClass, &e_nvnCommandBufferSetCopyImageStride,
                           &e_nvnMultisampleStateSetSampleLocationsGridEnable};
    void *fn[] = {(void *)h_nvnBufferBuilderGetMemoryOffset, (void *)h_nvnBufferBuilderGetSize, (void *)h_nvnEventGetMemoryOffset, (void *)h_nvnSamplerPoolGetMemoryOffset,
                  (void *)h_nvnTexturePoolGetMemoryOffset, (void *)h_nvnTextureBuilderGetRawStorageClass, (void *)h_nvnCommandBufferSetCopyImageStride,
                  (void *)h_nvnMultisampleStateSetSampleLocationsGridEnable};
    for (size_t i = 0; i < sizeof e / sizeof *e; i++) {
        CHECK(e[i]->fn == fn[i], "registered %s", e[i]->name);
        printf("name %s\n", e[i]->name);   // the Python test compares these with names.txt / nvn_thunks.S
    }
}

static void storage_queries(void) {
    pool_t pool = {.magic = MAGIC('P', 'O', 'O', 'L'), .size = 0x100000};
    NVNbufferBuilder bb; memset(&bb, 0, sizeof bb);
    *(totk_buffer_builder *)&bb = (totk_buffer_builder){NULL, &pool, 0x12340, 0x8000};   // what nvnBufferBuilderSetStorage stores
    CHECK(h_nvnBufferBuilderGetMemoryOffset(&bb) == 0x12340, "nvnBufferBuilderGetMemoryOffset = SetStorage offset");
    CHECK(h_nvnBufferBuilderGetSize(&bb) == 0x8000, "nvnBufferBuilderGetSize = SetStorage size");

    NVNtexturePool tp; NVNsamplerPool sp;
    *(dpool_t *)&tp = (dpool_t){&pool, 0x40000, 4096};   // what nvnTexturePoolInitialize / nvnSamplerPoolInitialize store
    *(dpool_t *)&sp = (dpool_t){&pool, 0x60020, 2048};
    CHECK(h_nvnTexturePoolGetMemoryOffset(&tp) == 0x40000, "nvnTexturePoolGetMemoryOffset = Initialize offset");
    CHECK(h_nvnSamplerPoolGetMemoryOffset(&sp) == 0x60020, "nvnSamplerPoolGetMemoryOffset = Initialize offset");

    uint8_t mem[64] = {0}; pool.mem = mem;
    NVNevent ev; memset(&ev, 0, sizeof ev);
    *(ev_t *)&ev = (ev_t){MAGIC('E', 'V', 'N', 'T'), (volatile uint32_t *)(mem + 0x20), &pool, 0x20};   // what nvnEventInitialize stores
    CHECK(h_nvnEventGetMemoryOffset(&ev) == 0x20, "nvnEventGetMemoryOffset = EventBuilderSetStorage offset");
    CHECK(sizeof(ev_t) <= sizeof(NVNevent), "ev_t fits NVNevent (%zu <= %zu)", sizeof(ev_t), sizeof(NVNevent));

    NVNtextureBuilder tb; memset(&tb, 0, sizeof tb);
    CHECK(h_nvnTextureBuilderGetRawStorageClass(&tb) == 1, "nvnTextureBuilderGetRawStorageClass = the texture's (1)");
}

static void copy_image_stride(void) {
    NVNcommandBuffer cb; memset(&cb, 0, sizeof cb);
    h_nvnCommandBufferSetCopyImageStride(&cb, 0x3000);
    CHECK(g_rec_calls == 1 && g_rec_op == OP_COPY_IMG_STRIDE && g_rec_payload == sizeof(p_copy_stride), "SetCopyImageStride records OP_COPY_IMG_STRIDE (op %u)", g_rec_op);
    CHECK(((p_copy_stride *)g_rec)->stride == 0x3000, "the record holds the stride");
    h_nvnCommandBufferSetCopyImageStride(&cb, 0);
    CHECK(g_rec_calls == 2 && ((p_copy_stride *)g_rec)->stride == 0, "stride 0 (back to tightly packed) is recorded too");
    CHECK(OP_COPY_IMG_STRIDE == OP_COUNT_ - 1 && OP_RENDER_COND == OP_COUNT_ - 2, "new op appended: earlier op numbers unchanged");
}

static void layout(void) {
    // RGBA8 (4 bytes, 1x1 blocks) 64x32: tightly packed
    nvn_copy_layout L = nvn_copy_layout_of(64, 32, 1, 1, 1, 4, 0, 0);
    CHECK(L.row == 256 && L.rows == 32 && L.tight == 8192 && L.img == 8192 && L.span == 8192, "RGBA8 64x32 tightly packed");
    // three layers, no strides: the kit's earlier formula (row * rows * layers)
    L = nvn_copy_layout_of(64, 32, 3, 1, 1, 4, 0, 0);
    CHECK(L.img == 8192 && L.span == 3 * 8192, "three layers tightly packed = row * rows * layers");
    // row stride only
    L = nvn_copy_layout_of(64, 32, 3, 1, 1, 4, 512, 0);
    CHECK(L.row == 512 && L.tight == 512 * 32 && L.img == L.tight && L.span == 3 * L.tight, "row stride 512: images follow the padded rows");
    // image stride: images start every 20000 bytes; the last one covers only its rows
    L = nvn_copy_layout_of(64, 32, 3, 1, 1, 4, 0, 20000);
    CHECK(L.row == 256 && L.img == 20000 && L.span == 2 * 20000 + 8192, "image stride 20000 over three layers spans 2*20000 + 8192");
    // both strides
    L = nvn_copy_layout_of(64, 32, 2, 1, 1, 4, 512, 65536);
    CHECK(L.row == 512 && L.img == 65536 && L.span == 65536 + 512 * 32, "row 512 + image 65536");
    // one image: the image stride does not matter
    L = nvn_copy_layout_of(64, 32, 1, 1, 1, 4, 0, 20000);
    CHECK(L.span == 8192, "one image: the image stride changes nothing");
    // BC1 (8 bytes per 4x4 block) 30x30: 8 blocks per row, 8 block rows
    L = nvn_copy_layout_of(30, 30, 1, 4, 4, 8, 0, 0);
    CHECK(L.row == 64 && L.rows == 8 && L.tight == 512, "BC1 30x30 rounds up to whole blocks");
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "run";
    NVNcommandBuffer cb; memset(&cb, 0, sizeof cb);
    if (!strcmp(mode, "negative-stride")) { h_nvnCommandBufferSetCopyImageStride(&cb, -16); printf("not stopped\n"); return 0; }
    if (!strcmp(mode, "grid-log")) {
        NVNmultisampleState ms; memset(&ms, 0, sizeof ms);
        h_nvnMultisampleStateSetSampleLocationsGridEnable(&ms, 0x100);   // NVNboolean: only the low 8 bits count -> off
        printf("grid %d\n", ((ms_st *)(void *)&ms)->sl_grid);
        for (int i = 0; i < 3; i++) h_nvnMultisampleStateSetSampleLocationsGridEnable(&ms, 1);
        printf("grid %d\n", ((ms_st *)(void *)&ms)->sl_grid);
        h_nvnMultisampleStateSetSampleLocationsGridEnable(&ms, 0);
        printf("grid %d\n", ((ms_st *)(void *)&ms)->sl_grid);
        return 0;
    }
    registration(); storage_queries(); copy_image_stride(); layout();
    return g_fail;
}
