#!/usr/bin/env python3
"""Write the manifest.tsv of a player's RomFS mod (runtime/romfs.c loads it from TOTK_ROMFS_MODS, which the launcher sets to
~/Library/Application Support/MacNativeGames/TOTK/mods/<version>).

The mod folder holds the replacement files under their RomFS paths (for example Sound/Resource/Stream/Dm_OP_0001.bwav).
A path the app replaces itself (its romfs-patches and the 2K romfs-patches-out overlays) is left out with a line
saying so: both overlays cannot be loaded, and for the heap table the line says whether the app's 2K overlay already
carries the mod's heap sizes (build_app.py chains them with --mod). --exclude leaves out further paths; Windows and macOS
droppings (desktop.ini, Thumbs.db, .DS_Store) are skipped.
Each line of the manifest names a path, the replacement's size and SHA-256 and the original's SHA-256; the game checks
all of them at start, so a mod made for another game version stops the start instead of loading. A file the RomFS lacks
is added (its original's SHA-256 is "-"), unless a RomFS path differs from it only in case: that is a misspelt
replacement (paths are case-sensitive), so nothing is written. The originals come
from the RomFS the app was built with: the app's Contents/Resources/totk/extracted/<version>/romfs (romfs.bin and
runtime-index.bin), or a build work folder's extracted/<version>/romfs.

usage: make_mod_manifest.py <mod folder> (--app <Tears of the Kingdom.app> | --romfs <folder>) [--version v143]
                              [--exclude <RomFS path or glob>]...
"""
import argparse
import fnmatch
import hashlib
from pathlib import Path
import struct
import sys

VERSIONS = ('v0', 'v112', 'v121', 'v143')
CHUNK = 8 << 20
# Windows/macOS droppings that mod managers (TKMM, Ryujinx output folders) leave in a RomFS tree: never a game file.
JUNK = {'desktop.ini', 'thumbs.db', '.ds_store'}


def read_index(path):
    """RomFS path -> (offset, size) from runtime-index.bin (scripts/prepare_romfs_backend.py writes it)."""
    data = path.read_bytes()
    magic, count, strings = struct.unpack_from('<8sQQ', data, 0)
    if magic != b'TOTKRFS1' or strings != 24 + count*24 or strings > len(data):
        raise ValueError(f'{path}: not a RomFS index')
    files = {}
    for i in range(count):
        offset, size, name, length = struct.unpack_from('<QQII', data, 24 + i*24)
        files[data[strings+name:strings+name+length-1].decode()] = (offset, size)
    return files


def sha256_range(handle, offset, size):
    digest = hashlib.sha256()
    handle.seek(offset)
    while size:
        block = handle.read(min(CHUNK, size))
        if not block:
            raise ValueError('RomFS image ends early')
        digest.update(block)
        size -= len(block)
    return digest.hexdigest()


HEAPDEF = 'System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs'


def app_overlays(app, version):
    """RomFS path -> the app's own replacement of it (extracted/<version>/romfs-patches*, the 2K HeapDef included). The
    game stops at the first start when a mod replaces one of them too (runtime/romfs.c), so the manifest leaves every one
    of them to the app."""
    root = app/'Contents/Resources/totk/extracted'/version
    replaced = {}
    manifests = [root/'romfs-patches/manifest.tsv', *sorted((root/'romfs-patches-out').glob('*/manifest.tsv'))]
    for path in manifests:
        if path.is_file():
            for line in path.read_text().splitlines():
                name = line.split('\t', 1)[0]
                if name and not name.startswith('#'):
                    replaced.setdefault(name, path.parent/name)
    return replaced


TWO_K = ('DynamicTextureAllocatorMem', 'Graphics')     # the two heaps scripts/make_output_res_overlay.py grows


def heap_sizes(byml):
    """System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml (BYML v7, "YB") -> {heap name: Size in KiB}."""
    assert byml[:2] == b'YB' and struct.unpack_from('<H', byml, 2)[0] == 7
    keys_at, _, root = struct.unpack_from('<III', byml, 4)
    count = struct.unpack_from('<I', byml, keys_at)[0] >> 8
    offsets = struct.unpack_from(f'<{count + 1}I', byml, keys_at + 4)
    keys = [byml[keys_at + o: byml.index(0, keys_at + o)].decode() for o in offsets[:count]]
    def entry(node, name):
        """The value field of hash node `node`'s entry `name`."""
        assert byml[node] == 0xc1, 'not a hash node'
        for i in range(struct.unpack_from('<I', byml, node)[0] >> 8):
            at = node + 4 + 8*i
            if keys[struct.unpack_from('<I', byml, at)[0] & 0xffffff] == name:
                return at + 4, byml[at + 3]
        raise KeyError(name)
    heaps = struct.unpack_from('<I', byml, entry(root, 'Heaps')[0])[0]
    sizes = {}
    for i in range(struct.unpack_from('<I', byml, heaps)[0] >> 8):
        at = heaps + 4 + 8*i
        name = keys[struct.unpack_from('<I', byml, at)[0] & 0xffffff]
        node = struct.unpack_from('<I', byml, at + 4)[0]
        try:
            field, kind = entry(node, 'Size')
            if kind == 0xd1:
                sizes[name] = struct.unpack_from('<i', byml, field)[0]
        except (KeyError, AssertionError):
            pass
    return sizes


