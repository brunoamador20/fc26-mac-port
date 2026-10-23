"""Synthetic NSO0 modules for the pre-island tests (no game data).

Shape mirrors a real Switch module so patch_nso.py / structck.py / equiv.py exercise their real paths:
NSO0 header (uncompressed), a module prologue whose word 4 points at MOD0, MOD0 with a dynamic table and an
eh_frame_hdr listing function starts, and a .text seeded with x18 sites spread start-to-end, one ldxr/stxr
exclusive window touching x18, one GROUP of linked windows (an ldaxr/stlxr window plus the out-of-line ldaxr retry
that re-enters it, both on x18: the rewriter's linked_windows / site_window_group path) in the first 16 KiB, one
`br x18` jump table in the kit's ldrb-width form, and an svc. A fixed build id that matches no CUTS / OBS / PARAMS /
SIGNED_TABLES entry keeps the rewrite on the plain generic path.

small()  -> a few hundred KiB, fits with the default reach (no island) and spills to a pre-island at a small reach.
giant()  -> text over 140 MiB in a single function (like FC 26's main: one eh_frame FDE, the chunked LazyInsns path).
"""
import struct

NOP = 0xD503201F
RET = 0xD65F03C0


def _adr(rd, pc, target):
    imm = target - pc
    assert -(1 << 20) <= imm < (1 << 20)
    return 0x10000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def mov_from_x18(rd):            # mov x<rd>, x18  (orr x<rd>, xzr, x18): a plain x18 read site
    return 0xAA0003E0 | (18 << 16) | rd


# The linked-window group (word index; byte offset GROUP_WORD * 4 = 0x4000, low in the text so that a short routing
# reach, or the real one on the giant module, sends it to the pre-island):
#   +0 R0: ldaxr x8, [x18]        out-of-line retry: re-loads, then re-enters the window at its stlxr
#   +1 R1: add   x9, x8, #1
#   +2 R2: cbnz  x9, W2            -> into the middle of the window (linked_windows makes the pair one group)
#   +3 R3: b     W4                (retry not taken: leave)
#   +4 W0: ldaxr x8, [x18]        the window
#   +5 W1: add   x9, x8, #1
#   +6 W2: stlxr w10, x9, [x18]
#   +7 W3: cbnz  w10, R0           store failed -> out-of-line retry
#   +8 W4: (nop)
GROUP_WORD = 0x1000
GROUP_SPAN = 9
GROUP_WORDS = [0xC85FFE48, 0x91000509, 0xB5000089, 0x14000005,
               0xC85FFE48, 0x91000509, 0xC80AFE49, 0x35FFFF2A]
GROUP_HEADS = (GROUP_WORD * 4, (GROUP_WORD + 4) * 4)   # R0 and W0: the two W rows the rewriter writes for the group


