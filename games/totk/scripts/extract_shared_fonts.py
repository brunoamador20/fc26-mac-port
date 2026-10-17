#!/usr/bin/env python3
"""Extract the system shared fonts (BFTTF) from firmware data NCAs, verifying the NCA FS header,
all six IVFC levels and each BFTTF header. Fonts stay in the BFTTF form that hardware places in
shared memory; only local copies are written, never printed.

Sources: --xci <game card image> reads the data NCAs from the card's system update partition (a game card carries the
system update it needs, shared fonts included); otherwise --inventory lists the NCAs of an installed firmware."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import modes
from extract_exefs import decrypt, read_at, require
from extract_romfs import index_romfs

FIRMWARE = Path.home() / 'Library/Application Support/Ryujinx/bis/system/Contents/registered'
# nn::pl::SharedFontType -> (system data title, BFTTF file name)
FONTS = [
    (0, 'standard', '0100000000000811', 'nintendo_udsg-r_std_003.bfttf'),
    (1, 'chinese-simplified', '0100000000000814', 'nintendo_udsg-r_org_zh-cn_003.bfttf'),
    (2, 'chinese-simplified-extension', '0100000000000814', 'nintendo_udsg-r_ext_zh-cn_003.bfttf'),
    (3, 'chinese-traditional', '0100000000000813', 'nintendo_udjxh-db_zh-tw_003.bfttf'),
    (4, 'korean', '0100000000000812', 'nintendo_udsg-r_ko_003.bfttf'),
    (5, 'nintendo-extension', '0100000000000810', 'nintendo_ext_003.bfttf'),
]
BFTTF_DECODED_MAGIC = 0x7f9a0218


def load_keys(path):
    keys = {}
    for line in path.read_text().splitlines():
        if '=' in line:
            name, value = line.split('=', 1)
            keys[name.strip().lower()] = bytes.fromhex(value.strip())
    return keys


class Slice:
    """A file seen from a base offset: an NCA inside a game card image reads like a standalone NCA file."""
    def __init__(self, path, base=0):
        self.f, self.base = path.open('rb'), base

    def seek(self, offset, whence=0):
        return self.f.seek(self.base + offset if whence == 0 else offset, whence) - self.base

    def read(self, size=-1):
        return self.f.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.f.close()


def hfs0_entries(f, offset):
    """(name, absolute offset, size) of each file in the HFS0 partition at offset."""
    head = read_at(f, offset, 16)
    require(head[:4] == b'HFS0', 'Unsupported game card partition')
    count, strings = struct.unpack_from('<II', head, 4)
    table = read_at(f, offset + 16, count * 0x40 + strings)
    data = offset + 16 + count * 0x40 + strings
    names = table[count * 0x40:]
    out = []
    for i in range(count):
        rel, size, name_off = struct.unpack_from('<QQI', table, i * 0x40)
        out.append((names[name_off:names.index(b'\0', name_off)].decode(), data + rel, size))
    return out


def nca_header(f, keys):
    raw = read_at(f, 0, 0xc00)
    return b''.join(decrypt(keys['header_key'], modes.XTS(i.to_bytes(16, 'big')), raw[i * 512:(i + 1) * 512]) for i in range(6))


def xci_data_ncas(xci, keys):
    """title ID -> offset of each data NCA in the card's system update partition."""
    found = {}
    with xci.open('rb') as f:
        require(read_at(f, 0x100, 4) == b'HEAD', 'Not a game card image (XCI)')
        root = struct.unpack('<Q', read_at(f, 0x130, 8))[0]
        update = [e for e in hfs0_entries(f, root) if e[0] == 'update']
        require(update, 'The game card image has no system update partition')
        for name, offset, size in hfs0_entries(f, update[0][1]):
            if not name.endswith('.nca') or name.endswith('.cnmt.nca'):
                continue
            with Slice(xci, offset) as nca:
                hdr = nca_header(nca, keys)
            if hdr[0x200:0x204] == b'NCA3' and hdr[0x205] == 4:   # content type 4: data
                found[f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016x}'] = offset
    return found


