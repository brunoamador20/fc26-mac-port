#!/usr/bin/env python3
"""Breath of the Wild: a startup shader seed from a translation cache that was played with (botw.md).

The shader discovery of games/totk/scripts/prepare_shader_seed.py reads Tears of the Kingdom's shader archives; until it
knows Breath of the Wild's, the seed packaged into the app is what a played session translated: every variant a cache's
<key>.variants files name, with its MSL and reflection, in the seed format the runtime imports on the first start
(seed-manifest.json, pso_manifest.tsv). Game-derived data: it belongs in the work folder, never in the repo.
usage: prepare_shader_seed_from_cache.py --cache <translation cache> --output <seed folder> --romfs <RomFS folder>
       --translator <totk_xlate> --spirv-cross <spirv-cross> [--version botw160]
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

CHAIN = 'totk-native-v4-unverified'
STAGE = {'vs': 0, 'ps': 1, 'cs': 5}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('cache', 'output', 'romfs', 'translator', 'spirv-cross'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--version', default='botw160')
    a = p.parse_args()
    cache = a.cache
    identity = dict(schema=1, chain=CHAIN, version=a.version,
                    source_romfs_sha256=json.loads((a.romfs / 'index.json').read_text())['romfs_sha256'],
                    translator_sha256=digest(a.translator.read_bytes()), spirv_cross_sha256=digest(getattr(a, 'spirv_cross').read_bytes()),
                    preparation_sha256=digest(Path(__file__).read_bytes()), shader_list_sha256=None)
    staging = a.output.with_name(a.output.name + '.partial')
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    rows, completed, skipped = [], [], 0
    for variants in sorted(cache.glob('*.variants')):
        key = variants.name[:-len('.variants')]
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            continue
        try:
            entries = json.loads(variants.read_text())
        except ValueError:
            skipped += 1
            continue
        kept = []
        for entry in entries:
            variant = entry.get('variant', '')
            metal, refl = cache / f'{variant}_b.metal', cache / f'{variant}_b.json'
            if not (variant.startswith(key + '-') and len(variant) == 77 and metal.is_file() and refl.is_file()):
                skipped += 1
                continue
            info = json.loads(refl.read_text())
            if info.get('chain') != CHAIN or info.get('stage') not in STAGE:
                skipped += 1
                continue
            shutil.copyfile(metal, staging / metal.name)
            shutil.copyfile(refl, staging / refl.name)
            rows.append(f'S\t{variant}_b\t{STAGE[info["stage"]]}')
            if info['stage'] == 'cs':
                rows.append(f'C\t{variant}_b')
            kept.append(entry)
            completed.append(variant)
        if kept:
            (staging / variants.name).write_text(json.dumps(kept, separators=(',', ':')) + '\n')
    if not completed:
        raise SystemExit(f'no complete shader variants in {cache}')
    (staging / 'pso_manifest.tsv').write_text(f"# Prepared from a played translation cache of this game; {CHAIN}\n" + '\n'.join(rows) + '\n')
    report = dict(**identity, shaders=len(completed), discovered=len(completed), located=0, startup_shaders=0, listed_variants=0,
                  skipped=skipped, archives=[], seconds=0.0, source='translation cache',
                  files={f.name: digest(f.read_bytes()) for f in sorted(staging.iterdir())})
    (staging / 'seed-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    if a.output.exists():
        shutil.rmtree(a.output)
    staging.rename(a.output)
    print(f'startup seed ready: {len(completed)} shader variants from the cache, {skipped} skipped')


if __name__ == '__main__':
    main()
