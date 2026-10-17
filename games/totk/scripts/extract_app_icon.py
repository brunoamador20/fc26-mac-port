#!/usr/bin/env python3
"""The app icon from the game's own control data: the control NCA in the card image's secure partition carries
icon_<language>.dat (a 256x256 JPEG); it becomes build/AppIcon.icns (sips and iconutil, both part of macOS).
usage: extract_app_icon.py <card image .xci> --keys <prod.keys> [--title 0100f2c0115b6000] [--output build/AppIcon.icns]"""
import argparse
import struct
import subprocess
import tempfile
from pathlib import Path
from extract_exefs import read_at, require
from extract_romfs import index_romfs
from extract_shared_fonts import Slice, hfs0_entries, load_keys, nca_header, nca_romfs

LANGUAGES = ['AmericanEnglish', 'BritishEnglish', 'Japanese', 'French', 'German', 'LatinAmericanSpanish', 'Spanish',
             'Italian', 'Dutch', 'CanadianFrench', 'Portuguese', 'Russian', 'Korean', 'TraditionalChinese', 'SimplifiedChinese']


def control_nca(xci, keys, title):
    with xci.open('rb') as f:
        require(read_at(f, 0x100, 4) == b'HEAD', 'Not a game card image (XCI)')
        root = struct.unpack('<Q', read_at(f, 0x130, 8))[0]
        secure = [e for e in hfs0_entries(f, root) if e[0] == 'secure']
        require(secure, 'The game card image has no secure partition')
        for name, offset, size in hfs0_entries(f, secure[0][1]):
            if not name.endswith('.nca') or name.endswith('.cnmt.nca'):
                continue
            with Slice(xci, offset) as nca:
                hdr = nca_header(nca, keys)
            if hdr[0x200:0x204] == b'NCA3' and hdr[0x205] == 2 and f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016x}' == title:
                return offset
    raise ValueError('no control data for this title in the card image')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('xci', type=Path)
    ap.add_argument('--keys', type=Path, required=True)
    ap.add_argument('--title', default='0100f2c0115b6000')
    ap.add_argument('--output', type=Path, default=Path('build/AppIcon.icns'))
    a = ap.parse_args()
    keys = load_keys(a.keys)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        image = t / 'control.romfs'
        nca_romfs(Slice(a.xci, control_nca(a.xci, keys, a.title.lower())), keys, image)
        entries = {e['path']: e for e in index_romfs(image)}
        icon = next((entries[f'icon_{lang}.dat'] for lang in LANGUAGES if f'icon_{lang}.dat' in entries), None)
        require(icon is not None, 'no icon in the control data')
        with image.open('rb') as f:
            (t / 'icon.jpg').write_bytes(read_at(f, icon['offset'], icon['size']))
        iconset = t / 'AppIcon.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png'
                subprocess.run(['sips', '-s', 'format', 'png', '-z', str(px), str(px), t / 'icon.jpg', '--out', iconset / name],
                               check=True, capture_output=True)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', a.output], check=True)
    print(f'{a.output}')


if __name__ == '__main__':
    main()