def nca_romfs(source, keys, image_path):
    """Write the verified RomFS image of a data NCA (a Path, or a Slice of a game card image) to image_path."""
    with (source if isinstance(source, Slice) else Slice(source)) as f:
        raw = read_at(f, 0, 0xc00)
        hdr = b''.join(decrypt(keys['header_key'], modes.XTS(i.to_bytes(16, 'big')), raw[i * 512:(i + 1) * 512]) for i in range(6))
        require(hdr[0x200:0x204] == b'NCA3' and hdr[0x230:0x240] == bytes(16), f'Unsupported NCA at {f.base:#x}')
        gen = max(max(hdr[0x206], hdr[0x220]) - 1, 0)
        area = ['application', 'ocean', 'system'][hdr[0x207]]
        area_keys = decrypt(keys[f'key_area_key_{area}_{gen:02x}'], modes.ECB(), hdr[0x300:0x340])
        for i in range(4):
            start, end = struct.unpack_from('<II', hdr, 0x240 + i * 16)
            if not start:
                continue
            fs = hdr[0x400 + 512 * i:0x600 + 512 * i]
            require(hashlib.sha256(fs).digest() == hdr[0x280 + 32 * i:0x2a0 + 32 * i], 'FS header hash')
            if fs[2:5] != bytes([0, 3, 3]):
                continue
            require(fs[8:12] == b'IVFC' and struct.unpack_from('<III', fs, 12) == (0x20000, 32, 7), 'Unsupported IVFC layout')
            levels = [struct.unpack_from('<QQII', fs, 0x18 + j * 24) for j in range(6)]

            def read(relative, size):
                require(0 <= relative <= relative + size <= (end - start) * 512, 'Section bounds')
                absolute = start * 512 + relative
                aligned = absolute & ~15
                skip = absolute - aligned
                iv = fs[0x140:0x148][::-1] + (aligned // 16).to_bytes(8, 'big')
                return decrypt(area_keys[32:48], modes.CTR(iv), read_at(f, aligned, size + skip))[skip:]

            parent = fs[0xc8:0xe8]
            image = bytearray()
            for level, (offset, size, power, reserved) in enumerate(levels):
                require(12 <= power <= 24 and reserved == 0, 'IVFC block size')
                block = 1 << power
                data = read(offset, size)
                for index, j in enumerate(range(0, len(data), block)):
                    payload = data[j:j + block]
                    require(hashlib.sha256(payload + bytes(block - len(payload))).digest() == parent[index * 32:index * 32 + 32], f'IVFC level {level} block {index}')
                parent = data
                if level == 5:
                    image = data
            image_path.write_bytes(image)
            return
    raise ValueError(f'No RomFS in the NCA at {f.base:#x}')


def bfttf_size(data):
    """BFTTF: big-endian words XORed with key = word0 ^ 0x7f9a0218; word1 = font size; payload follows."""
    magic, size = struct.unpack_from('>II', data, 0)
    key = magic ^ BFTTF_DECODED_MAGIC
    decoded = size ^ key
    require(decoded + 8 == len(data), 'BFTTF size does not match file')
    first = struct.unpack_from('>I', data, 8)[0] ^ key
    require(first in (0x00010000, 0x4f54544f), 'BFTTF payload is not a TrueType/OpenType font')
    return decoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keys', type=Path, required=True)
    parser.add_argument('--xci', type=Path, help='game card image: take the fonts from its system update partition')
    parser.add_argument('--inventory', type=Path, default=Path('analysis/firmware-inventory.json'))
    parser.add_argument('--output', type=Path, default=Path('extracted/firmware/shared-fonts'))
    args = parser.parse_args()
    require(not args.output.exists(), 'Output already exists')
    keys = load_keys(args.keys)
    if args.xci:
        card = xci_data_ncas(args.xci, keys)
        missing = sorted({t for _, _, t, _ in FONTS} - card.keys())
        require(not missing, f'Shared font data missing from the card update partition: {", ".join(missing)}')
        source = lambda title: Slice(args.xci, card[title])
    else:
        rows = json.loads(args.inventory.read_text())['rows']
        data_nca = {r['title_id']: r['file'] for r in rows if r['content_type'] == 4}
        source = lambda title: (FIRMWARE / data_nca[title] / '00') if (FIRMWARE / data_nca[title]).is_dir() else FIRMWARE / data_nca[title]
    args.output.mkdir(parents=True)
    images = {}
    report = []
    for kind, name, title, filename in FONTS:
        if title not in images:
            image_path = args.output / f'{title}.romfs'
            nca_romfs(source(title), keys, image_path)
            images[title] = (image_path, {e['path']: e for e in index_romfs(image_path)})
        image_path, entries = images[title]
        require(filename in entries, f'{filename} missing in {title}')
        e = entries[filename]
        with image_path.open('rb') as f:
            data = read_at(f, e['offset'], e['size'])
        size = bfttf_size(data)
        out = args.output / f'{kind}-{name}.bfttf'
        out.write_bytes(data)
        report.append(dict(type=kind, name=name, title_id=title, file=filename, bfttf_bytes=len(data), font_bytes=size,
                           sha256=hashlib.sha256(data).hexdigest()))
    for image_path, _ in images.values():
        image_path.unlink()
    manifest = dict(status='pass', integrity='NCA FS header and six IVFC levels verified per NCA; BFTTF header decodes to an sfnt font; RSA not checked', fonts=report)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(status='pass', fonts=[(r['type'], r['font_bytes']) for r in report])))


if __name__ == '__main__':
    main()
