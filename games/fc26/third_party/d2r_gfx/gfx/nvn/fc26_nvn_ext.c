// FC 26: the eight NVN entry points FC 26's video module (Engine.Render.Core2.PlatformNvn.nro) calls that this layer did
// not answer (static analysis of the module: 241 used, 233 already here; docs/NVN_LACUNAS_NUVEM.md). Their names were
// already in main's name table (names.txt, nvn_thunks.S slots), so a call stopped in nvn_unimpl_c with
// "[fc26-missing] nvn: <name>". Six return what the object stored; SetCopyImageStride is recorded like SetCopyRowStride
// and applied by the Metal copies (nvn_mtl.m copy_b2t / copy_t2b, nvn_copy_stride.h); the sample-location grid flag is
// stored and reported once (no Metal equivalent). Signatures: nvn_protos.h (the kit's open nvn.h); the two names the
// header has no prototype for follow their siblings. tests/test_nvn_gaps.py builds this file on Linux.
#include "../../host/hle.h"
#include "nvn_impl.h"
#include "nvn_obj.h"

// ---------- Storage queries: what SetStorage / Initialize stored ----------
NVN(nvnBufferBuilderGetMemoryOffset, ptrdiff_t, const NVNbufferBuilder *b) { return (ptrdiff_t)((const totk_buffer_builder *)b)->off; }
NVN(nvnBufferBuilderGetSize, size_t, const NVNbufferBuilder *b) { return (size_t)((const totk_buffer_builder *)b)->size; }
NVN(nvnTexturePoolGetMemoryOffset, ptrdiff_t, const NVNtexturePool *p) { return (ptrdiff_t)((const dpool_t *)p)->off; }
NVN(nvnSamplerPoolGetMemoryOffset, ptrdiff_t, const NVNsamplerPool *p) { return (ptrdiff_t)((const dpool_t *)p)->off; }
/* No prototype in the header: the offset type is nvnEventBuilderSetStorage's (int64_t), a 64-bit value in x0 like the
   ptrdiff_t of the other *GetMemoryOffset. nvnEventInitialize (hle_nvn.c) keeps the builder's offset in ev_t. */
NVN_NOPROTO(nvnEventGetMemoryOffset, int64_t, const NVNevent *e) { return ((const ev_t *)e)->off; }
/* No prototype in the header. The texture answers 1 (hle_nvn.c nvnTextureGetRawStorageClass; meaning unverified, TOTK
   compares it with 1); the builder answers the same, so a builder and the texture made from it agree. */
NVN_NOPROTO(nvnTextureBuilderGetRawStorageClass, int, const NVNtextureBuilder *b) { (void)b; return 1; }

// ---------- Copy strides: bytes between 2D images (array layers / 3D slices) in the buffer of later buffer <-> texture
// copies, 0 = tightly packed. Command buffer state like the row stride (OP_COPY_STRIDE), replayed in order. ----------
void *nvn_rec(NVNcommandBuffer *c, uint32_t op, size_t payload);   // hle_nvn.c: appends a command record
NVN(nvnCommandBufferSetCopyImageStride, void, NVNcommandBuffer *c, ptrdiff_t st) {
    if (st < 0) die("nvnCommandBufferSetCopyImageStride %td: negative image stride not supported by the Metal copies", st);
    if (st) { static int seen; if (seen < 4) LOG("[nvn] SetCopyImageStride %td (first non-zero image strides: %d of 4 logged)", st, ++seen); }
    ((p_copy_stride *)nvn_rec(c, OP_COPY_IMG_STRIDE, sizeof(p_copy_stride)))->stride = st;
}

// ---------- Programmable sample locations repeated over a pixel grid: Metal's custom sample positions are the same for
// every pixel, and this layer applies no sample locations at all (SetSampleLocations stores nothing). The flag is kept
// for the state object; enabling it is reported once and drawing uses the standard positions. ----------
NVN(nvnMultisampleStateSetSampleLocationsGridEnable, void, NVNmultisampleState *s, uint32_t e) {
    ((ms_st *)(void *)s)->sl_grid = (e & 0xff) != 0;
    if (e & 0xff) { static int once; if (!once++) LOG("【红】SetSampleLocationsGridEnable(1): no Metal equivalent, drawn with the standard sample positions"); }
}
