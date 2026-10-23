#!/usr/bin/env python3
"""Wrap a Switch NRO (an nn::ro module) in an uncompressed NSO for the kit's rewriter, and check what comes back.

An NRO's segments already sit at their memory offsets and its text starts with the NRO header itself, so the NSO keeps
every byte: text, ro and data are copied as they are, the bss size and the module id (build id) go into the NSO header,
and MOD0 (inside the copied bytes) is untouched. third_party/d2r/patch_nso.py then reads it like an ExeFS module.

  info <nro>                   layout, MOD0, dynamic tags, relocation counts and imports (JSON)
  wrap <nro> <nso>             write the NSO and prove the round trip (the NSO's segments give back the NRO byte for byte)
  unwrap <nso> <nro>           the NRO again from such an NSO
  register <nro> <dir> <name>  after `patch_nso.py <nso> <dir> <name>`: check that the rewrite kept what must not change
                               and record the image in <dir>/nro_manifest.tsv under the NRO's SHA-256 (read by runtime/ro)
  symbols <module> [--prefix]  imports and exports of an NRO or NSO (ExeFS ones too; compressed segments need lz4)
  nrr <nrr> [<nro>...]         an NRR's header, whether its hash list is sorted, and whether each NRO is listed in it

Layouts: switchbrew NRO0, NSO0, MOD and NRR0 pages. Only the files named on the command line are read.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'third_party/d2r'))   # FC 26's own copy of the rewriter (relr.py has no dependencies)
from relr import decode_relr

PAGE = 0x1000                      # Horizon page: NRO segments and the ro service work in 4 KiB units
NRO_HEADER_SIZE = 0x80
NSO_HEADER_SIZE = 0x100
MOD0_SIZE = 0x1c                   # [19.0.0+] the header grows to 0x34 (relro, debug link, build id note)
FLAG_ALIGNED_HEADER, FLAG_COMPRESS = 1, 2
NSO_FLAG_HASHES = 0x38             # text / ro / data hashes present; nothing compressed
MANIFEST = 'nro_manifest.tsv'
DT = dict(NULL=0, PLTRELSZ=2, PLTGOT=3, HASH=4, STRTAB=5, SYMTAB=6, RELA=7, RELASZ=8, RELAENT=9, STRSZ=10, SYMENT=11,
          INIT=12, FINI=13, PLTREL=20, JMPREL=23, INIT_ARRAY=25, FINI_ARRAY=26, INIT_ARRAYSZ=27, FINI_ARRAYSZ=28,
          RELRSZ=35, RELR=36, RELRENT=37, GNU_HASH=0x6ffffef5, RELACOUNT=0x6ffffff9, NEEDED=1)
TAG_NAMES = {v: 'DT_' + k for k, v in DT.items()}
RELOC_NAMES = {257: 'ABS64', 258: 'ABS32', 1025: 'GLOB_DAT', 1026: 'JUMP_SLOT', 1027: 'RELATIVE', 1031: 'TLSDESC'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def page_up(x, page):
    return (x + page - 1) & ~(page - 1)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_nro(data):
    """The NRO header, checked the way the ro service checks a module before mapping it."""
    require(len(data) >= NRO_HEADER_SIZE, 'NRO shorter than its header')
    magic, version, size, flags = struct.unpack_from('<4sIII', data, 0x10)
    require(magic == b'NRO0', 'not an NRO (no NRO0 signature at 0x10)')
    text_off, text_size, ro_off, ro_size, data_off, data_size, bss_size, extra = struct.unpack_from('<8I', data, 0x20)
    h = dict(version=version, size=size, flags=flags, text_off=text_off, text_size=text_size, ro_off=ro_off,
             ro_size=ro_size, data_off=data_off, data_size=data_size, bss_size=bss_size, additional_header=extra,
             module_id=data[0x40:0x60].hex(), dso_handle=struct.unpack_from('<I', data, 0x60)[0],
             embedded=struct.unpack_from('<II', data, 0x68), dynstr=struct.unpack_from('<II', data, 0x70),
             dynsym=struct.unpack_from('<II', data, 0x78), mod0=struct.unpack_from('<I', data, 4)[0])
    require(not flags & FLAG_COMPRESS, 'compressed NRO (23.0.0+ format) is not supported')
    require(size <= len(data), f'NRO header size {size:#x} beyond the file ({len(data):#x} bytes)')
    for name in ('text_size', 'ro_size', 'data_size', 'bss_size'):
        require(h[name] % PAGE == 0, f'NRO {name} {h[name]:#x} is not page aligned')
    require(text_off == 0 and text_off + text_size == ro_off and ro_off + ro_size == data_off
            and data_off + data_size == size, 'NRO segments are not contiguous from 0 to the NRO size')
    require(NRO_HEADER_SIZE <= h['mod0'] and h['mod0'] + MOD0_SIZE <= size, 'MOD0 offset outside the NRO')
    require(data[h['mod0']:h['mod0'] + 4] == b'MOD0', 'no MOD0 at the offset given at +4')
    return h


def parse_mod0(image, mod0):
    words = struct.unpack_from('<4s6i', image, mod0)
    fields = ['dynamic', 'bss_start', 'bss_end', 'eh_frame_hdr_start', 'eh_frame_hdr_end', 'module_object']
    out = {k: mod0 + v for k, v in zip(fields, words[1:])}
    extra = ['relro_start', 'full_relro_end', 'nx_debuglink_start', 'nx_debuglink_end', 'build_id_note_start',
             'build_id_note_end']
    if mod0 + 0x34 <= len(image):   # present from 19.0.0 on; older modules have other bytes there
        out['sdk19_fields'] = {k: mod0 + v for k, v in zip(extra, struct.unpack_from('<6i', image, mod0 + MOD0_SIZE))}
    return out


def parse_dynamic(image, mod0):
    dyn = mod0 + struct.unpack_from('<i', image, mod0 + 4)[0]
    tags, needed = {}, []
    for offset in range(dyn, min(len(image), dyn + 16 * 4096) - 15, 16):
        tag, value = struct.unpack_from('<qQ', image, offset)
        if tag == DT['NULL']:
            return dyn, tags, needed
        if tag == DT['NEEDED']: needed.append(value)
        else: tags[tag] = value
    raise ValueError('unterminated dynamic table')


def symbol_count(image, tags):
    # DT_HASH's nchain is the symbol count; patch_nso.py reads it the same way (tags[4] + 4).
    require(DT['HASH'] in tags, 'no DT_HASH in the dynamic table (the rewriter and runtime/ro count symbols with it)')
    return struct.unpack_from('<I', image, tags[DT['HASH']] + 4)[0]


def symbols(image, tags):
    require(tags.get(DT['SYMENT'], 24) == 24, 'unexpected DT_SYMENT')
    out = []
    for i in range(symbol_count(image, tags)):
        name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', image, tags[DT['SYMTAB']] + 24 * i)
        start = tags[DT['STRTAB']] + name
        end = image.index(0, start, tags[DT['STRTAB']] + tags[DT['STRSZ']])
        out.append(dict(name=image[start:end].decode(), value=value, size=size, defined=bool(shndx),
                        binding=info >> 4, type=info & 15))
    return out


def relocations(image, tags, lower, upper):
    """RELR (implicit addends) then RELA and JMPREL: [(where, type, symbol index, addend, table)]."""
    out = [(where, 1027, 0, addend, 'relr') for where, addend in decode_relr(image, tags, lower, upper)]
    if DT['JMPREL'] in tags:
        require(tags.get(DT['PLTREL']) == DT['RELA'], 'JMPREL is not RELA')
    for table, size, name in ((DT['RELA'], DT['RELASZ'], 'rela'), (DT['JMPREL'], DT['PLTRELSZ'], 'jmprel')):
        if table not in tags: continue
        require(tags.get(size, 0) % 24 == 0 and (table != DT['RELA'] or tags.get(DT['RELAENT'], 24) == 24),
                f'{name}: unexpected entry size')
        for offset in range(tags[table], tags[table] + tags.get(size, 0), 24):
            where, info, addend = struct.unpack_from('<QQq', image, offset)
            require(lower <= where <= upper - 8, f'{name} relocation outside data: {where:#x}')
            out.append((where, info & 0xffffffff, info >> 32, addend, name))
    return out


def describe(data):
    h = parse_nro(data)
    image = data[:h['size']]
    mod = parse_mod0(image + bytes(h['bss_size']), h['mod0'])
    dyn, tags, needed = parse_dynamic(image, h['mod0'])
    syms = symbols(image, tags)
    relocs = relocations(image, tags, h['data_off'], h['size'] + h['bss_size'])
    counts = {}
    for _, kind, _, _, table in relocs:
        key = f'{table}:{RELOC_NAMES.get(kind, kind)}'
        counts[key] = counts.get(key, 0) + 1
    imports = sorted({syms[s]['name'] for _, kind, s, _, _ in relocs if s and not syms[s]['defined']})
    ro = h['ro_off']
    def agreement(field, tag):
        off = h[field][0]
        return 'ro-relative' if ro + off == tags.get(tag) else 'absolute' if off == tags.get(tag) else 'other'
    return dict(sha256=sha256(image), file_bytes=len(data), header=h, mod0=mod, dynamic_offset=dyn,
                tags={TAG_NAMES.get(k, hex(k)): hex(v) for k, v in sorted(tags.items())}, needed=needed, symbols=len(syms),
                exports=sum(1 for s in syms if s['defined']), relocations=counts, imports=imports,
                header_dynsym=agreement('dynsym', DT['SYMTAB']), header_dynstr=agreement('dynstr', DT['STRTAB']))


def wrap(data):
    """The NSO for patch_nso.py: the NRO's segments copied at their own offsets, no compression."""
    h = parse_nro(data)
    image = data[:h['size']]
    _, tags, _ = parse_dynamic(image, h['mod0'])
    segments = [(h['text_off'], h['text_size']), (h['ro_off'], h['ro_size']), (h['data_off'], h['data_size'])]
    out = bytearray(NSO_HEADER_SIZE)
    struct.pack_into('<4sIII', out, 0, b'NSO0', 0, 0, NSO_FLAG_HASHES)
    file_offset = NSO_HEADER_SIZE
    for i, (memory, size) in enumerate(segments):
        last = (NSO_HEADER_SIZE, 0, h['bss_size'])[i]   # module name offset / module name size / bss size
        struct.pack_into('<4I', out, 0x10 + 0x10 * i, file_offset, memory, size, last)
        struct.pack_into('<I', out, 0x60 + 4 * i, size)                    # stored size = size (uncompressed)
        out[0xa0 + 0x20 * i:0xc0 + 0x20 * i] = hashlib.sha256(image[memory:memory + size]).digest()
        file_offset += size
    out[0x40:0x60] = data[0x40:0x60]                                       # module id (build id)
    struct.pack_into('<II', out, 0x88, *h['embedded'])
    nsym = symbol_count(image, tags)
    # NSO dynstr / dynsym are relative to .rodata: taken from the dynamic table, which is what rtld itself reads.
    if DT['STRTAB'] in tags and tags[DT['STRTAB']] >= h['ro_off'] and DT['SYMTAB'] in tags and tags[DT['SYMTAB']] >= h['ro_off']:
        struct.pack_into('<4I', out, 0x90, tags[DT['STRTAB']] - h['ro_off'], tags.get(DT['STRSZ'], 0),
                         tags[DT['SYMTAB']] - h['ro_off'], nsym * 24)
    else:
        struct.pack_into('<4I', out, 0x90, *h['dynstr'], *h['dynsym'])
    for memory, size in segments:
        out += image[memory:memory + size]
    nso = bytes(out)
    require(unwrap(nso) == image, 'round trip failed: the NSO segments do not give back the NRO')
    return nso


