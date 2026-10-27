"""Synthetic NRO, NRR and rewriter output for the FC 26 nn::ro tests. Every byte is made up here; no game data.

The NRO has the shapes the real PlatformNvn module was measured to have (games/fc26/docs/BRIEFING.md): RELR for the
relative relocations, RELA with ABS64 / GLOB_DAT / TLSDESC, JMPREL with JUMP_SLOT, DT_HASH and DT_GNU_HASH, INIT /
FINI / INIT_ARRAY, a [19.0.0+] MOD0, no DT_NEEDED. Its text holds one instruction of each kind the rewriter changes.
"""
import hashlib
import struct

FC26_PROGRAM_ID = 0x01004FF021942000
TEXT, RO, DATA = 0x0, 0x4000, 0x8000
NRO_SIZE, BSS_SIZE = 0x9000, 0x2000
MOD0 = 0x80

# A few AArch64 words (encodings from the Arm ARM).
MRS_X0_TPIDR, SVC_1, MRS_X1_CNTPCT = 0xd53bd040, 0xd4000021, 0xd53be021
MOV_X0_X1, MOV_X0_X18, MOV_W0_42, RET, NOP = 0xaa0103e0, 0xaa1203e0, 0x52800540, 0xd65f03c0, 0xd503201f
CODE = {0x100: [MRS_X0_TPIDR, RET], 0x108: [SVC_1, RET], 0x110: [MRS_X1_CNTPCT, MOV_X0_X1, RET],
        0x11c: [MOV_X0_X18, RET], 0x130: [MOV_W0_42, RET], 0x138: [RET, NOP], 0x140: [RET], 0x144: [RET],
        0x150: [NOP, RET]}
SITES = {0x100: 'tpidr', 0x108: 'svc', 0x110: 'cntpct', 0x11c: 'x18'}   # what the rewriter changes in this text

# Data segment layout (absolute offsets in the module).
DYNAMIC, GOT, INIT_ARRAY, TABLE, FAR, EXPORT_DATA = 0x8000, 0x8200, 0x8300, 0x8400, 0x8800, 0x8a00
G_ABS_IMPORT, G_ABS_LOCAL, G_GLOB, G_WEAK, G_TLS_LOCAL, G_TLS_SYM, G_JUMP0, G_JUMP1 = (
    0x8200, 0x8208, 0x8210, 0x8218, 0x8220, 0x8230, 0x8240, 0x8248)
RELR_TARGETS = {INIT_ARRAY: 0x140, TABLE: 0x130, TABLE + 8: 0x134, TABLE + 16: 0x138, FAR: 0x4100}

# (name, binding, type, defined value or None); undefined first, as GNU hash wants the hashed ones last.
SYMBOLS = [('pthread_mutex_lock', 1, 2, None), ('__cxa_guard_acquire', 1, 2, None),
           ('_ZN2nn3mem17StandardAllocator8AllocateEm', 1, 2, None), ('_ZTVN10__cxxabiv117__class_type_infoE', 1, 1, None),
           ('weak_optional_hook', 2, 0, None), ('nro_export_fn', 1, 2, 0x130), ('nro_export_data', 1, 1, EXPORT_DATA),
           ('nro_tls_var', 1, 6, 0x8)]
SYM = {name: i + 1 for i, (name, *_) in enumerate(SYMBOLS)}
R_ABS64, R_GLOB_DAT, R_JUMP_SLOT, R_RELATIVE, R_TLSDESC = 257, 1025, 1026, 1027, 1031


def elf_hash(name):
    h = 0
    for c in name.encode():
        h = ((h << 4) + c) & 0xffffffff
        g = h & 0xf0000000
        if g: h ^= g >> 24
        h &= ~g & 0xffffffff
    return h


def gnu_hash(name):
    h = 5381
    for c in name.encode(): h = (h * 33 + c) & 0xffffffff
    return h


