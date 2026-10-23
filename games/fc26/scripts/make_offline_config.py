#!/usr/bin/env python3
"""Build the RomFS offline configuration package for EA SPORTS FC 26.

Generates overlay files served in place of the originals (runtime/romfs.c, TOTK_ROMFS_PATCHES):
1. Data/nxcert.ini: offline parameters confirmed in the game's executable (main) to neutralize
   EA online dependencies (Kickoff force offline, single machine, local server, no auto-squad,
   pre-login disabled, dynamic content disabled, live messaging disabled, telemetry disabled).
2. Scripts/BootIni/MemoryInit.ini: conservative heap reductions for online and reserve heaps:
   - RainyDayPP on .nx: reduced from 169M (final) / 53M (otp) / 15M (debug) to 4M (PC/Linux default),
     freeing up 165 MB of physical RAM.
   - OnlinePP on .nx: reduced from 22M to 1M (with allowGrow=1), freeing up 21 MB of physical RAM.
3. manifest.tsv: the kit overlay manifest mapping relative RomFS paths, modified sizes,
   modified SHA-256, and original RomFS SHA-256.

Usage:
  python3 scripts/make_offline_config.py [--work <folder>] [--romfs <folder>] [--output <folder>]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import game_config

VERSION = game_config.VERSION

# Online keys confirmed to exist in main (under ONLINE/<KEY>) from reverse engineering
CONFIRMED_ONLINE_KEYS = [
    ("KICKOFF_FORCE_OFFLINE", "1", "Força Kickoff 100% offline sem download de elencos"),
    ("SINGLEMACHINE", "1", "Restringe loop do jogo a máquina local sem discovery"),
    ("USE_LOCALSERVER", "1", "Usa servidor local embutido para simulação"),
    ("NO_AUTO_SQUAD", "1", "Desativa checagem automática e CRC de elencos online"),
    ("PERFORM_PRE_LOGIN", "0", "Desativa tela e requisição de pré-login Nucleus"),
    ("DYNAMIC_CONTENT_ENABLED", "0", "Desativa busca de banners e eventos live service"),
    ("LIVE_MESSAGING_ENABLED", "0", "Desativa mensagens em tempo real da EA"),
    ("REPLAY_UPLOAD_ENABLE", "0", "Desativa envio de vídeos de melhores momentos"),
    ("ENABLE_INPUT_QOS_TELEMETRY", "0", "Desativa telemetria de qualidade de conexão/input"),
    ("DISABLE_OTP", "1", "Desativa exigência de código de uso único"),
    ("NOIDLE", "1", "Desativa desconexão automática por inatividade"),
    ("NOIDLEDISCONNECT", "1", "Impede desconexão nos menus por tempo ocioso"),
]


def patch_nxcert(text):
    """Update or add confirmed offline keys in the [ONLINE] section of nxcert.ini.

    Preserves line endings (\r\n vs \n), comments, and existing values not overridden.
    Returns (modified_text, list_of_changes).
    """
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()

    keys_dict = {k: v for k, v, _ in CONFIRMED_ONLINE_KEYS}
    desc_dict = {k: d for k, _, d in CONFIRMED_ONLINE_KEYS}

    changes = []
    in_online = False
    online_idx = -1
    next_section_idx = len(lines)
    found_keys = set()

    for i, line in enumerate(lines):
        striped = line.strip()
        if striped.startswith('[') and striped.endswith(']'):
            section = striped[1:-1].strip().upper()
            if section == 'ONLINE':
                in_online = True
                online_idx = i
            elif in_online:
                next_section_idx = i
                break
        elif in_online:
            if '=' in line and not striped.startswith('#') and not striped.startswith(';'):
                k, v = line.split('=', 1)
                k_clean = k.strip().upper()
                if k_clean in keys_dict:
                    orig_val = v.strip()
                    new_val = keys_dict[k_clean]
                    lines[i] = f"{k.rstrip()}={new_val}"
                    found_keys.add(k_clean)
                    changes.append({
                        'file': 'Data/nxcert.ini',
                        'key': k_clean,
                        'original_value': orig_val,
                        'new_value': new_val,
                        'description': desc_dict[k_clean],
                        'action': 'updated' if orig_val != new_val else 'kept'
                    })

    if online_idx == -1:
        # If [ONLINE] was missing entirely, append it
        lines.append('[ONLINE]')
        for k, v in keys_dict.items():
            lines.append(f"{k}={v}")
            changes.append({
                'file': 'Data/nxcert.ini',
                'key': k,
                'original_value': None,
                'new_value': v,
                'description': desc_dict[k],
                'action': 'added'
            })
    else:
        # Insert missing keys at the end of the [ONLINE] section
        to_insert = []
        for k, v in keys_dict.items():
            if k not in found_keys:
                to_insert.append(f"{k}={v}")
                changes.append({
                    'file': 'Data/nxcert.ini',
                    'key': k,
                    'original_value': None,
                    'new_value': v,
                    'description': desc_dict[k],
                    'action': 'added'
                })
        lines[next_section_idx:next_section_idx] = to_insert

    modified_text = nl.join(lines) + nl
    return modified_text, changes


def patch_memory_init(text):
    """Apply conservative heap cuts to MemoryInit.ini on .nx configurations.

    - RainyDayPP on .nx: reduce coreSize to 4M (PC/Linux baseline).
    - OnlinePP on .nx: reduce coreSize to 1M (allowGrow=1 remains active).
    Returns (modified_text, list_of_changes).
    """
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()
    changes = []

    for i, line in enumerate(lines):
        striped = line.strip()
        if striped.startswith('#') or striped.startswith(';'):
            continue

        if 'RainyDayPP' in line and '.nx' in line:
            m = re.search(r'coreSize\s*=\s*(\d+M)', line)
            if m:
                orig_size = m.group(1)
                new_size = '4M'
                new_line = line[:m.start(1)] + new_size + line[m.end(1):]
                lines[i] = new_line
                changes.append({
                    'file': 'Scripts/BootIni/MemoryInit.ini',
                    'arena': 'RainyDayPP',
                    'line': i + 1,
                    'original_size': orig_size,
                    'new_size': new_size,
                    'original_line': line,
                    'new_line': new_line
                })

        elif 'OnlinePP' in line and 'AddArena.nx' in line:
            m = re.search(r'coreSize\s*=\s*(\d+M)', line)
            if m:
                orig_size = m.group(1)
                new_size = '1M'
                new_line = line[:m.start(1)] + new_size + line[m.end(1):]
                lines[i] = new_line
                changes.append({
                    'file': 'Scripts/BootIni/MemoryInit.ini',
                    'arena': 'OnlinePP',
                    'line': i + 1,
                    'original_size': orig_size,
                    'new_size': new_size,
                    'original_line': line,
                    'new_line': new_line
                })

    modified_text = nl.join(lines) + nl
    return modified_text, changes


def read_index_bin(path):
    """Read TOTKRFS1 runtime-index.bin to map RomFS path -> (offset, size)."""
    data = path.read_bytes()
    magic, count, strings = struct.unpack_from('<8sQQ', data, 0)
    if magic != b'TOTKRFS1' or strings != 24 + count * 24 or strings > len(data):
        raise ValueError(f'{path}: not a valid TOTKRFS1 RomFS index')
    files = {}
    for i in range(count):
        offset, size, name_off, length = struct.unpack_from('<QQII', data, 24 + i * 24)
        name = data[strings + name_off:strings + name_off + length - 1].decode('utf-8', errors='replace')
        files[name] = (offset, size)
    return files


def read_romfs_file(romfs_dir, rel_path):
    """Read a RomFS file by relative path, supporting loose files or romfs.bin image.

    Returns (bytes_content, sha256_hex).
    """
    loose_path = romfs_dir / rel_path
    if loose_path.is_file():
        content = loose_path.read_bytes()
        return content, hashlib.sha256(content).hexdigest()

    image_path = romfs_dir / 'romfs.bin'
    if image_path.is_file():
        index_json = romfs_dir / 'index.json'
        if index_json.is_file():
            meta = json.loads(index_json.read_text())
            for item in meta.get('files', []):
                if item.get('path') == rel_path:
                    offset = item['offset']
                    size = item['size']
                    with image_path.open('rb') as f:
                        f.seek(offset)
                        content = f.read(size)
                    if len(content) != size:
                        raise ValueError(f'{rel_path}: premature EOF reading from {image_path}')
                    return content, hashlib.sha256(content).hexdigest()

        runtime_index = romfs_dir / 'runtime-index.bin'
        if runtime_index.is_file():
            files_map = read_index_bin(runtime_index)
            if rel_path in files_map:
                offset, size = files_map[rel_path]
                with image_path.open('rb') as f:
                    f.seek(offset)
                    content = f.read(size)
                if len(content) != size:
                    raise ValueError(f'{rel_path}: premature EOF reading from {image_path}')
                return content, hashlib.sha256(content).hexdigest()

    raise FileNotFoundError(f'RomFS file {rel_path!r} not found in {romfs_dir} (neither loose nor in romfs.bin)')


def generate_offline_package(romfs_dir, output_dir, nxcert_override=None, memory_init_override=None):
    """Generate modified Data/nxcert.ini, Scripts/BootIni/MemoryInit.ini and manifest.tsv.

    Returns report dictionary with hashes and logged changes.
    """
    output_dir = Path(output_dir)

    # 1. Read originals
    if nxcert_override and Path(nxcert_override).is_file():
        nxcert_bytes = Path(nxcert_override).read_bytes()
        nxcert_orig_sha = hashlib.sha256(nxcert_bytes).hexdigest()
    else:
        nxcert_bytes, nxcert_orig_sha = read_romfs_file(Path(romfs_dir), 'Data/nxcert.ini')

    if memory_init_override and Path(memory_init_override).is_file():
        mem_bytes = Path(memory_init_override).read_bytes()
        mem_orig_sha = hashlib.sha256(mem_bytes).hexdigest()
    else:
        mem_bytes, mem_orig_sha = read_romfs_file(Path(romfs_dir), 'Scripts/BootIni/MemoryInit.ini')

    # 2. Patch contents
    nxcert_text = nxcert_bytes.decode('utf-8', errors='replace')
    mod_nxcert_text, nxcert_changes = patch_nxcert(nxcert_text)
    mod_nxcert_bytes = mod_nxcert_text.encode('utf-8')
    mod_nxcert_sha = hashlib.sha256(mod_nxcert_bytes).hexdigest()

    mem_text = mem_bytes.decode('utf-8', errors='replace')
    mod_mem_text, mem_changes = patch_memory_init(mem_text)
    mod_mem_bytes = mod_mem_text.encode('utf-8')
    mod_mem_sha = hashlib.sha256(mod_mem_bytes).hexdigest()

    # 3. Write modified files
    out_nxcert = output_dir / 'Data/nxcert.ini'
    out_nxcert.parent.mkdir(parents=True, exist_ok=True)
    out_nxcert.write_bytes(mod_nxcert_bytes)

    out_mem = output_dir / 'Scripts/BootIni/MemoryInit.ini'
    out_mem.parent.mkdir(parents=True, exist_ok=True)
    out_mem.write_bytes(mod_mem_bytes)

    # 4. Generate manifest.tsv in the 4-column format required by runtime/romfs.c:
    # <path>\t<size>\t<sha256>\t<orig_sha256>
    manifest_lines = [
        '# path\tsize\tsha256\toriginal_sha256 (generated by scripts/make_offline_config.py)',
        f'Data/nxcert.ini\t{len(mod_nxcert_bytes)}\t{mod_nxcert_sha}\t{nxcert_orig_sha}',
        f'Scripts/BootIni/MemoryInit.ini\t{len(mod_mem_bytes)}\t{mod_mem_sha}\t{mem_orig_sha}',
    ]
    manifest_text = '\n'.join(manifest_lines) + '\n'
    out_manifest = output_dir / 'manifest.tsv'
    out_manifest.write_text(manifest_text, encoding='utf-8')

    report = {
        'status': 'pass',
        'output_dir': str(output_dir),
        'manifest': str(out_manifest),
        'files': [
            {
                'path': 'Data/nxcert.ini',
                'size': len(mod_nxcert_bytes),
                'sha256': mod_nxcert_sha,
                'original_sha256': nxcert_orig_sha,
                'changes': nxcert_changes
            },
            {
                'path': 'Scripts/BootIni/MemoryInit.ini',
                'size': len(mod_mem_bytes),
                'sha256': mod_mem_sha,
                'original_sha256': mem_orig_sha,
                'changes': mem_changes
            }
        ]
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path(game_config.CONFIG['work']),
                        help='work directory (default: %(default)s)')
    parser.add_argument('--romfs', type=Path, default=None,
                        help='path to RomFS directory holding loose files or romfs.bin (default: <work>/extracted/<version>/romfs)')
    parser.add_argument('--output', type=Path, default=None,
                        help='output directory for RomFS overlay and manifest (default: <work>/extracted/<version>/romfs-patches)')
    parser.add_argument('--nxcert', type=Path, default=None,
                        help='optional direct path to source nxcert.ini')
    parser.add_argument('--memory-init', type=Path, default=None,
                        help='optional direct path to source MemoryInit.ini')
    parser.add_argument('--json', action='store_true',
                        help='output structured report in JSON format')

    args = parser.parse_args()

    romfs_dir = args.romfs or (args.work / f'extracted/{VERSION}/romfs')
    output_dir = args.output or (args.work / f'extracted/{VERSION}/romfs-patches')

    # If default romfs_dir doesn't exist, check common fallback locations (e.g. /home/bruno/fc26/romfs)
    if not romfs_dir.exists() and not (args.nxcert and args.memory_init):
        fallback = Path('/home/bruno/fc26/romfs')
        if fallback.exists():
            romfs_dir = fallback

    try:
        report = generate_offline_package(
            romfs_dir=romfs_dir,
            output_dir=output_dir,
            nxcert_override=args.nxcert,
            memory_init_override=args.memory_init
        )
    except Exception as e:
        sys.exit(f'error: {e}')

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Generated offline config package in {report['output_dir']}:")
        for f in report['files']:
            print(f"  {f['path']} ({f['size']} bytes, sha256: {f['sha256'][:16]}..., orig: {f['original_sha256'][:16]}...)")
            for c in f['changes']:
                if 'arena' in c:
                    print(f"    - line {c['line']}: {c['arena']} {c['original_size']} -> {c['new_size']}")
                elif 'key' in c:
                    print(f"    - [{c['action']}] {c['key']} = {c['new_value']} ({c['description']})")
        print(f"Manifest written to {report['manifest']}")


if __name__ == '__main__':
    main()