def nso_image(nso):
    """The NSO's memory image as patch_nso.py / nsoimg.py build it: segments at their offsets, then zero bss."""
    require(nso[:4] == b'NSO0', 'not an NSO')
    flags = struct.unpack_from('<I', nso, 0xc)[0]
    segs = [struct.unpack_from('<III', nso, 0x10 + 0x10 * i) for i in range(3)]
    bss = struct.unpack_from('<I', nso, 0x3c)[0]
    stored = struct.unpack_from('<III', nso, 0x60)
    image = bytearray(segs[2][1] + segs[2][2] + bss)
    for i, (file_offset, memory, size) in enumerate(segs):
        require(file_offset + stored[i] <= len(nso), f'NSO segment {i} truncated')
        raw = nso[file_offset:file_offset + stored[i]]
        if flags >> i & 1:
            import lz4.block   # only compressed (ExeFS) modules need it; it is in requirements.txt
            raw = lz4.block.decompress(raw, uncompressed_size=size)
        require(len(raw) == size, f'NSO segment {i} has {len(raw):#x} bytes, header says {size:#x}')
        image[memory:memory + size] = raw
    return bytes(image), segs, bss


def unwrap(nso):
    image, segs, _ = nso_image(nso)
    require(segs[0][1] == 0 and segs[0][1] + segs[0][2] == segs[1][1] and segs[1][1] + segs[1][2] == segs[2][1],
            'NSO segments are not contiguous (not made by wrap)')
    nro = image[:segs[2][1] + segs[2][2]]
    require(nro[0x10:0x14] == b'NRO0', 'the NSO text does not start with an NRO header (not made by wrap)')
    return nro