def relr_encode(addresses):
    """lld's packing: an address word, then bitmaps of the next 63 words while they cover anything."""
    out, todo = [], sorted(addresses)
    while todo:
        base = todo.pop(0); out.append(base); cursor = base + 8
        while todo and todo[0] < cursor + 63 * 8:
            bits = 1
            while todo and todo[0] < cursor + 63 * 8:
                bits |= 1 << ((todo.pop(0) - cursor) // 8 + 1)
            out.append(bits); cursor += 63 * 8
    return out


def eh_frame_hdr(at, starts):
    """version 1, eh_frame_ptr pcrel sdata4, fde_count udata4, table datarel sdata4 (what patch_nso.py reads)."""
    out = bytearray(b'\x01\x1b\x03\x3b') + struct.pack('<iI', 0x100, len(starts))
    for s in sorted(starts): out += struct.pack('<ii', s - at, 0x100 + 16 * len(out))
    return bytes(out)


def make_nro(module_id=bytes(range(0x10, 0x24)) + bytes(12), tlsdesc=True, header_word=None, extra_symbols=None):
    image = bytearray(NRO_SIZE)
    # Text: RocrtHeader (version, MOD0 offset, version offset, reserved) and the NRO header, MOD0, then the code.
    struct.pack_into('<4I', image, 0, 0, MOD0, MOD0 + 0x34, 0)
    struct.pack_into('<4sIII', image, 0x10, b'NRO0', 0, NRO_SIZE, 0)
    struct.pack_into('<8I', image, 0x20, TEXT, RO - TEXT, RO, DATA - RO, DATA, NRO_SIZE - DATA, BSS_SIZE, 0)
    image[0x40:0x60] = module_id
    if header_word is not None: struct.pack_into('<I', image, 0x58, header_word)   # inside the module id
    for at, words in CODE.items(): struct.pack_into(f'<{len(words)}I', image, at, *words)
    # Ro: dynstr, dynsym, hash tables, relocation tables, eh_frame_hdr.
    dynstr, dynsym, hash_at, gnu_at, rela_at, jmprel_at, relr_at, ehdr_at = (
        0x4000, 0x4400, 0x4600, 0x4700, 0x4800, 0x4900, 0x4a00, 0x4b00)
    symbols = list(SYMBOLS) + (list(extra_symbols) if extra_symbols else [])
    strings = bytearray(b'\0'); offsets = []
    for name, *_ in symbols: offsets.append(len(strings)); strings += name.encode() + b'\0'
    image[dynstr:dynstr + len(strings)] = strings
    for i, (name, binding, kind, value) in enumerate(symbols):
        struct.pack_into('<IBBHQQ', image, dynsym + 24 * (i + 1), offsets[i], binding << 4 | kind, 0,
                         0 if value is None else (10 if kind == 6 else 1 if value < RO else 3), value or 0, 8)
    nsym = len(symbols) + 1
    nbucket = 3
    buckets, chains = [0] * nbucket, [0] * nsym
    for i in range(1, nsym):
        b = elf_hash(symbols[i - 1][0]) % nbucket
        chains[i], buckets[b] = buckets[b], i
    struct.pack_into(f'<II{nbucket}I{nsym}I', image, hash_at, nbucket, nsym, *buckets, *chains)
    first = next(i + 1 for i, s in enumerate(symbols) if s[3] is not None)
    hashes = [gnu_hash(symbols[i - 1][0]) for i in range(first, nsym)]
    bloom = 0
    for h in hashes: bloom |= 1 << (h % 64) | 1 << ((h >> 6) % 64)
    chain = [h & ~1 for h in hashes]; chain[-1] |= 1
    struct.pack_into(f'<IIIIQI{len(chain)}I', image, gnu_at, 1, first, 1, 6, bloom, first, *chain)
    rela = [(G_ABS_IMPORT, R_ABS64, SYM['_ZTVN10__cxxabiv117__class_type_infoE'], 16),
            (G_ABS_LOCAL, R_ABS64, SYM['nro_export_data'], 0),
            (G_GLOB, R_GLOB_DAT, SYM['_ZN2nn3mem17StandardAllocator8AllocateEm'], 0),
            (G_WEAK, R_GLOB_DAT, SYM['weak_optional_hook'], 0)]
    if tlsdesc: rela += [(G_TLS_LOCAL, R_TLSDESC, 0, 0x10), (G_TLS_SYM, R_TLSDESC, SYM['nro_tls_var'], 0)]
    for i, (where, kind, sym, addend) in enumerate(rela):
        struct.pack_into('<QQq', image, rela_at + 24 * i, where, sym << 32 | kind, addend)
    jmprel = [(G_JUMP0, R_JUMP_SLOT, SYM['pthread_mutex_lock'], 0), (G_JUMP1, R_JUMP_SLOT, SYM['__cxa_guard_acquire'], 0)]
    for i, (where, kind, sym, addend) in enumerate(jmprel):
        struct.pack_into('<QQq', image, jmprel_at + 24 * i, where, sym << 32 | kind, addend)
        struct.pack_into('<Q', image, where, 0x150)   # lazy GOT entries start at PLT0, as a linker leaves them
    relr = relr_encode(RELR_TARGETS)
    struct.pack_into(f'<{len(relr)}Q', image, relr_at, *relr)
    for where, value in RELR_TARGETS.items(): struct.pack_into('<Q', image, where, value)
    struct.pack_into('<Q', image, EXPORT_DATA, 0x1234)
    if extra_symbols:
        for name, binding, kind, value in extra_symbols:
            if value is not None and value >= DATA and value + 8 <= NRO_SIZE:
                struct.pack_into('<Q', image, value, 0x5555)
    ehdr = eh_frame_hdr(ehdr_at, CODE)
    image[ehdr_at:ehdr_at + len(ehdr)] = ehdr
    # MOD0 [19.0.0+]: offsets relative to MOD0; module object at the bss start; then the SDK version.
    struct.pack_into('<4s12i', image, MOD0, b'MOD0', DYNAMIC - MOD0, NRO_SIZE - MOD0, NRO_SIZE + BSS_SIZE - MOD0,
                     ehdr_at - MOD0, ehdr_at + len(ehdr) - MOD0, NRO_SIZE - MOD0, DYNAMIC - MOD0, INIT_ARRAY - MOD0,
                     0, 0, 0, 0)
    struct.pack_into('<3I', image, MOD0 + 0x34, 19, 3, 4)
    tags = [(4, hash_at), (0x6ffffef5, gnu_at), (5, dynstr), (6, dynsym), (10, len(strings)), (11, 24),
            (7, rela_at), (8, 24 * len(rela)), (9, 24), (23, jmprel_at), (2, 24 * len(jmprel)), (20, 7), (3, GOT),
            (36, relr_at), (35, 8 * len(relr)), (37, 8), (12, 0x140), (13, 0x144), (25, INIT_ARRAY), (27, 8), (0, 0)]
    for i, (tag, value) in enumerate(tags): struct.pack_into('<qQ', image, DYNAMIC + 16 * i, tag, value)
    # NRO header extents of dynstr / dynsym, relative to .rodata like an NSO's.
    struct.pack_into('<4I', image, 0x70, dynstr - RO, len(strings), dynsym - RO, 24 * nsym)
    return bytes(image)


def make_nrr(hashes, program_id=FC26_PROGRAM_ID, kind=0):
    hashes = sorted(hashes)
    size = (0x350 + 32 * len(hashes) + 0xfff) & ~0xfff
    out = bytearray(size)
    out[0:4] = b'NRR0'
    struct.pack_into('<QIB', out, 0x330, program_id, size, kind)
    struct.pack_into('<II', out, 0x340, 0x350, len(hashes))
    for i, h in enumerate(hashes): out[0x350 + 32 * i:0x370 + 32 * i] = h
    return bytes(out)


def other_hashes(n):
    return [hashlib.sha256(b'not this module %d' % i).digest() for i in range(n)]


def fake_rewrite(nro, directory, name):
    """The files patch_nso.py writes, with its layout formulas, for when capstone is not installed: every site in
    SITES becomes a branch into the patch area, the svc and timer sites get a gate row."""
    image = bytearray(nro + bytes(BSS_SIZE))
    key = (len(image) + 0x3fff) & ~0x3fff
    image.extend(bytes(0x4000))
    patch_off = (len(image) + 0xffff) & ~0xffff
    patch, gates = bytearray(), []
    for site, kind in SITES.items():
        block = patch_off + len(patch)
        if kind in ('svc', 'cntpct'):   # arg: the svc number (svc #1) or the timer's target register (x1)
            gates.append(f'{block + 8:#x}\t{kind}\t1\t{site:#x}')
        patch += struct.pack('<4I', NOP, NOP, NOP, 0x14000000 | (((site + 4 - (block + 12)) >> 2) & 0x3ffffff))
        struct.pack_into('<I', image, site, 0x14000000 | (((block - site) >> 2) & 0x3ffffff))
    patched = bytes(image) + bytes(patch_off - len(image)) + bytes(patch)
    (directory / f'{name}.patched.bin').write_bytes(patched)
    (directory / f'{name}.fixups.tsv').write_text(
        f'# PATCH_OFF\t{patch_off:#x}\n# KEY_PAGE_OFF\t{key:#x}\n# KEY_PAGE_SIZE\t0x4000\n# TEXT_END\t{RO:#x}\n'
        f'# RO_OFF\t{RO:#x}\n# DATA_OFF\t{DATA:#x}\n' +
        ''.join(f'# KEY_{k}_IDX\t{i}\n' for i, k in enumerate(('K18', 'KTLS', 'KTLR', 'KGATE', 'KRES0', 'KRES1', 'KASPECT', 'KASPECTUI'))))
    (directory / f'{name}.gates.tsv').write_text(''.join(g + '\n' for g in gates))
    return patched, gates


def make_library(exports=(), imports=(), strings=b'', module_id=bytes(range(0x80, 0x94)) + bytes(12)):
    """A small module with only symbols (an ExeFS-like main / sdk / rtld stand-in): exports defined in its text,
    undefined imports, and extra bytes in .rodata (strings a loader would look up by name)."""
    image = bytearray(0x3000)
    struct.pack_into('<4I', image, 0, 0, MOD0, MOD0 + 0x34, 0)
    struct.pack_into('<4sIII', image, 0x10, b'NRO0', 0, 0x3000, 0)
    struct.pack_into('<8I', image, 0x20, 0, 0x1000, 0x1000, 0x1000, 0x2000, 0x1000, 0, 0)
    image[0x40:0x60] = module_id
    struct.pack_into('<I', image, 0x100, RET)
    names = [(n, True) for n in exports] + [(n, False) for n in imports]
    dynstr, dynsym, hash_at, extra = 0x1000, 0x1400, 0x1c00, 0x1e00
    table = bytearray(b'\0'); offsets = []
    for n, _ in names: offsets.append(len(table)); table += n.encode() + b'\0'
    image[dynstr:dynstr + len(table)] = table
    for i, (n, defined) in enumerate(names):
        struct.pack_into('<IBBHQQ', image, dynsym + 24 * (i + 1), offsets[i], 1 << 4 | 2, 0, 1 if defined else 0, 0x100 if defined else 0, 4)
    nsym = len(names) + 1
    struct.pack_into(f'<II1I{nsym}I', image, hash_at, 1, nsym, nsym - 1, *[max(0, i - 1) for i in range(nsym)])
    image[extra:extra + len(strings)] = strings
    tags = [(4, hash_at), (5, dynstr), (6, dynsym), (10, len(table)), (11, 24), (0, 0)]
    for i, (tag, value) in enumerate(tags): struct.pack_into('<qQ', image, 0x2000 + 16 * i, tag, value)
    struct.pack_into('<4s6i', image, MOD0, b'MOD0', 0x2000 - MOD0, 0x3000 - MOD0, 0x3000 - MOD0, 0, 0, 0x3000 - MOD0)
    return bytes(image)


def make_elf(nro, tls=(0x10, 0x40, 0x10), build_id=None):
    """The module as an ELF64 (what a .nrs is): one PT_LOAD with the NRO image at file offset 0x1000, PT_DYNAMIC, PT_TLS
    (filesz, memsz, align) and a GNU build id note (the first 20 bytes of the NRO's module id by default)."""
    build_id = nro[0x40:0x54] if build_id is None else build_id
    note = struct.pack('<III', 4, len(build_id), 3) + b'GNU\0' + build_id
    note += bytes(-len(note) % 4)
    dynamic = struct.unpack_from('<i', nro, MOD0 + 4)[0] + MOD0
    phdrs = [(1, 5, 0x1000, 0, 0, len(nro), len(nro), 0x1000), (2, 6, 0x1000 + dynamic, dynamic, dynamic, 0x200, 0x200, 8),
             (7, 4, 0x1000 + DATA, DATA, DATA, tls[0], tls[1], tls[2]), (4, 4, 0x200, 0, 0, len(note), len(note), 4)]
    head = bytearray(0x1000)
    head[0:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', head, 16, 3, 183, 1, 0, 0x40, 0, 0, 64, 56, len(phdrs), 64, 0, 0)
    for i, p in enumerate(phdrs): struct.pack_into('<IIQQQQQQ', head, 0x40 + 56 * i, *p)
    head[0x200:0x200 + len(note)] = note
    return bytes(head) + nro
