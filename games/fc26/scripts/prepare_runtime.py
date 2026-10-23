#!/usr/bin/env python3
"""Bind the native loader to the verified FC 26 rewrite and RomFS: generated headers stay in the work folder.

Writes <work>/build/runtime_tables.h (modules, symbols, relocations, gates), romfs_config.h and
extracted/<version>/romfs/runtime-index.bin (the RomFS index the runtime reads), and shared_fonts_config.h.
The modules, their order and the version folder come from assets/game.json (scripts/game_config.py). Every input is
checked against assets/expected-v<version>.json first.

FC 26 1.0.0 has no update: the RomFS is scripts/extract_romfs.py's romfs.bin + index.json, used as they are (the kit's
earlier fork merged a sparse base and its update into the same two files).

--record: on the first run on the Mac, measure every pin that is still null (ExeFS and rewrite SHA-256, main's build ID,
the RomFS SHA-256), check it against what is already pinned (sizes, file count, hash prefix) and write it into the
expected file. Run it only after story 1's checks passed (structck and equiv for every module), then commit the file.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'third_party/d2r'))   # FC 26's own copy of the rewriter
sys.path.insert(0, str(HERE / 'scripts'))           # also under python -I, which drops the script's folder
from relr import decode_relr
import game_config

VERSION = game_config.VERSION
MODULES = game_config.MODULES
R_ABS64, R_GLOB_DAT, R_JUMP_SLOT, R_RELATIVE = 257, 1025, 1026, 1027
RELOC_NAMES = {257: 'R_AARCH64_ABS64', 1024: 'R_AARCH64_COPY', 1025: 'R_AARCH64_GLOB_DAT', 1026: 'R_AARCH64_JUMP_SLOT',
               1027: 'R_AARCH64_RELATIVE', 1028: 'R_AARCH64_TLS_DTPMOD64', 1029: 'R_AARCH64_TLS_DTPREL64',
               1030: 'R_AARCH64_TLS_TPREL64', 1031: 'R_AARCH64_TLSDESC', 1032: 'R_AARCH64_IRELATIVE'}
TABLES_WARN_BYTES = 64 << 20


def need(ok, message):
    if not ok:
        raise SystemExit(f'prepare_runtime: {message}')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


class Pins:
    """assets/expected-v<version>.json: pins are compared; with --record a null pin takes the measured value."""
    def __init__(self, path, record):
        self.path, self.record, self.data, self.recorded = path, record, json.loads(path.read_text()), []

    def check(self, keys, value, what):
        node = self.data
        for k in keys[:-1]:
            node = node[k]
        pinned = node.get(keys[-1])
        if pinned is None:
            need(self.record, f'{what}: no pin yet in {self.path.name} ({".".join(keys)}); after story 1\'s checks run '
                              f'scripts/prepare_runtime.py --record once, then commit {self.path.name}')
            node[keys[-1]] = value
            self.recorded.append(f'{".".join(keys)} = {value}')
            return
        need(pinned == value, f'{what}: {value} differs from the pinned {pinned} ({".".join(keys)} in {self.path.name})')

    def save(self):
        if self.recorded:
            self.path.write_text(json.dumps(self.data, indent=4) + '\n')
            print(f'recorded in {self.path}:\n  ' + '\n  '.join(self.recorded), file=sys.stderr)


def module_table(work, name, pins):
    path = work / f'rewritten/{VERSION}/{name}.patched.bin'
    need(path.exists(), f'{path} missing: the rewrite of {name} (story 1) goes to rewritten/{VERSION}')
    image = path.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    pins.check(['rewritten_sha256', f'{name}.patched.bin'], digest, f'rewrite {name}')
    exefs = work / f'extracted/{VERSION}/exefs/{name}'   # its hash was checked by exefs_pins
    need(exefs.exists(), f'{exefs} missing (scripts/extract_exefs.py)')
    layout = {}
    for line in (work / f'rewritten/{VERSION}/{name}.fixups.tsv').read_text().splitlines():
        _, key, value = line.split()
        layout[key] = int(value, 0)
    mod0 = struct.unpack_from('<I', image, 4)[0]
    need(image[mod0:mod0 + 4] == b'MOD0', f'{name}: no MOD0 at {mod0:#x}')
    dyn = mod0 + struct.unpack_from('<i', image, mod0 + 4)[0]
    tags = {}
    for offset in range(dyn, dyn + 4096 * 16, 16):
        tag, value = struct.unpack_from('<qQ', image, offset)
        if tag == 0: break
        tags[tag] = value
    else: raise SystemExit(f'prepare_runtime: {name}: unterminated dynamic table')
    if 4 in tags:
        nsym = struct.unpack_from('<I', image, tags[4] + 4)[0]
    else:
        raw_header = exefs.read_bytes()[:256]
        _, _, symbol_offset, symbol_size = struct.unpack_from('<IIII', raw_header, 0x90)
        need(layout['RO_OFF'] + symbol_offset == tags[6] and symbol_size % 24 == 0, f'{name}: cannot establish the symbol count')
        nsym = symbol_size // 24
    need(tags.get(11) == 24 and tags.get(9, 24) == 24, f'{name}: DT_SYMENT {tags.get(11)} / DT_RELAENT {tags.get(9)}, expected 24')
    need(23 not in tags or tags.get(20) == 7, f'{name}: DT_PLTREL {tags.get(20)}, expected 7 (RELA)')
    symbols = []
    for i in range(nsym):
        no, info, other, section, value, size = struct.unpack_from('<IBBHQQ', image, tags[6] + 24 * i)
        end = image.index(0, tags[5] + no, tags[5] + tags[10])
        symbols.append(dict(name=image[tags[5] + no:end].decode(), value=value, size=size,
                            defined=bool(section), binding=info >> 4, type=info & 15))
    relocs = [dict(where=where, kind=R_RELATIVE, symbol=0, addend=addend)
              for where, addend in decode_relr(image, tags, layout['DATA_OFF'], layout['KEY_PAGE_OFF'])]
    relocated = {reloc['where'] for reloc in relocs}
    for address, size in [(tags.get(7, 0), tags.get(8, 0)), (tags.get(23, 0), tags.get(2, 0))]:
        need(size % 24 == 0, f'{name}: relocation table size {size} is not a multiple of 24')
        for offset in range(address, address + size, 24):
            where, info, addend = struct.unpack_from('<QQq', image, offset)
            kind, si = info & 0xffffffff, info >> 32
            # TODO(mac): the loader (runtime/loader.c relocate) knows these four kinds only. FC 26's video module has
            # TLSDESC relocations (BRIEFING); if main or sdk has one too, this stops here with its name.
            need(kind in (R_ABS64, R_GLOB_DAT, R_JUMP_SLOT, R_RELATIVE),
                 f'{name}: relocation {RELOC_NAMES.get(kind, kind)} ({kind}) at {where:#x} is not supported by the loader')
            need(si < nsym, f'{name}: relocation at {where:#x} names symbol {si} of {nsym}')
            need(layout['DATA_OFF'] <= where <= layout['KEY_PAGE_OFF'] - 8, f'{name}: relocation at {where:#x} outside data')
            need(kind != R_RELATIVE or 0 <= addend < layout['KEY_PAGE_OFF'], f'{name}: relative addend {addend:#x} at {where:#x}')
            need(where not in relocated, f'{name}: duplicate RELR/RELA relocation at {where:#x}')
            relocated.add(where)
            relocs.append(dict(where=where, kind=kind, symbol=si, addend=addend))
    gates = []
    for line in (work / f'rewritten/{VERSION}/{name}.gates.tsv').read_text().splitlines():
        ret, kind, arg, original = line.split()
        need(kind in ['cntpct', 'cntvct', 'svc'], f'{name}: unknown gate kind {kind}')
        # ret may be negative (a gate in the pre-island); store it as an unsigned 64-bit offset from base, which the
        # loader adds to base (base + (uint64)ret wraps to base - |ret|), so a negative offset resolves correctly.
        gates.append(dict(ret=int(ret, 0) & ((1 << 64) - 1), timer=kind != 'svc', arg=int(arg), original=int(original, 0)))
    pre_size, pre_digest = pre_island(work, name, layout, pins)
    return dict(name=name, sha256=digest, size=len(image), layout=layout, tags=tags, symbols=symbols,
                relocs=relocs, gates=gates, ctor_flag=ctor_flag(image, tags, layout, name),
                pre_size=pre_size, pre_digest=pre_digest)


def pre_island(work, name, layout, pins):
    """Pre-island (games/fc26/docs/ILHAS_NUVEM.md): present only when the rewrite needed a patch area before base.
    Its SHA-256 is pinned like patched.bin's (rewritten_sha256.<name>.pre.bin: compared, or written by --record) and
    baked into the table with its size, so the loader verifies the .pre.bin it maps. Returns (pre_size, pre_digest);
    (0, '') when there is no island, and then a non-null pin for one is an error (it belongs to another rewrite)."""
    key = f'{name}.pre.bin'
    pre_size = layout.get('PRE_PATCH_SIZE', 0)
    if not pre_size:
        need(pins.data['rewritten_sha256'].get(key) is None,
             f'{name}: {key} is pinned in {pins.path.name} but {name}.fixups.tsv declares no pre-island')
        return 0, ''
    pre_path = work / f'rewritten/{VERSION}/{key}'
    need(pre_path.exists(), f'{pre_path} missing but {name}.fixups.tsv declares a pre-island')
    pre_bytes = pre_path.read_bytes()
    need(len(pre_bytes) == pre_size, f'{name}: {pre_path.name} is {len(pre_bytes)} bytes, fixups says {pre_size}')
    need(layout.get('PRE_PATCH_OFF', 0) == -pre_size, f'{name}: PRE_PATCH_OFF {layout.get("PRE_PATCH_OFF")} != -PRE_PATCH_SIZE')
    used = layout.get('PRE_PATCH_USED', 0)
    need(0 < used <= pre_size and pre_bytes[used:] == bytes(pre_size - used),
         f'{name}: PRE_PATCH_USED {used:#x} missing or the island past it is not zero padding')
    pre_digest = hashlib.sha256(pre_bytes).hexdigest()
    pins.check(['rewritten_sha256', key], pre_digest, f'pre-island {name}')
    return pre_size, pre_digest


def ctor_flag(image, tags, layout, name):
    """The constructor-state word DT_INIT tests (the loader checks it reads 2 after DT_INIT).

    The first adrp + ldr w (same register) in DT_INIT's first 16 instructions is decoded, and the register pair is
    reported so a different shape is visible."""
    need(12 in tags, f'{name}: no DT_INIT (the loader runs each module\'s DT_INIT)')
    init = tags[12]
    words = [struct.unpack_from('<I', image, init + 4 * i)[0] for i in range(16)]
    for i, a in enumerate(words):
        if a & 0x9f000000 != 0x90000000: continue
        reg = a & 31
        for j in range(i + 1, len(words)):
            w = words[j]
            if w & 0xffc00000 == 0xb9400000 and (w >> 5) & 31 == reg:
                imm = ((a >> 29) & 3) | (((a >> 5) & 0x7ffff) << 2)
                imm = (imm ^ (1 << 20)) - (1 << 20)
                flag = ((init + 4 * i) & ~4095) + (imm << 12) + ((w >> 10) & 0xfff) * 4
                need(layout['DATA_OFF'] <= flag < layout['KEY_PAGE_OFF'], f'{name}: ctor flag outside data')
                print(f'{name}: DT_INIT ctor flag at {flag:#x} (adrp x{reg} at +{4*i:#x}, ldr at +{4*j:#x})', file=sys.stderr)
                return flag
    # TODO(mac): a DT_INIT of another shape needs its constructor-state word found by hand (disassemble DT_INIT).
    raise SystemExit(f'prepare_runtime: {name}: no constructor-state load (adrp + ldr w) in DT_INIT\'s first 16 '
                     f'instructions at {init:#x}: ' + ' '.join(f'{w:08x}' for w in words))


def probe_plt(main, image):
    """The PLT stub through which main calls nn::os::GetSystemTick (the probe calls it on 4 threads).

    The PLT sits at the end of main's text: 16 bytes per JUMP_SLOT after a 32-byte header. The window searched is that
    size plus slack (at least 64 KiB, the earlier fork's fixed window), so a main with many imports is covered."""
    target = '_ZN2nn2os13GetSystemTickEv'
    slots = [r['where'] for r in main['relocs'] if r['kind'] == R_JUMP_SLOT and main['symbols'][r['symbol']]['name'] == target]
    # TODO(mac): if FC 26's main does not import GetSystemTick through its PLT, pick another sdk function main calls.
    need(len(slots) == 1, f'main: {len(slots)} JUMP_SLOT relocations for {target}, expected 1')
    slot = slots[0]
    njump = sum(r['kind'] == R_JUMP_SLOT for r in main['relocs'])
    end = main['layout']['TEXT_END']
    window = max(0x10000, 0x20 + 16 * njump + 0x1000)
    plt = []
    for address in range(max(0, end - window), end - 12, 4):
        a, b, c, d = struct.unpack_from('<IIII', image, address)
        if a & 0x9f00001f != 0x90000010 or b & 0xffc003ff != 0xf9400211 or d != 0xd61f0220: continue
        imm = ((a >> 29) & 3) | (((a >> 5) & 0x7ffff) << 2)
        imm = (imm ^ (1 << 20)) - (1 << 20)
        if (address & ~4095) + (imm << 12) + ((b >> 10) & 0xfff) * 8 == slot: plt.append(address)
    need(len(plt) == 1, f'main: PLT stubs for {target} in the last {window:#x} bytes of text: {[hex(p) for p in plt]}, expected 1')
    return plt[0], slot


# Symbols the runtime looks up by name and cannot start without (runtime/loader.c required(), the probe's PLT target).
REQUIRED = {'nnMain': 'the game entry (loader.c verify_identity)',
            '_ZN2nn4init5StartEmmPFvvES2_S2_': 'the SDK startup boot calls (loader.c boot)',
            '_ZN2nn2os13GetSystemTickEv': 'what the probe calls through main\'s PLT'}


def check_required(modules):
    """Every REQUIRED symbol is defined by some module; else stop now, naming similar exports, rather than at boot."""
    defined = {s['name'] for m in modules for s in m['symbols'] if s['defined'] and s['name']}
    missing = []
    for name, why in REQUIRED.items():
        if name in defined: continue
        stem = name[:name.find('E', 8)] if name.startswith('_ZN') else name   # the qualified name without its parameters
        similar = sorted(n for n in defined if stem in n)[:5]
        missing.append(f'{name} ({why}) is defined by none of {[m["name"] for m in modules]}; similar: {similar or "none"}')
    # TODO(mac): a different nn::init::Start signature in SDK 19.3.4 is fixed in runtime/loader.c boot() and here.
    # loader.c verify_identity (every mode, probe included) compares nnMain's address in the relocations that name it
    # without the PLT (ABS64 / GLOB_DAT) with the definition, and needs at least one.
    refs = [(m['name'], RELOC_NAMES[r['kind']]) for m in modules for r in m['relocs']
            if r['kind'] in (R_ABS64, R_GLOB_DAT) and m['symbols'][r['symbol']]['name'] == 'nnMain']
    if not refs:
        missing.append('no ABS64 / GLOB_DAT relocation names nnMain, which runtime/loader.c verify_identity needs '
                       '(TODO(mac): find how the SDK reaches nnMain and adapt verify_identity)')
    need(not missing, '; '.join(missing))
    # The story-2 checkpoint (TOTK_VERIFY_STARTUP=nnmain) and the "ENTER nnMain" log come from the observer the loader
    # puts on the JUMP_SLOT relocations of nnMain (the SDK calling it through its PLT). Without one they never show.
    calls = [m['name'] for m in modules for r in m['relocs'] if r['kind'] == R_JUMP_SLOT and m['symbols'][r['symbol']]['name'] == 'nnMain']
    if not calls:
        # TODO(mac): without a PLT call of nnMain, stop at its entry another way (TOTK_VERIFY_STARTUP=1 stops later).
        print('warning: no module calls nnMain through its PLT: TOTK_VERIFY_STARTUP=nnmain will not fire', file=sys.stderr)
    return dict(nnmain_references=refs, nnmain_plt_callers=calls)


def runtime_tables(work, out, pins):
    modules = [module_table(work, n, pins) for n in MODULES]
    nnmain = check_required(modules)
    main = modules[0]
    image = (work / f'rewritten/{VERSION}/main.patched.bin').read_bytes()
    plt, slot = probe_plt(main, image)
    lines = ['/* Generated locally from validated player images; do not commit. */']
    for n, m in enumerate(modules):
        lines.append(f'static const Reloc reloc_{n}[] = {{')
        lines.extend(f'{{{r["where"]}ULL,{r["kind"]},{r["symbol"]},{r["addend"]}LL}},' for r in m['relocs'])
        lines.append('};')
        lines.append(f'static const Symbol symbol_{n}[] = {{')
        lines.extend('{' + f'{json.dumps(s["name"])},{s["value"]}ULL,{s["size"]}ULL,{int(s["defined"])},{s["binding"]},{s["type"]}' + '},' for s in m['symbols'])
        lines.append('};')
        lines.append(f'static const Gate gate_{n}[] = {{')
        lines.extend(f'{{{g["ret"]}ULL,{g["original"]}ULL,{int(g["timer"])},{g["arg"]}}},' for g in m['gates'])
        if not m['gates']: lines.append('{0,0,0,0},')
        lines.append('};')
    lines.append('static Module modules[] = {')
    for n, m in enumerate(modules):
        l = m['layout']
        lines.append('{' + f'.name={json.dumps(m["name"])},.digest={json.dumps(m["sha256"])},.pre_digest={json.dumps(m["pre_digest"])},.file_size={m["size"]}ULL,.text_end={l["TEXT_END"]}ULL,.ro_off={l["RO_OFF"]}ULL,.data_off={l["DATA_OFF"]}ULL,.patch_off={l["PATCH_OFF"]}ULL,.key_off={l["KEY_PAGE_OFF"]}ULL,.pre_size={m["pre_size"]}ULL,.symbols=symbol_{n},.nsym={len(m["symbols"])},.relocs=reloc_{n},.nreloc={len(m["relocs"])},.gates=gate_{n},.ngate={len(m["gates"])},.init={m["tags"].get(12,0)}ULL,.ctor_flag={m["ctor_flag"]}ULL,.init_array={m["tags"].get(25,0)}ULL,.init_size={m["tags"].get(27,0)}ULL' + '},')
    lines.append('};')
    lines.append(f'#define PROBE_PLT {plt}ULL\n#define PROBE_SLOT {slot}ULL')
    text = '\n'.join(lines) + '\n'
    (out / 'runtime_tables.h').write_text(text)
    if len(text) > TABLES_WARN_BYTES:
        # TODO(mac): measure clang's time and memory on this header; if it does not fit the 8 GB Mac, load the
        # relocation rows from a binary file instead of C arrays.
        print(f'warning: runtime_tables.h is {len(text) >> 20} MiB; compiling it needs much memory', file=sys.stderr)
    (work / 'analysis').mkdir(exist_ok=True)
    (work / 'analysis/runtime-layout.json').write_text(json.dumps(modules, indent=2) + '\n')
    return dict(modules=[m['name'] for m in modules], relocations=sum(len(m['relocs']) for m in modules),
                symbols=sum(len(m['symbols']) for m in modules), main_plt=hex(plt), tables_bytes=len(text), **nnmain)


def build_id(work):
    raw = (work / f'extracted/{VERSION}/exefs/main').read_bytes()
    need(raw[:4] == b'NSO0', 'exefs/main is not an NSO')
    return raw[0x40:0x54].hex().upper()


def exefs_pins(work, pins):
    """Every ExeFS file (rtld and main.npdm too, which the runtime does not load), main's build ID, and the size of the
    NSP the extraction read (extraction-manifest.json, written by scripts/extract_exefs.py next to exefs/)."""
    manifest = work / f'extracted/{VERSION}/extraction-manifest.json'
    need(manifest.exists(), f'{manifest} missing (scripts/extract_exefs.py writes it)')
    source = json.loads(manifest.read_text()).get('source_size')
    need(source == pins.data['source_nsp_size'], f'the ExeFS came from a {source}-byte file, pinned NSP is {pins.data["source_nsp_size"]} bytes')
    for name in sorted(pins.data['exefs_sha256']):
        path = work / f'extracted/{VERSION}/exefs/{name}'
        need(path.exists(), f'{path} missing (scripts/extract_exefs.py)')
        pins.check(['exefs_sha256', name], sha(path), f'ExeFS {name}')
    pins.check(['main_build_id'], build_id(work), 'main build ID')


def romfs_config(work, out, pins):
    folder = work / f'extracted/{VERSION}/romfs'
    need((folder / 'index.json').exists(), f'{folder}/index.json missing (scripts/extract_romfs.py)')
    manifest = json.loads((folder / 'index.json').read_text())
    need(manifest.get('status') == 'pass', f'{folder}/index.json: extraction status {manifest.get("status")}')
    want = pins.data['romfs']
    need(manifest['romfs_size'] == want['size'], f'RomFS size {manifest["romfs_size"]}, pinned {want["size"]}')
    need(len(manifest['files']) == want['files'], f'RomFS has {len(manifest["files"])} files, pinned {want["files"]}')
    need(manifest['romfs_sha256'].startswith(want['sha256_prefix']), f'RomFS SHA-256 {manifest["romfs_sha256"]} does not start with {want["sha256_prefix"]}')
    pins.check(['romfs', 'sha256'], manifest['romfs_sha256'], 'RomFS SHA-256')
    need((folder / 'romfs.bin').stat().st_size == manifest['romfs_size'], f'{folder}/romfs.bin size differs from index.json')
    strings, rows = bytearray(), bytearray()
    for item in manifest['files']:
        name = item['path'].encode() + b'\0'
        rows.extend(struct.pack('<QQII', item['offset'], item['size'], len(strings), len(name)))
        strings.extend(name)
    index = struct.pack('<8sQQ', b'TOTKRFS1', len(manifest['files']), 24 + len(rows)) + rows + strings
    (folder / 'runtime-index.bin').write_bytes(index)
    (out / 'romfs_config.h').write_text(f'#define ROMFS_IMAGE_SIZE {manifest["romfs_size"]}ULL\n'
                                        f'#define ROMFS_IMAGE_SHA256 "{manifest["romfs_sha256"]}"\n'
                                        f'#define ROMFS_INDEX_SHA256 "{hashlib.sha256(index).hexdigest()}"\n')
    return dict(files=len(manifest['files']), index_bytes=len(index))


def shared_fonts_config(work, out):
    """The six system fonts, when extracted to <work>/extracted/firmware/shared-fonts (scripts/extract_shared_fonts.py).
    A game NSP does not contain them; without them the rows are empty and the runtime stops if the game asks for one."""
    folder = work / 'extracted/firmware/shared-fonts'
    if not (folder / 'manifest.json').exists():
        rows = ['{"",0ULL,0ULL,""}'] * 6
        state = 'missing (the game stops with a message if it asks for one)'
    else:
        manifest = json.loads((folder / 'manifest.json').read_text())
        need(manifest['status'] == 'pass' and [f['type'] for f in manifest['fonts']] == list(range(6)), f'{folder}/manifest.json')
        rows = []
        for f in manifest['fonts']:
            path = folder / f"{f['type']}-{f['name']}.bfttf"
            need(path.stat().st_size == f['bfttf_bytes'] == f['font_bytes'] + 8, f'{path} size')
            rows.append(f'{{"{path}",{f["bfttf_bytes"]}ULL,{f["font_bytes"]}ULL,"{f["sha256"]}"}}')
        state = 'loaded from ' + str(folder)
    (out / 'shared_fonts_config.h').write_text('#define SHARED_FONT_COUNT 6\n#define SHARED_FONT_ROWS ' + ','.join(rows) + '\n')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--work', type=Path, default=HERE / game_config.CONFIG['work'])
    parser.add_argument('--record', action='store_true', help='write the measured value of every null pin (see above)')
    args = parser.parse_args()
    problems = game_config.check_config() + game_config.check_game_version_h()
    need(not problems, '; '.join(problems))
    work = args.work.resolve()
    out = work / 'build'
    out.mkdir(parents=True, exist_ok=True)
    for stale in ('runtime_tables.h', 'romfs_config.h', 'shared_fonts_config.h'):   # a failed run leaves none of them,
        (out / stale).unlink(missing_ok=True)                                     # so make runtime cannot mix two runs
    pins = Pins(game_config.EXPECTED_PATH, args.record)
    romfs = romfs_config(work, out, pins)
    exefs_pins(work, pins)
    runtime = runtime_tables(work, out, pins)
    fonts = shared_fonts_config(work, out)
    pins.save()
    print(json.dumps(dict(runtime=runtime, romfs=romfs, shared_fonts=fonts, recorded=len(pins.recorded))))


if __name__ == '__main__':
    main()