def module_symbols(data, prefix=''):
    """Imports (undefined dynamic symbols) and exports of an NRO or NSO, optionally only names starting with prefix."""
    if data[0x10:0x14] == b'NRO0':
        h = parse_nro(data)
        image = data[:h['size']] + bytes(h['bss_size'])
    else:
        image = nso_image(data)[0]
    mod0 = struct.unpack_from('<I', image, 4)[0]
    require(image[mod0:mod0 + 4] == b'MOD0', 'no MOD0 at the offset given at +4')
    _, tags, needed = parse_dynamic(image, mod0)
    syms = [s for s in symbols(image, tags)[1:] if s['name'].startswith(prefix)]
    return dict(imports=sorted(s['name'] for s in syms if not s['defined']),
                exports=sorted((dict(name=s['name'], value=hex(s['value']), type=s['type']) for s in syms if s['defined']),
                               key=lambda s: s['name']), needed=needed)


def describe_nrr(data, nros=()):
    require(len(data) >= 0x350 and data[:4] == b'NRR0', 'not an NRR')
    program_id, size, kind = struct.unpack_from('<QIB', data, 0x330)
    offset, count = struct.unpack_from('<II', data, 0x340)
    require(offset >= 0x350 and offset + 32 * count <= len(data), 'NRR hash list outside the file')
    hashes = [data[offset + 32 * i:offset + 32 * i + 32] for i in range(count)]
    listed = {}
    for path in nros:
        nro = Path(path).read_bytes()
        digest = hashlib.sha256(nro[:parse_nro(nro)['size']]).digest()
        listed[str(path)] = dict(sha256=digest.hex(), listed=digest in hashes)
    return dict(program_id=f'{program_id:016x}', size=size, size_matches_file=size == len(data), kind=kind,
                hash_offset=hex(offset), hashes=count, sorted=hashes == sorted(hashes), nros=listed)


