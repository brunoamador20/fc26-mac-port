// FC 26: buffer-side layout of a copy between a buffer and a texture (CopyBufferToTexture / CopyTextureToBuffer) under
// the command buffer's copy strides: SetCopyRowStride = bytes from one row of blocks to the next, SetCopyImageStride =
// bytes from one 2D image (array layer or 3D slice) to the next; 0 = tightly packed, the default. Pure C so the
// arithmetic is tested on Linux (tests/test_nvn_gaps.py); nvn_mtl.m copy_t2b / copy_b2t use it.
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    size_t row;     // bytes per row of blocks in the buffer
    size_t rows;    // rows of blocks per image
    size_t tight;   // row * rows: the bytes one image covers
    size_t img;     // bytes from the start of one image to the next
    size_t span;    // bytes the whole copy covers: (images - 1) * img + tight
} nvn_copy_layout;

// width / height in texels, images = layers or slices copied (>= 1), bw / bh / bpb = the format's block (nvn_fmt_bpb).
static inline nvn_copy_layout nvn_copy_layout_of(int width, int height, int images, int bw, int bh, int bpb,
                                                 int64_t row_stride, int64_t img_stride) {
    nvn_copy_layout L;
    L.row = row_stride ? (size_t)row_stride : (size_t)((width + bw - 1) / bw) * (size_t)bpb;
    L.rows = (size_t)((height + bh - 1) / bh);
    L.tight = L.row * L.rows;
    L.img = img_stride ? (size_t)img_stride : L.tight;
    L.span = (images > 1 ? (size_t)(images - 1) * L.img : 0) + L.tight;
    return L;
}