def seed(words, nwords, n_sites):
    """Spread x18 read sites, one exclusive window, one linked-window group, an svc and a `br x18` jump table across `words`.

    Returns (n_x18_sites, window_at, svc_at, jump_base, jump_count)."""
    step = max(4, (nwords - 512) // max(1, n_sites))
    placed = 0
    for k in range(1, n_sites + 1):
        i = 8 + k * step
        if i >= nwords - 512:
            break
        if GROUP_WORD - 4 <= i < GROUP_WORD + GROUP_SPAN + 4:   # keep plain sites clear of the group
            continue
        words[i] = mov_from_x18(1); placed += 1
    for j, w in enumerate(GROUP_WORDS):
        words[GROUP_WORD + j] = w
    wi = min(nwords // 3 | 1, nwords - 512)      # exclusive window touching x18 (ldxr/add/stxr/cbnz retry)
    words[wi] = 0x885F7E41                        # ldxr w1, [x18]
    words[wi + 1] = 0x11000421                    # add  w1, w1, #1
    words[wi + 2] = 0x88027E41                    # stxr w2, w1, [x18]
    words[wi + 3] = 0x35FFFFA2                    # cbnz w2, wi (retry into the window)
    svc_at = (nwords // 2 + 1)
    words[svc_at] = 0xD4000001                    # svc #0
    base_i = nwords - 280                         # 256 landing targets (all `ret`, all valid in-function
    for j in range(260):
        words[base_i + j] = RET
    disp_i = base_i - 8
    words[disp_i] = _adr(18, disp_i * 4, base_i * 4)   # adr x18, base
    words[disp_i + 1] = 0x39400001                # ldrb w1, [x0]
    words[disp_i + 2] = 0x8B010A52                # add  x18, x18, x1, lsl #2
    words[disp_i + 3] = 0xD61F0240                # br   x18
    return placed, wi * 4, svc_at * 4, base_i * 4, 256


def build(text_words, func_starts, ro_size=0x2000, data_size=0x1000, bss=0x1000, build_id=b'\xa5' * 16):
    """text_words: a mutable list/bytearray-backed sequence of u32. func_starts: sorted text offsets (>= 8)."""
    text = bytearray(len(text_words) * 4)
    for i, w in enumerate(text_words):
        struct.pack_into('<I', text, i * 4, w)
    TEXT_SZ = len(text)
    RO_OFF = (TEXT_SZ + 0xFFF) & ~0xFFF
    DATA_OFF = (RO_OFF + ro_size + 0xFFF) & ~0xFFF
    m0 = RO_OFF
    struct.pack_into('<I', text, 0, 0x14000002)          # b #8 past the header pointer
    struct.pack_into('<I', text, 4, m0)                  # image[4] -> MOD0
    dyn_off, ehs = m0 + 0x100, m0 + 0x400
    ro = bytearray(ro_size)
    ro[0:4] = b'MOD0'
    struct.pack_into('<i', ro, 4, dyn_off - m0)
    struct.pack_into('<i', ro, 16, ehs - m0)
    struct.pack_into('<qQ', ro, dyn_off - m0, 0, 0)      # empty dynamic table (terminator)
    o = ehs - m0
    ro[o:o + 4] = bytes([1, 0x03, 0x03, 0x03]); o += 4   # eh_frame_hdr: all u32 absolute
    struct.pack_into('<I', ro, o, 0); o += 4             # eh_frame_ptr (unused)
    struct.pack_into('<I', ro, o, len(func_starts)); o += 4
    for fs in func_starts:
        struct.pack_into('<II', ro, o, fs, ehs); o += 8  # (pc begin absolute, fde ptr unused)
    HDR = 0x100
    file = bytearray(HDR)
    file[0:4] = b'NSO0'
    struct.pack_into('<I', file, 0xc, 0)                 # flags: no compression
    segs = [(0, TEXT_SZ), (RO_OFF, ro_size), (DATA_OFF, data_size)]
    foff = HDR
    for i, (mo, sz) in enumerate(segs):
        struct.pack_into('<III', file, 0x10 + i * 0x10, foff, mo, sz); foff += sz
    struct.pack_into('<I', file, 0x3c, bss)
    file[0x40:0x40 + len(build_id)] = build_id
    struct.pack_into('<III', file, 0x60, segs[0][1], segs[1][1], segs[2][1])   # csz == sz (uncompressed)
    return bytes(file) + bytes(text) + bytes(ro) + bytes(data_size)


def small(path, text_sz=0x40000, n_sites=200):
    nwords = text_sz // 4
    words = [NOP] * nwords
    info = seed(words, nwords, n_sites)
    open(path, 'wb').write(build(words, [8, nwords // 4 * 4, nwords // 2 * 4]))
    return info


def giant(path, mib=144, every=256):
    """A single >mib MiB function (one FDE) with x18 sites every `every` words, a window, a jump table and an svc."""
    nwords = (mib << 20) // 4
    words = bytearray(nwords * 4)
    for i in range(nwords):
        struct.pack_into('<I', words, i * 4, NOP)

    class _W:                                            # a thin u32 view so seed()/build() can index words
        def __len__(self): return nwords
        def __setitem__(self, i, v): struct.pack_into('<I', words, i * 4, v)
        def __getitem__(self, i): return struct.unpack_from('<I', words, i * 4)[0]
        def __iter__(self):
            for i in range(nwords):
                yield struct.unpack_from('<I', words, i * 4)[0]
    view = _W()
    info = seed(view, nwords, nwords // every)
    open(path, 'wb').write(build(view, [8]))             # one function => the giant-function LazyInsns path
    return info