def read_layout(path):
    layout = {}
    for line in path.read_text().splitlines():
        if line.startswith('#'):
            key, value = line[1:].split()
            layout[key] = int(value, 0)
    return layout


def branch_target(word, address):
    if word & 0xfc000000 != 0x14000000: return None
    return address + 4 * (((word & 0x3ffffff) ^ 0x2000000) - 0x2000000)


def check_rewrite(nro, patched, layout, gates_text):
    """What the rewrite of an NRO must keep: header, MOD0, ro, data and bss bytes; only text sites may change."""
    h = parse_nro(nro)
    size, bss = h['size'], h['bss_size']
    image_end = size + bss
    key, patch = layout.get('KEY_PAGE_OFF'), layout.get('PATCH_OFF')
    require(layout.get('TEXT_END') == h['text_size'] and layout.get('RO_OFF') == h['ro_off']
            and layout.get('DATA_OFF') == h['data_off'], 'fixups.tsv layout does not match the NRO header')
    require(key == page_up(image_end, 0x4000) and patch == page_up(image_end + 0x4000, 0x10000),
            'fixups.tsv key page / patch area not where patch_nso.py puts them')
    require([layout.get(f'KEY_{k}_IDX') for k in ('K18', 'KTLS', 'KTLR', 'KGATE')] == [0, 1, 2, 3],
            'unexpected key page indices (runtime/ro writes slot i at index i, as loader.c does)')
    require(len(patched) >= patch, 'patched image shorter than its patch area offset')
    require(patched[:NRO_HEADER_SIZE] == nro[:NRO_HEADER_SIZE], 'the rewrite changed the NRO header (0x0-0x80)')
    mod0 = h['mod0']
    require(patched[mod0:mod0 + MOD0_SIZE] == nro[mod0:mod0 + MOD0_SIZE], 'the rewrite changed MOD0')
    require(patched[h['ro_off']:size] == nro[h['ro_off']:size], 'the rewrite changed ro or data bytes')
    require(not any(patched[size:patch]), 'bss, key page or padding not zero in the patched image')
    sites = 0
    for address in range(0, h['text_size'], 4):
        old, new = struct.unpack_from('<I', nro, address)[0], struct.unpack_from('<I', patched, address)[0]
        if old == new: continue
        target = branch_target(new, address)
        call_window = old == 0xd63f0240 and new == 0xd63f03c0   # BLR_X18 -> BLR_X30 (call_window.py; not imported: needs capstone)
        require(call_window or (target is not None and patch <= target < len(patched)),
                f'text word at {address:#x} changed to something other than a branch into the patch area')
        sites += 1
    gates = []
    for line in gates_text.splitlines():
        ret, kind, arg, original = line.split()
        require(kind in ('svc', 'cntpct', 'cntvct'), f'unknown gate kind {kind}')
        require(patch <= int(ret, 0) <= len(patched) and int(original, 0) < h['text_size'], f'gate outside the module: {line}')
        gates.append(line)
    return dict(sites=sites, gates=len(gates), patch_bytes=len(patched) - patch)


