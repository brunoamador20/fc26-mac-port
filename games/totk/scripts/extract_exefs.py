#!/usr/bin/env python3
"""Read an XCI in place; extract and verify only its base Program ExeFS.

Supports NCA3, rights-free key-area AES-CTR, and hierarchical SHA-256 PFS0.
Keys stay in memory. No RomFS extraction, executable launch, or network calls.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decrypt(key, mode, data):
    ctx = Cipher(algorithms.AES(key), mode).decryptor()
    return ctx.update(data) + ctx.finalize()


def read_at(f, offset, length):
    require(0 <= offset and 0 <= length <= 512 * 1024 * 1024, 'Invalid/big read')
    f.seek(offset)
    data = f.read(length)
    require(len(data) == length, 'Truncated input')
    return data


def hfs(f, offset, bound):
    hdr = read_at(f, offset, 16)
    require(hdr[:4] == b'HFS0', 'Expected HFS0')
    count, strings_size = struct.unpack_from('<II', hdr, 4)
    require(count <= 4096 and strings_size <= 1024 * 1024, 'Invalid HFS0 table')
    size = 16 + count * 64 + strings_size
    raw = read_at(f, offset, size)
    strings = raw[16 + count * 64:]
    entries = []
    for i in range(count):
        off, length, nameoff = struct.unpack_from('<QQI', raw, 16 + i * 64)
        require(nameoff < len(strings), 'Invalid HFS0 name')
        name = strings[nameoff:].split(b'\0', 1)[0].decode('utf-8')
        require(size + off + length <= bound, 'HFS0 entry out of bounds')
        entries.append((name, offset + size + off, length))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xci', type=Path)
    parser.add_argument('--keys', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), 'Output already exists; choose a new directory')
    keys = {}
    for line in args.keys.read_text().splitlines():
        if '=' in line:
            name, value = line.split('=', 1)
            keys[name.strip().lower()] = bytes.fromhex(value.strip())
    records = []
    with args.xci.open('rb') as f:
        require(read_at(f, 0x100, 4) == b'HEAD', 'Expected XCI HEAD')
        root = struct.unpack('<Q', read_at(f, 0x130, 8))[0]
        partitions = hfs(f, root, args.xci.stat().st_size - root)
        secure = next(e for e in partitions if e[0] == 'secure')
        ncas = hfs(f, secure[1], secure[2])
        programs = []
        for name, offset, length in ncas:
            raw = read_at(f, offset, 0xC00)
            hdr = b''.join(decrypt(keys['header_key'], modes.XTS(i.to_bytes(16, 'big')),
                                   raw[i * 512:(i + 1) * 512]) for i in range(6))
            require(hdr[0x200:0x204] == b'NCA3', 'Only NCA3 is supported')
            content = hdr[0x205]
            record = {'name': name, 'xci_offset': offset, 'size': length,
                      'content_type': content, 'title_id': f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016X}'}
            records.append(record)
            if content == 0:
                programs.append((record, hdr))
        require(len(programs) == 1, 'Expected one base Program NCA')
        record, hdr = programs[0]
        require(hdr[0x230:0x240] == bytes(16), 'Rights-managed content is unsupported')
        generation = max(hdr[0x206], hdr[0x220])
        generation = max(generation - 1, 0)
        area = ['application', 'ocean', 'system'][hdr[0x207]]
        keyname = f'key_area_key_{area}_{generation:02x}'
        require(keyname in keys, f'Missing key-area key for generation {generation}')
        area_keys = decrypt(keys[keyname], modes.ECB(), hdr[0x300:0x340])
        for i in range(4):
            start, end = struct.unpack_from('<II', hdr, 0x240 + 16 * i)
            if not start:
                continue
            fs = hdr[0x400 + 512 * i:0x600 + 512 * i]
            require(hashlib.sha256(fs).digest() == hdr[0x280 + 32 * i:0x2A0 + 32 * i], 'FS header hash mismatch')
            if fs[2:4] != b'\x01\x02':
                continue
            require(fs[4] == 3, 'Only AES-CTR ExeFS is supported')
            blocksize, levels = struct.unpack_from('<II', fs, 0x28)
            hashoff, hashsize, pfsoff, pfssize = struct.unpack_from('<QQQQ', fs, 0x30)
            secstart, secsize = start * 512, (end - start) * 512
            require(levels == 2 and blocksize > 0 and pfssize <= 512 * 1024 * 1024, 'Unsupported ExeFS hash layout')

            def section_read(relative, size):
                require(relative >= 0 and relative + size <= secsize, 'Section read out of bounds')
                absolute = secstart + relative
                aligned = absolute & ~15
                iv = fs[0x140:0x148][::-1] + (aligned // 16).to_bytes(8, 'big')
                data = read_at(f, record['xci_offset'] + aligned, size + absolute - aligned)
                return decrypt(area_keys[32:48], modes.CTR(iv), data)[absolute - aligned:]

            hashes = section_read(hashoff, hashsize)
            require(hashlib.sha256(hashes).digest() == fs[8:40], 'ExeFS hash-table mismatch')
            pfs = section_read(pfsoff, pfssize)
            for index, pos in enumerate(range(0, pfssize, blocksize)):
                expected = hashes[index * 32:(index + 1) * 32]
                require(hashlib.sha256(pfs[pos:pos + blocksize]).digest() == expected,
                        f'ExeFS block hash mismatch: {index}')
            require(pfs[:4] == b'PFS0', 'Expected ExeFS PFS0')
            count, stringsize = struct.unpack_from('<II', pfs, 4)
            require(count <= 128, 'Too many ExeFS files')
            dataoff = 16 + count * 24 + stringsize
            strings = pfs[16 + count * 24:dataoff]
            files = []
            for j in range(count):
                off, size, nameoff = struct.unpack_from('<QQI', pfs, 16 + j * 24)
                require(nameoff < len(strings), 'Bad ExeFS filename offset')
                name = strings[nameoff:].split(b'\0', 1)[0].decode('utf-8')
                require(name not in ('', '.', '..') and '/' not in name and '\\' not in name, 'Unsafe ExeFS filename')
                require(dataoff + off + size <= len(pfs), 'ExeFS file out of bounds')
                data = pfs[dataoff + off:dataoff + off + size]
                files.append((name, data))
            require(any(name == 'main.npdm' for name, _ in files), 'PFS0 is not ExeFS')
            args.output.mkdir(parents=True)
            extracted = []
            for name, data in files:
                (args.output / name).write_bytes(data)
                extracted.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            manifest = {'source': str(args.xci.resolve()), 'source_size': args.xci.stat().st_size,
                        'nca_inventory': records, 'program': record, 'section_index': i,
                        'integrity': 'FS header, ExeFS hash table, and every ExeFS data block verified; RSA signatures not checked',
                        'files': extracted}
            (args.output.parent / 'extraction-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(json.dumps({'integrity': manifest['integrity'], 'files': extracted}, indent=2))
            return
        raise ValueError('No ExeFS section found')


if __name__ == '__main__':
    main()
