#!/usr/bin/env python3
"""Are FC 26's shader keys the same from one start to the next? (docs/SHADERS_NUVEM.md, question 1)

The translation cache finds a shader by SHA-256 of the control section NVN receives (its first ctl_key_len bytes) and of
the code (nvn_mtl.m prog_get; +0x7d0..+0x7e7 left out). Breath of the Wild showed that a game can hand NVN control sections with bytes that are
not the shader's (botw: its own allocation after the section); bytes that change from one start to the next would give
a new key every start, and then the cache never hits. FC 26's shaders come from Frostbite's shader depot at run time, so
this is measured, not assumed.

Input: two (or more) files written by TOTK_CTL_DUMP=<file> (nvn_mtl.m: one line per program stage the game binds,
"<key>\\t<stage>\\t<SHA-256 of the code without its 0x30-byte header for graphics>\\t<control section, 0x880 bytes hex>").
Compares the first start with each next one: shaders whose code is in both are matched by that code hash; their keys
should be the same. When they are not, prints which control bytes differ (offsets inside the hashed length are the ones
that matter). No game data is printed: only offsets, counts and hashes."""
import argparse
from collections import Counter
import json
import struct
import sys
from pathlib import Path

CONTROL_LEN = 0x880


KEY_SKIP = (0x7d0, 0x7e8)   # nvn_mtl.m CTL_KEY_SKIP_LO/HI: left out of the key


def key_len(control):
    """nvn_mtl.m ctl_key_len."""
    n = struct.unpack_from('<I', control, 0x20)[0]
    return n if 0x7cc <= n < 0x880 else 0x880


def hashed(offset, n):
    """Does the control byte at offset enter the key (nvn_mtl.m ctl_key_update) of a section hashed up to n?"""
    return offset < n and not KEY_SKIP[0] <= offset < KEY_SKIP[1]


def read_dump(path):
    """code hash -> {key: control bytes}; plus the count of malformed lines."""
    codes, bad = {}, 0
    with open(path, encoding='ascii', errors='replace') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            try:
                key, stage, code, control = parts[0], int(parts[1]), parts[2], bytes.fromhex(parts[3])
                if len(parts) != 4 or len(key) != 64 or len(code) != 64 or len(control) != CONTROL_LEN or stage not in (0, 1, 5):
                    raise ValueError
            except (ValueError, IndexError):
                bad += 1
                continue
            codes.setdefault(code, {}).setdefault(key, control)
    return codes, bad


def ranges(offsets):
    """Sorted offsets as "0x100-0x107" ranges."""
    out, start, prev = [], None, None
    for o in sorted(offsets):
        if start is None:
            start = prev = o
        elif o == prev + 1:
            prev = o
        else:
            out.append((start, prev)); start = prev = o
    if start is not None:
        out.append((start, prev))
    return [f'{a:#x}' if a == b else f'{a:#x}-{b:#x}' for a, b in out]


def compare(first, other):
    common = sorted(set(first) & set(other))
    stable, unstable, inside, outside, header_only = 0, 0, Counter(), Counter(), 0
    for code in common:
        a, b = first[code], other[code]
        if set(a) == set(b):
            stable += 1
            continue
        unstable += 1
        ca, cb = next(iter(a.values())), next(iter(b.values()))
        n = min(key_len(ca), key_len(cb))
        diff = [i for i in range(CONTROL_LEN) if ca[i] != cb[i]]
        inside.update(i for i in diff if hashed(i, n))
        outside.update(i for i in diff if not hashed(i, n))
        if not any(hashed(i, n) for i in diff):
            header_only += 1   # same hashed control bytes: the code's 0x30-byte header (not in the dump) differs
    return dict(common_codes=len(common), stable=stable, unstable=unstable,
                only_first=len(set(first) - set(other)), only_other=len(set(other) - set(first)),
                differing_hashed_bytes=ranges(inside), differing_unhashed_bytes=ranges(outside),
                most_common_hashed=[f'{o:#x} ({c})' for o, c in inside.most_common(8)], header_only=header_only)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('dumps', nargs='+', type=Path, help='TOTK_CTL_DUMP files of two or more starts, first start first')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    missing = [str(p) for p in args.dumps if not p.is_file()]
    if missing:
        ap.error('not found: ' + ', '.join(missing))
    if len(args.dumps) < 2:
        ap.error('two starts at least')
    runs = [read_dump(p) for p in args.dumps]
    first = runs[0][0]
    report = dict(starts=[dict(dump=str(p), codes=len(c), keys=sum(len(k) for k in c.values()),
                               codes_with_several_keys=sum(len(k) > 1 for k in c.values()), malformed=bad)
                          for p, (c, bad) in zip(args.dumps, runs)],
                  comparisons=[compare(first, c) for c, _ in runs[1:]])
    report['stable'] = all(c['unstable'] == 0 and c['common_codes'] > 0 for c in report['comparisons'])
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for i, s in enumerate(report['starts'], 1):
            print(f'abertura {i}: {s["dump"]}: {s["codes"]} códigos, {s["keys"]} chaves '
                  f'({s["codes_with_several_keys"]} códigos com mais de uma chave na mesma abertura), {s["malformed"]} linhas inválidas')
        for i, c in enumerate(report['comparisons'], 2):
            print(f'abertura 1 x {i}: {c["common_codes"]} códigos nas duas; mesma chave {c["stable"]}, chave diferente {c["unstable"]} '
                  f'(só na 1: {c["only_first"]}, só na {i}: {c["only_other"]})')
            if c['unstable']:
                print(f'  bytes do controle que entram na chave e mudaram: {", ".join(c["differing_hashed_bytes"]) or "nenhum"}')
                print(f'  mais frequentes: {", ".join(c["most_common_hashed"]) or "—"}')
                print(f'  fora do trecho da chave (não importam): {", ".join(c["differing_unhashed_bytes"]) or "nenhum"}')
                if c['header_only']:
                    print(f'  {c["header_only"]} com o controle igual no trecho da chave: muda o cabeçalho de 0x30 bytes do código')
        print('veredito: ' + ('chave ESTÁVEL entre aberturas: o cache serve' if report['stable'] else
                              'chave NÃO estável (ou nada em comum): o cache não acerta; ver os bytes acima e docs/SHADERS_NUVEM.md'))
    return 0 if report['stable'] else 1


if __name__ == '__main__':
    sys.exit(main())