def heapdef_carried(mod_file, app_file):
    """True when the app's 2K overlay keeps this mod's heap sizes (the build chains the table with --mod: every heap
    equal, and the two 2K heaps grown by the same amount), False when it does not, None when that cannot be told here
    (no zstd module, or unreadable files)."""
    try:
        from compression import zstd
    except ImportError:
        return None
    try:
        mod, app = heap_sizes(zstd.decompress(mod_file.read_bytes())), heap_sizes(zstd.decompress(app_file.read_bytes()))
    except (zstd.ZstdError, OSError, ValueError, AssertionError, struct.error):
        return None
    if set(mod) != set(app):
        return False
    extra = {name: app[name] - mod[name] for name in mod if app[name] != mod[name]}
    if any(name not in TWO_K for name in extra):
        return False
    return not extra or (len(extra) == len(TWO_K) and len(set(extra.values())) == 1 and next(iter(extra.values())) > 0)


def manifest(mod, romfs, excludes=(), app_replaced=None):
    """The manifest lines for every file in the mod folder; files equal to their original are left out, anything matching
    an --exclude pattern is left out, and so is a path the app replaces itself (app_replaced: path -> the app's file).
    Returns (lines, same, added, misspelt, excluded, taken): misspelt pairs a mod path with the RomFS path that differs
    only in case; taken maps a left-out path to the app's own replacement of it."""
    index = read_index(romfs/'runtime-index.bin')
    folded = {name.lower(): name for name in index}
    app_replaced = app_replaced or {}
    lines, same, added, misspelt, excluded, taken = [], [], [], [], [], {}
    with (romfs/'romfs.bin').open('rb') as image:
        for file in sorted(p for p in mod.rglob('*') if p.is_file()):
            name = file.relative_to(mod).as_posix()
            if name == 'manifest.tsv' or any(part.startswith('.') for part in file.relative_to(mod).parts):
                continue
            if file.name.lower() in JUNK:
                continue
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in excludes):
                excluded.append(name)
                continue
            if name in app_replaced:                 # the app's own overlay replaces it: both cannot be loaded
                taken[name] = file
                continue
            if name not in index:
                if name.lower() in folded:
                    misspelt.append((name, folded[name.lower()]))
                    continue
                with file.open('rb') as handle:
                    lines.append(f'{name}\t{file.stat().st_size}\t{sha256_range(handle, 0, file.stat().st_size)}\t-')
                added.append(name)
                continue
            offset, size = index[name]
            with file.open('rb') as handle:
                replacement = sha256_range(handle, 0, file.stat().st_size)
            original = sha256_range(image, offset, size)
            if replacement == original:
                same.append(name)
                continue
            lines.append(f'{name}\t{file.stat().st_size}\t{replacement}\t{original}')
    return lines, same, added, misspelt, excluded, taken


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('mod', type=Path, help='the mod folder, files under their RomFS paths')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--app', type=Path, help='the built Tears of the Kingdom.app')
    source.add_argument('--romfs', type=Path, help='a folder holding romfs.bin and runtime-index.bin')
    parser.add_argument('--version', choices=VERSIONS, help='the game version (default: the mod folder name)')
    parser.add_argument('--exclude', action='append', default=[], metavar='PATH',
                        help='a RomFS path or glob to leave out of the manifest as well (files the app replaces itself '
                             'are left out without it)')
    args = parser.parse_args()
    version = args.version or (args.mod.resolve().name if args.mod.resolve().name in VERSIONS else None)
    romfs = args.romfs
    if args.app:
        if not version:
            parser.error('name the game version with --version (or name the mod folder v0, v112, v121 or v143)')
        romfs = args.app/f'Contents/Resources/totk/extracted/{version}/romfs'
    for need in ('romfs.bin', 'runtime-index.bin'):
        if not (romfs/need).is_file():
            parser.error(f'{romfs/need} not found')
    if not args.mod.is_dir():
        parser.error(f'{args.mod} is not a folder')
    replaced = app_overlays(args.app, version) if args.app else {}
    lines, same, added, misspelt, excluded, taken = manifest(args.mod, romfs, args.exclude, replaced)
    for name in same:
        print(f'left out (same as the original): {name}')
    for name in excluded:
        print(f'left out (--exclude): {name}')
    for name, file in sorted(taken.items()):
        where = replaced[name].relative_to(args.app).as_posix()
        if name == HEAPDEF:
            carried = heapdef_carried(file, replaced[name])
            if carried:
                print(f'left out (the app replaces it, and the 2K overlay already carries these heap sizes): {name}')
            elif carried is False:
                print(f'left out (the app replaces it, but with other heap sizes: rebuild the app with --mod pointing '
                      f'at this mod to keep them): {name}')
            else:
                print(f'left out (the app replaces it; build with --mod pointing at this mod to keep its heap sizes): {name}')
        else:
            print(f'left out (the app replaces it too, so this file would not be used: {where}): {name}')
    if misspelt:
        for name, real in misspelt:
            print(f'not a file of this RomFS: {name} (it has {real}; paths are case-sensitive)', file=sys.stderr)
        sys.exit('nothing written: rename the files above')
    if added:
        print(f'{len(added)} files the RomFS lacks are added, for example {added[0]}')
    if not lines:
        sys.exit('nothing written: the folder replaces or adds no file')
    (args.mod/'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256 (generated by scripts/make_mod_manifest.py)\n'
                                         + '\n'.join(lines) + '\n')
    print(f'{args.mod/"manifest.tsv"}: {len(lines)} files ({len(lines) - len(added)} replaced, {len(added)} added)')


if __name__ == '__main__':
    main()
