#!/usr/bin/env python3
"""Answer story 3's questions about the game binary (docs/ESTORIA3_NUVEM.md, P1-P7) from the files already extracted.

Reads <work>/extracted/<version>/exefs (main, sdk, rtld, subsdk*), the RomFS image and index there, the rewritten images
in <work>/rewritten/<version> and the runtime's C sources (which imports the host replaces). Writes
<work>/analysis/estoria3_perguntas.json and .md and prints the Markdown. --extract also writes the .nro / .nrr / .nrs
files to <work>/nro for the rewrite. Nothing is run; nothing leaves the work folder.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nro_to_nso as tool

PROGRAM_ID = 0x01004FF021942000   # BRIEFING.md: Title ID of FC 26
VIDEO_MODULE = 'Engine.Render.Core2.PlatformNvn'
# What BRIEFING.md ("Fatos do módulo de vídeo", measured on the Mac on 22/10) says about the video module.
BRIEFING_FACTS = dict(size=962560, text_size=0xb0000, ro_off=0xb0000, ro_size=0x30000, data_off=0xe0000,
                      data_size=0xb000, bss_size=0xb000, abs64=52, glob_dat=4, tlsdesc=2, jump_slot=79, imports=82,
                      needed=0)
SERVICE_NAMES = (b'ldr:ro', b'ro:1')


def romfs_files(romfs_dir):
    index = json.loads((romfs_dir / 'index.json').read_text())
    return index['files']


def romfs_read(romfs_dir, item):
    with open(romfs_dir / 'romfs.bin', 'rb') as f:
        f.seek(item['offset'])
        return f.read(item['size'])


def module_image(data):
    if data[0x10:0x14] == b'NRO0':
        h = tool.parse_nro(data)
        return data[:h['size']] + bytes(h['bss_size'])
    return tool.nso_image(data)[0]


def counted_strings(image, names):
    """How many times each name appears as a whole C string."""
    return {n.decode(): len(re.findall(re.escape(n) + rb'\x00', image)) for n in names}


def elf_info(data):
    """PT_TLS, the GNU build id and the TLSDESC relocations of an ELF64 (the .nrs is the module as an ELF)."""
    tool.require(data[:4] == b'\x7fELF' and data[4] == 2 and data[5] == 1, 'not a little-endian ELF64')
    phoff, = struct.unpack_from('<Q', data, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', data, 0x36)
    phdrs = [struct.unpack_from('<IIQQQQQQ', data, phoff + phentsize * i) for i in range(phnum)]
    loads = [(p[3], p[2], p[5]) for p in phdrs if p[0] == 1]   # vaddr, offset, filesz
    def at(vaddr):
        for v, o, n in loads:
            if v <= vaddr < v + n: return o + vaddr - v
        raise ValueError(f'ELF address {vaddr:#x} outside the loaded segments')
    def parse_notes(offset, filesz):
        o = offset
        while o + 12 <= offset + filesz:
            namesz, descsz, kind = struct.unpack_from('<III', data, o)
            name = data[o + 12:o + 12 + namesz]
            desc = data[o + 12 + (namesz + 3 & ~3):][:descsz]
            if kind == 3 and name.rstrip(b'\0') == b'GNU': return desc.hex()
            o += 12 + (namesz + 3 & ~3) + (descsz + 3 & ~3)
        return None
    out = dict(tls=None, build_id=None, tlsdesc=[], program_headers=len(phdrs))
    for p_type, _, offset, vaddr, _, filesz, memsz, align in phdrs:
        if p_type == 7: out['tls'] = dict(vaddr=hex(vaddr), filesz=filesz, memsz=memsz, align=align)
        if p_type == 4:   # notes: namesz, descsz, type, name, desc (4-byte aligned)
            out['build_id'] = parse_notes(offset, filesz)
        if p_type == 2:
            tags = {}
            for o in range(offset, offset + filesz - 15, 16):
                tag, value = struct.unpack_from('<qQ', data, o)
                if tag == 0: break
                tags[tag] = value
            symtab, strtab = tags.get(6), tags.get(5)
            for table, size in ((tags.get(7), tags.get(8, 0)), (tags.get(23), tags.get(2, 0))):
                if not table: continue
                for o in range(at(table), at(table) + size, 24):
                    _, info, addend = struct.unpack_from('<QQq', data, o)
                    if info & 0xffffffff != 1031: continue
                    index = info >> 32
                    name = '(local)'
                    if index and symtab and strtab:
                        name_off = struct.unpack_from('<I', data, at(symtab) + 24 * index)[0]
                        start = at(strtab) + name_off
                        name = data[start:data.index(0, start)].decode()
                    out['tlsdesc'].append(dict(symbol=name, addend=addend))
    if out['build_id'] is None and len(data) >= 0x40:
        shoff, = struct.unpack_from('<Q', data, 0x28)
        shentsize, shnum = struct.unpack_from('<HH', data, 0x3a)
        if shoff and shentsize and shnum:
            for i in range(shnum):
                sh_type, _, _, sh_offset, sh_size = struct.unpack_from('<IQQQQ', data, shoff + shentsize * i + 4)
                if sh_type == 7:   # SHT_NOTE
                    bid = parse_notes(sh_offset, sh_size)
                    if bid:
                        out['build_id'] = bid
                        break
    return out


def overrides(runtime_dir, names):
    """Imports whose mangled name appears as a string literal in the runtime's C sources (the host's replacements)."""
    text = ''.join(p.read_text(errors='replace') for p in sorted(runtime_dir.glob('*.c')) + sorted(runtime_dir.glob('*.m')))
    return sorted(n for n in names if f'"{n}"' in text)


def answer(work, version, runtime_dir, extract=False):
    exefs = work / f'extracted/{version}/exefs'
    romfs = work / f'extracted/{version}/romfs'
    rewritten = work / f'rewritten/{version}'
    report = dict(work=str(work), version=version)

    raw = {p.name: p.read_bytes() for p in sorted(exefs.iterdir())
           if p.is_file() and (p.name in ('main', 'sdk', 'rtld') or p.name.startswith('subsdk'))}
    modules = {n: module_image(data) for n, data in raw.items()}
    listing = {n: tool.module_symbols(data, '') for n, data in raw.items() if n != 'rtld'}
    exports = {e['name'] for n, l in listing.items() for e in l['exports']}

    # P1: nn::ro the game calls, and where the library is
    main_ro = [n for n in listing.get('main', {}).get('imports', []) if n.startswith('_ZN2nn2ro')]
    sdk_ro = [e['name'] for e in listing.get('sdk', {}).get('exports', []) if e['name'].startswith('_ZN2nn2ro')]
    report['P1'] = dict(main_imports_nn_ro=main_ro, sdk_exports_nn_ro=sdk_ro,
                        nn_ro_in_sdk=bool(main_ro) and all(n in sdk_ro for n in main_ro),
                        main_nn_ro_not_in_sdk=[n for n in main_ro if n not in sdk_ro])

    # P2: names of nn::ro symbols rtld looks up (rtld is not run by the host)
    rtld_names = sorted({m.decode() for m in re.findall(rb'_ZN2nn2ro[0-9A-Za-z_]+', modules['rtld'])}) if 'rtld' in modules else None
    sdk_detail = [n for n in sdk_ro if n.startswith('_ZN2nn2ro6detail')]
    report['P2'] = dict(rtld_present='rtld' in modules, rtld_nn_ro_names=rtld_names,
                        rtld_names_exported_by_sdk=[n for n in rtld_names or [] if n in sdk_ro], sdk_nn_ro_detail_exports=sdk_detail)

    # P3: which port the SDK can open
    report['P3'] = {n: counted_strings(modules[n], SERVICE_NAMES) for n in ('sdk', 'main') if n in modules}

    # P6 first: the files themselves
    files = [f for f in romfs_files(romfs) if f['path'].endswith(('.nro', '.nrr', '.nrs'))]
    blobs = {f['path']: romfs_read(romfs, f) for f in files}
    if extract:
        (work / 'nro').mkdir(exist_ok=True)
        for path, data in blobs.items(): (work / 'nro' / Path(path).name).write_bytes(data)
    nros = {p: d for p, d in blobs.items() if p.endswith('.nro')}
    nrrs = {p: d for p, d in blobs.items() if p.endswith('.nrr')}
    p6 = dict(files=[dict(path=f['path'], size=f['size']) for f in files], nrr={})
    digests = {p: hashlib.sha256(d[:tool.parse_nro(d)['size']]).digest() for p, d in nros.items()}   # what the service hashes
    for path, data in nrrs.items():
        info = tool.describe_nrr(data)
        listed = {data[int(info['hash_offset'], 16) + 32 * i:][:32] for i in range(info['hashes'])}
        info['nros'] = {p: dict(sha256=d.hex(), listed=d in listed) for p, d in digests.items()}
        info['program_id_is_fc26'] = info['program_id'] == f'{PROGRAM_ID:016x}'
        p6['nrr'][path] = info
    report['P6'] = p6

    # The video module: BRIEFING facts, P4 (TLS), P5 (imports) and P7 (rewrite)
    video = next((p for p in nros if Path(p).name == f'{VIDEO_MODULE}.nro'), next(iter(nros), None))
    report['video_module'] = video
    if video:
        info = tool.describe(nros[video])
        h, r = info['header'], info['relocations']
        measured = dict(size=h['size'], text_size=h['text_size'], ro_off=h['ro_off'], ro_size=h['ro_size'],
                        data_off=h['data_off'], data_size=h['data_size'], bss_size=h['bss_size'],
                        abs64=r.get('rela:ABS64', 0), glob_dat=r.get('rela:GLOB_DAT', 0), tlsdesc=r.get('rela:TLSDESC', 0),
                        jump_slot=r.get('jmprel:JUMP_SLOT', 0), imports=len(info['imports']), needed=len(info['needed']))
        report['briefing_facts'] = {k: dict(briefing=v, measured=measured[k], same=v == measured[k]) for k, v in BRIEFING_FACTS.items()}
        report['video_info'] = dict(sha256=info['sha256'], module_id=h['module_id'], relocations=r, tags=info['tags'],
                                    header_dynsym=info['header_dynsym'])
        image = nros[video][:h['size']] + bytes(h['bss_size'])
        _, tags, _ = tool.parse_dynamic(image, h['mod0'])
        syms = tool.symbols(image, tags)
        relocs = tool.relocations(image, tags, h['data_off'], len(image))
        tls_symbols = sorted({syms[s]['name'] if s else '(local)' for _, kind, s, _, _ in relocs if kind == 1031})
        nrs_path = video[:-4] + '.nrs'
        p4 = dict(nro_tlsdesc_symbols=tls_symbols, nrs=None)
        if nrs_path in blobs:
            e = elf_info(blobs[nrs_path])
            e['build_id_matches_nro'] = bool(e['build_id']) and h['module_id'].startswith(e['build_id'])
            p4['nrs'] = e
        report['P4'] = p4
        weak = {syms[s]['name'] for _, kind, s, _, _ in relocs if s and not syms[s]['defined'] and syms[s]['binding'] == 2}
        imports = info['imports']
        report['P5'] = dict(imports=len(imports), runtime_sources=str(runtime_dir),
                            not_exported_strong=[n for n in imports if n not in exports and n not in weak],
                            not_exported_weak=[n for n in imports if n not in exports and n in weak],
                            overridden_by_host=overrides(runtime_dir, imports) if runtime_dir.is_dir() else None)
        manifest = rewritten / tool.MANIFEST
        p7 = dict(state='not rewritten yet')
        if manifest.exists():
            row = next((l.split('\t') for l in manifest.read_text().splitlines()
                        if l and not l.startswith('#') and l.split('\t')[0] == info['sha256']), None)
            if row:
                name = row[1]
                try:
                    p7 = dict(state='registered', name=name, **tool.check_rewrite(
                        nros[video], (rewritten / f'{name}.patched.bin').read_bytes(),
                        tool.read_layout(rewritten / f'{name}.fixups.tsv'), (rewritten / f'{name}.gates.tsv').read_text()))
                except ValueError as error:
                    p7 = dict(state='rewrite refused', name=name, reason=str(error))
        report['P7'] = p7
    return report


def markdown(r):
    yes = lambda b: 'sim' if b else 'não'
    out = [f'# Estória 3 — respostas do binário ({r["version"]})', '']
    p1 = r['P1']
    out += ['## P1 — nn::ro que o `main` chama', f'- {len(p1["main_imports_nn_ro"])} importações `_ZN2nn2ro*` no main; '
            f'{len(p1["sdk_exports_nn_ro"])} exportações no sdk; biblioteca no sdk: **{yes(p1["nn_ro_in_sdk"])}**']
    out += [f'  - `{n}`' for n in p1['main_imports_nn_ro']]
    if p1['main_nn_ro_not_in_sdk']: out.append(f'- Fora do sdk: {", ".join(p1["main_nn_ro_not_in_sdk"])}')
    p2 = r['P2']
    out += ['', '## P2 — estado que só o `rtld` monta (decide caminho A × B)']
    if not p2['rtld_present']: out.append('- `rtld` não encontrado no ExeFS.')
    else:
        names = p2['rtld_nn_ro_names']
        out.append(f'- Nomes `_ZN2nn2ro*` no rtld: {len(names)}; exportados pelo sdk: {len(p2["rtld_names_exported_by_sdk"])}')
        out += [f'  - `{n}`' for n in names]
        out.append('- Leitura: ' + ('o rtld procura símbolos do nn::ro no sdk pelo nome — indício de que o nn::ro depende de '
                                    'estado que o rtld preenche (o MNG não roda o rtld): planejar A\' ou B.' if names else
                                    'nenhum nome do nn::ro no rtld — sem indício por nome (não descarta outro mecanismo).'))
    out += ['', '## P3 — porta do serviço'] + [f'- {m}: ' + ', '.join(f'`{k}` ×{v}' for k, v in c.items()) for m, c in r['P3'].items()]
    p6 = r['P6']
    out += ['', '## P6 — arquivos e NRR'] + [f'- `{f["path"]}` ({f["size"]} bytes)' for f in p6['files']]
    for path, n in p6['nrr'].items():
        out.append(f'- `{path}`: program_id {n["program_id"]} (FC 26: {yes(n["program_id_is_fc26"])}), {n["hashes"]} hashes, '
                   f'ordenado: {yes(n["sorted"])}, kind {n["kind"]}')
        out += [f'  - `{p}` listado: **{yes(v["listed"])}**' for p, v in n['nros'].items()]
    if r.get('video_module'):
        out += ['', f'## Fatos do BRIEFING para `{r["video_module"]}`']
        out += [f'- {k}: BRIEFING {v["briefing"]}, medido {v["measured"]}' + ('' if v['same'] else ' **← DIFERENTE**')
                for k, v in r['briefing_facts'].items()]
        p4 = r['P4']
        out += ['', '## P4 — TLS do módulo', f'- TLSDESC no NRO: {", ".join(p4["nro_tlsdesc_symbols"]) or "nenhum"}']
        if p4['nrs']:
            n = p4['nrs']
            out.append(f'- .nrs: PT_TLS {n["tls"]}; build id confere com o NRO: {yes(n["build_id_matches_nro"])}; '
                       f'TLSDESC: {", ".join(f"{t["symbol"]}+{t["addend"]:#x}" for t in n["tlsdesc"]) or "nenhum"}')
        else: out.append('- .nrs não encontrado na RomFS.')
        p5 = r['P5']
        out += ['', '## P5 — importações do módulo', f'- {p5["imports"]} importações; faltam no main/sdk (fortes): '
                f'{len(p5["not_exported_strong"])}; (weak): {len(p5["not_exported_weak"])}']
        out += [f'  - falta: `{n}`' for n in p5['not_exported_strong']]
        ov = p5['overridden_by_host']
        out.append(f'- Sobrepostas pelo host ({p5["runtime_sources"]}): ' + ('fontes do runtime não encontradas' if ov is None else
                   (', '.join(f'`{n}`' for n in ov) or 'nenhuma')))
        p7 = r['P7']
        label = {'not rewritten yet': 'ainda não reescrito (passo 4 do ESTORIA3_NUVEM.md)', 'registered': 'registrada e conferida',
                 'rewrite refused': '**reescrita RECUSADA**'}[p7['state']]
        detail = f' — {p7["reason"]}' if 'reason' in p7 else f' — {p7["sites"]} pontos reescritos, {p7["gates"]} gates' if 'sites' in p7 else ''
        out += ['', '## P7 — reescrita', f'- {label}{detail}']
    return '\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path.home() / 'fc26-switch/work')
    parser.add_argument('--version', default='v100')
    default_runtime = HERE.parent / 'runtime'
    parser.add_argument('--runtime', type=Path, default=default_runtime)
    parser.add_argument('--extract', action='store_true', help='also write the .nro / .nrr / .nrs files to <work>/nro')
    a = parser.parse_args()
    report = answer(a.work, a.version, a.runtime, a.extract)
    (a.work / 'analysis').mkdir(exist_ok=True)
    (a.work / 'analysis/estoria3_perguntas.json').write_text(json.dumps(report, indent=2) + '\n')
    text = markdown(report)
    (a.work / 'analysis/estoria3_perguntas.md').write_text(text)
    print(text)


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(f'estoria3_perguntas: {error}')
