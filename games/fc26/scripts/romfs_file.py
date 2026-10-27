#!/usr/bin/env python3
"""Copy one file out of an extracted RomFS image: romfs_file.py <romfs dir> <path in the RomFS> <output>.

<romfs dir> holds romfs.bin and its index.json (scripts/extract_romfs.py or scripts/merge_update_romfs.py).
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    folder, name, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    files = {f['path']: f for f in json.loads((folder / 'index.json').read_text())['files']}
    if name not in files:
        sys.exit(f'romfs_file: {name} is not in {folder}/index.json')
    entry = files[name]
    with (folder / 'romfs.bin').open('rb') as f:
        f.seek(entry['offset'])
        data = f.read(entry['size'])
    if len(data) != entry['size']:
        sys.exit(f'romfs_file: {folder}/romfs.bin is shorter than index.json says')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f'{name} -> {output} ({len(data)} bytes)')


if __name__ == '__main__':
    main()