def register(nro_path, directory, name):
    require(name and all(c.isalnum() or c in '._-' for c in name) and name != 'main', 'invalid module name')
    nro = nro_path.read_bytes()
    h = parse_nro(nro)
    nro = nro[:h['size']]
    patched = (directory / f'{name}.patched.bin').read_bytes()
    layout = read_layout(directory / f'{name}.fixups.tsv')
    result = check_rewrite(nro, patched, layout, (directory / f'{name}.gates.tsv').read_text())
    row = [sha256(nro), name, sha256(patched), str(h['size']), str(h['bss_size']), h['module_id']]
    manifest = directory / MANIFEST
    lines = manifest.read_text().splitlines() if manifest.exists() else []
    header = '# nro_sha256\tname\tpatched_sha256\tnro_size\tbss_size\tmodule_id'
    kept = [l for l in lines if l and not l.startswith('#') and l.split('\t')[0] != row[0] and l.split('\t')[1] != name]
    manifest.write_text('\n'.join([header] + kept + ['\t'.join(row)]) + '\n')
    return dict(result, nro_sha256=row[0], patched_sha256=row[2], manifest=str(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('info').add_argument('nro', type=Path)
    p = sub.add_parser('wrap'); p.add_argument('nro', type=Path); p.add_argument('nso', type=Path)
    p = sub.add_parser('unwrap'); p.add_argument('nso', type=Path); p.add_argument('nro', type=Path)
    p = sub.add_parser('register'); p.add_argument('nro', type=Path); p.add_argument('dir', type=Path); p.add_argument('name')
    p = sub.add_parser('symbols'); p.add_argument('module', type=Path); p.add_argument('--prefix', default='')
    p = sub.add_parser('nrr'); p.add_argument('nrr', type=Path); p.add_argument('nros', type=Path, nargs='*')
    a = parser.parse_args()
    if a.command == 'info':
        print(json.dumps(describe(a.nro.read_bytes()), indent=2))
    elif a.command == 'wrap':
        data = a.nro.read_bytes()
        nso = wrap(data)
        a.nso.write_bytes(nso)
        h = parse_nro(data)
        print(json.dumps(dict(status='pass', nro_sha256=sha256(data[:h['size']]), nso_sha256=sha256(nso),
                              build_id=h['module_id'], text=h['text_size'], ro=h['ro_size'], data=h['data_size'],
                              bss=h['bss_size'], round_trip='byte-identical')))
    elif a.command == 'unwrap':
        a.nro.write_bytes(unwrap(a.nso.read_bytes()))
    elif a.command == 'symbols':
        print(json.dumps(module_symbols(a.module.read_bytes(), a.prefix), indent=2))
    elif a.command == 'nrr':
        print(json.dumps(describe_nrr(a.nrr.read_bytes(), a.nros), indent=2))
    else:
        print(json.dumps(dict(status='pass', **register(a.nro, a.dir, a.name))))


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(f'nro_to_nso: {error}')
