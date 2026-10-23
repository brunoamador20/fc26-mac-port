#!/usr/bin/env python3
"""Turn the player's exefs patches (IPSwitch .pchtxt, from mods/<display_version>/<name>/exefs/) into checked patch tables.

The mechanism only: FC 26 has no patch of its own yet, so the folder is empty and the runtime applies none
(runtime/game_patches.c, FC26_PATCHES unset). Each patch must name main's build ID (pinned in
assets/expected-v<version>.json) and touch only bytes the Apple-silicon rewrite left as they were (a rewritten word
would be a branch into a rewrite block). Offsets are main image offsets (a file's `@flag offset_shift 0x100` is for the
IPS container). Writes <work>/patches/<slug>.tsv ("offset new-bytes original-bytes" in hex) and <work>/patches/index.tsv;
the runtime checks the original bytes again before writing. No game bytes come from the files beyond the replacement
words they already hold.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'third_party/d2r'))   # FC 26's own copy of the rewriter
sys.path.insert(0, str(HERE / 'scripts'))           # also under python -I
import nsoimg
import game_config

VERSION = game_config.VERSION
DISPLAY = game_config.CONFIG['display_version']
EXPECTED = json.loads(game_config.EXPECTED_PATH.read_text())


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def same_build_id(a, b):
    """IPSwitch files give the NSO build ID as its first 20 bytes or as all 32 (zero-padded); compare both alike."""
    return a.strip().upper().rstrip('0') == b.strip().upper().rstrip('0')


def parse(path, build_id):
    text = path.read_text(errors='replace').splitlines()
    ids = [l.split('-', 1)[1].strip().upper() for l in text if l.startswith('@nsobid-')]
    if len(ids) != 1 or not same_build_id(ids[0], build_id):
        raise ValueError(f'{path}: build ID {ids} is not main {DISPLAY} ({build_id})')
    patches, enabled = [], False
    for n, line in enumerate(text, 1):
        line = line.split('//', 1)[0].strip()
        if line.startswith('@enabled'): enabled = True; continue
        if line.startswith('@disabled') or line.startswith('@stop'): enabled = False; continue
        m = re.fullmatch(r'([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]+)', line)
        if not m: continue
        if not enabled: continue
        if len(m.group(2)) % 2: raise ValueError(f'{path}:{n}: odd number of hex digits')
        patches.append((int(m.group(1), 16), bytes.fromhex(m.group(2)), n))
    if not patches: raise ValueError(f'{path}: no enabled patch lines')
    return patches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mods', type=Path, nargs='?', default=HERE / f'mods/{DISPLAY}', help='folder of <name>/exefs/*.pchtxt')
    parser.add_argument('--work', type=Path, default=HERE / game_config.CONFIG['work'])
    args = parser.parse_args()
    work = args.work.resolve()
    if not EXPECTED.get('main_build_id'):
        sys.exit(f'main\'s build ID is not pinned yet in {game_config.EXPECTED_PATH.name} (scripts/prepare_runtime.py --record)')
    original = nsoimg.load(work / f'extracted/{VERSION}/exefs/main')
    rewritten = (work / f'rewritten/{VERSION}/main.patched.bin').read_bytes()
    out = work / 'patches'; out.mkdir(exist_ok=True)
    index = []
    for f in sorted(args.mods.glob('*/exefs/*.pchtxt')):
        name = f.parents[1].name
        patches = parse(f, EXPECTED['main_build_id'])
        rows = []
        for off, new, line in patches:
            end = off + len(new)
            if end > len(original) or end > len(rewritten):
                raise ValueError(f'{f}:{line}: {off:#x}+{len(new)} beyond main')
            if rewritten[off:end] != original[off:end]:
                raise ValueError(f'{f}:{line}: {off:#x} lies on bytes the Apple-silicon rewrite changed; refusing')
            rows.append(f'{off:#x}\t{new.hex()}\t{original[off:end].hex()}')
        (out / f'{slug(name)}.tsv').write_text('# ' + name + ' (' + f.name + ')\n' + '\n'.join(rows) + '\n')
        index.append(f'{slug(name)}\t{name}\t{len(rows)}')
        print(f'{slug(name):24} {len(rows):3} patches  ({name})')
    (out / 'index.tsv').write_text('\n'.join(index) + '\n')


if __name__ == '__main__':
    main()
