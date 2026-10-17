#!/usr/bin/env python3
"""Merge a base XCI/NSP and an update NSP with the pinned hactool BKTR reader.

Temporary common-ticket keys are private files, never arguments or log output.
The caller additionally verifies the resulting image against its known version hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from extract_exefs import (load_keys, container_entries, common_tickets, nca_inventory,
                           program_nca, record_offset, require)
from extract_romfs import index_romfs


def copy_range(source, offset, size, target):
    with source.open('rb') as src, target.open('wb') as dst:
        src.seek(offset)
        while size:
            data = src.read(min(size, 8 << 20))
            require(bool(data), 'Truncated NCA')
            dst.write(data)
            size -= len(data)


def merge(base, update, keys_path, hactool, output):
    require(not output.exists(), 'Output exists')
    keys = load_keys(keys_path)
    inputs = []
    tickets = {}
    for source, is_update in ((base, False), (update, True)):
        with source.open('rb') as f:
            kind, entries = container_entries(f, source.stat().st_size)
            require(not is_update or kind == 'nsp', 'Update must be an NSP')
            found = common_tickets(f, entries)
            for rights, key in found.items():
                require(rights not in tickets or tickets[rights] == key, 'Conflicting common tickets')
                tickets[rights] = key
            record, header = program_nca(nca_inventory(f, entries, keys), update=is_update)
            rights = header[0x230:0x240]
            require(rights == bytes(16) or rights in tickets, 'Missing common ticket')
            inputs.append((source, record, header))
    sections = [i for i in range(4) if inputs[1][2][0x400+i*512+4] == 4]
    require(len(sections) == 1, 'Expected one BKTR section')
    output.parent.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(output.parent).free > sum(r['size'] for _, r, _ in inputs) + 18*(1 << 30),
            'Need about 35 GiB free for temporary NCAs and merged image')
    with tempfile.TemporaryDirectory(prefix='update-merge-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        keyfile = tmp/'title.keys'
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            for rights, key in tickets.items():
                f.write(f'{rights.hex()} = {key.hex()}\n')
        for (source, record, _), name in zip(inputs, ('base.nca', 'update.nca')):
            copy_range(source, record_offset(record), record['size'], tmp/name)
        result = tmp/'result'
        result.mkdir()
        command = [str(hactool.resolve()), '-x', '-y', '--disablekeywarns', '--suppresskeys',
                   '-k', str(keys_path.resolve()), '--basenca='+str(tmp/'base.nca'),
                   f'--section{sections[0]}='+str(result/'romfs.bin'), str(tmp/'update.nca')]
        with (result/'merge.log').open('w') as log:
            code = subprocess.run(command, env=dict(os.environ, MNG_TITLE_KEYS=str(keyfile)),
                                  stdout=log, stderr=subprocess.STDOUT).returncode
        log = (result/'merge.log').read_text()
        require(code == 0 and not re.search(r'\(FAIL\)|\(INVALID\)|Failed to|Error:', log), 'BKTR verification failed')
        require(all(re.search(rf'Level {i} \(GOOD\)', log) for i in range(6)), 'Missing verified IVFC levels')
        image = result/'romfs.bin'
        with image.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        files = index_romfs(image)
        report = dict(status='pass', romfs_size=image.stat().st_size, romfs_sha256=digest,
                      files=files, integrity='BKTR merge; all six IVFC levels verified')
        (result/'index.json').write_text(json.dumps(report, indent=2)+'\n')
        result.rename(output)
    print(json.dumps(dict(status='pass', files=len(files), sha256=digest)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('update', type=Path)
    parser.add_argument('--keys', required=True, type=Path)
    parser.add_argument('--hactool', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    merge(args.base, args.update, args.keys, args.hactool, args.output)
