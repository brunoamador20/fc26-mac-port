#!/usr/bin/env python3
"""Which NVN entry points FC 26's video module asks for and calls, and what the NVN layer answers for each.
Reads the module's analysis ELF (<work>/nro/Engine.Render.Core2.PlatformNvn.nrs: the .nro with its symbol table):
  - asked: the names nvn::nvnLoadCPPProcs passes to the getProcAddress argument (x1 of each "blr x19", in order). The game
    runs it twice (once before nvnDeviceInitialize, once with the device), so the layer sees each name twice: the
    "DeviceGetProcAddress=<n>" of the "[nvn] 初始化 0" log line is 2 x this count. Each name is checked against the
    nvn::pfncpp_<name> pointer the result is stored to (through the GOT entry the loader reads).
  - called: the pfncpp_ pointers referenced anywhere else in .text / Rc2Hot (called() below), plus, with --layout
    (<work>/analysis/runtime-layout.json), the pfncpp_ pointers other modules import (main calls a few through them).
And the layer's answer for each name, from the sources of third_party/d2r_gfx/gfx/nvn as the Makefile compiles them
(every .c / .m, no GAME_* define, macOS), or with --binary from a built runtime's symbols:
  semantic  NVN() / NVN_NOPROTO() registration (section swnvn) for a name of names.txt (main's name table, a thunk each)
  nop       listed in hle_nvn.c g_nops (only counted)
  extra     NVN_EXTRA() (section totknvnx): a name outside names.txt, returned directly by nvn_lookup
  unimpl    in names.txt with no implementation: the thunk stops in nvn_unimpl_c ("[fc26-missing] nvn: <name>")
  null      neither: nvn_lookup logs "NVN 取址未知名字" and the game gets NULL
Usage: nvn_coverage.py <PlatformNvn.nrs> [--layout runtime-layout.json] [--binary fc26-native] [--nvn-dir DIR] [--json FILE].
Exit status 1 when a called name gets unimpl / null or a loader name does not match its pointer. capstone is the only
dependency (requirements.txt)."""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

NVN_DIR = Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn'
LOADER = '_ZN3nvn15nvnLoadCPPProcsEPNS_6DeviceEPFPFvvEPKS0_PKcE'
POINTER = re.compile(r'_ZN3nvn\d+pfncpp_(nvn\w+)E$')


class Elf:
    """The few parts of a little-endian ELF64 the scan needs: sections, symbols, bytes at a virtual address."""
    def __init__(self, data):
        if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
            raise ValueError('not a little-endian ELF64')
        self.data = data
        shoff, = struct.unpack_from('<Q', data, 0x28)
        shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3a)
        rows = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize) for i in range(shnum)]
        names = rows[shstrndx][4]
        self.sections = {}
        for name, kind, _, addr, off, size, link, _, _, entsize in rows:
            label = data[names + name:data.index(b'\0', names + name)].decode()
            self.sections[label] = dict(kind=kind, addr=addr, off=off, size=size, link=link, entsize=entsize)
        self.symbols = []   # (name, value, size, type)
        symtab = self.sections.get('.symtab')
        if symtab:
            strings = rows[symtab['link']][4]
            for k in range(symtab['size'] // 24):
                name, info, _, _, value, size = struct.unpack_from('<IBBHQQ', data, symtab['off'] + 24 * k)
                label = data[strings + name:data.index(b'\0', strings + name)].decode()
                self.symbols.append((label, value, size, info & 0xf))

    def section_of(self, addr):
        for name, s in self.sections.items():
            if s['addr'] and s['addr'] <= addr < s['addr'] + s['size']:
                return name, s
        return None, None

    def read(self, addr, size):
        name, s = self.section_of(addr)
        if s is None or s['kind'] == 8:   # SHT_NOBITS
            return None
        return self.data[s['off'] + addr - s['addr']:s['off'] + addr - s['addr'] + size]

    def cstring(self, addr):
        name, s = self.section_of(addr)
        if s is None or s['kind'] == 8:
            return None
        start = s['off'] + addr - s['addr']
        return self.data[start:self.data.index(b'\0', start)].decode('latin-1')


def disassembler():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    return md


def xreg(md, reg):
    """x<n> for w<n> / x<n> (one register state), None for sp / zr / vector registers."""
    name = md.reg_name(reg)
    if name and name[0] in 'wx' and name[1:].isdigit():
        return 'x' + name[1:]
    return 'x29' if name in ('fp', 'x29') else 'x30' if name in ('lr', 'x30') else None


def pointers(elf):
    """{address of nvn::pfncpp_<name>: name} and {GOT entry address: name} for the entries holding one of them (RELR /
    RELATIVE: the link-time address is stored in place, as the loader's own GOT reads show)."""
    by_addr = {v: POINTER.match(n).group(1) for n, v, _, _ in elf.symbols if POINTER.match(n)}
    got = {}
    for label in ('.got', '.got.plt'):
        s = elf.sections.get(label)
        if not s:
            continue
        for k in range(s['size'] // 8):
            value, = struct.unpack_from('<Q', elf.data, s['off'] + 8 * k)
            if value in by_addr:
                got[s['addr'] + 8 * k] = by_addr[value]
    return by_addr, got


def scan(elf, md, start, end, on_load, on_value=None):
    """Follow ADR / ADRP / ADD / LDR address forming over [start, end): on_load(pc, address, dest) for every load whose
    address is known (dest is the loaded register; its new value is what on_load returns, an address or None) and
    on_value(pc, value) for every address formed in a register."""
    from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM
    code = elf.read(start, end - start)
    starts = {v for n, v, size, t in elf.symbols if t == 2 and start <= v < end}
    regs = {}
    for ins in md.disasm(code, start):
        if ins.address in starts:
            regs = {}
        ops = ins.operands
        m = ins.mnemonic
        out = {}
        if m in ('adrp', 'adr') and len(ops) == 2 and ops[1].type == ARM64_OP_IMM:
            out[xreg(md, ops[0].reg)] = ops[1].imm
        elif m == 'add' and len(ops) == 3 and ops[1].type == ARM64_OP_REG and ops[2].type == ARM64_OP_IMM \
                and xreg(md, ops[1].reg) in regs and not ops[2].shift.type:
            out[xreg(md, ops[0].reg)] = regs[xreg(md, ops[1].reg)] + ops[2].imm
        elif m == 'mov' and len(ops) == 2 and ops[1].type == ARM64_OP_REG and xreg(md, ops[1].reg) in regs:
            out[xreg(md, ops[0].reg)] = regs[xreg(md, ops[1].reg)]
        elif m in ('ldr', 'ldur', 'ldp') and ops[-1].type == ARM64_OP_MEM and not ops[-1].mem.index \
                and xreg(md, ops[-1].mem.base) in regs and not ins.writeback:
            base = regs[xreg(md, ops[-1].mem.base)] + ops[-1].mem.disp
            width = 8 if md.reg_name(ops[0].reg).startswith('x') else 4
            for k, op in enumerate(ops[:-1]):
                value = on_load(ins.address, base + k * width, xreg(md, op.reg))
                if value is not None:
                    out[xreg(md, op.reg)] = value
        for reg in ins.regs_access()[1]:
            regs.pop(xreg(md, reg), None)
        if m in ('bl', 'blr'):
            for k in range(19):
                regs.pop(f'x{k}', None)
        elif m in ('b', 'br', 'ret', 'braa', 'retaa'):
            regs = {}
        out.pop(None, None)
        if on_value:
            for value in out.values():
                on_value(ins.address, value)
        regs.update(out)
    return regs


def asked(elf, md=None):
    """[(name string, pfncpp_ name the result is stored to)] for each getProcAddress call of nvnLoadCPPProcs, in order."""
    md = md or disassembler()
    sym = next((s for s in elf.symbols if s[0] == LOADER), None)
    if sym is None:
        raise ValueError(f'{LOADER} not in the symbol table')
    _, got = pointers(elf)
    code = elf.read(sym[1], sym[2])
    calls, pending, regs = [], None, {}
    for ins in md.disasm(code, sym[1]):
        ops, m = ins.operands, ins.mnemonic
        if m == 'adrp':
            regs[xreg(md, ops[0].reg)] = ops[1].imm
        elif m == 'add' and xreg(md, ops[1].reg) in regs and len(ops) == 3:
            regs[xreg(md, ops[0].reg)] = regs[xreg(md, ops[1].reg)] + ops[2].imm
        elif m == 'ldr' and xreg(md, ops[1].mem.base) in regs:
            regs[xreg(md, ops[0].reg)] = ('got', regs[xreg(md, ops[1].mem.base)] + ops[1].mem.disp)
        elif m == 'blr':
            if pending:
                raise ValueError(f'{pending[0]}: result not stored before the next call ({ins.address:#x})')
            pending = (elf.cstring(regs['x1']), ins.address)
        elif m == 'str' and pending and xreg(md, ops[0].reg) == 'x0':
            slot = regs.get(xreg(md, ops[1].mem.base))
            if not (isinstance(slot, tuple) and slot[1] in got):
                raise ValueError(f'{pending[0]}: stored through {slot} ({ins.address:#x}), not a pfncpp_ GOT entry')
            calls.append((pending[0], got[slot[1]]))
            pending = None
    if pending:
        raise ValueError(f'{pending[0]}: result never stored')
    return calls


def called(elf, md=None):
    """{name: [pc, ...]} of the references to a pfncpp_ pointer outside nvnLoadCPPProcs: its address formed in a register
    (ADR, ADRP + ADD, or the load of its GOT entry) or the pointer loaded directly (ADRP + LDR). Nothing but the loader
    stores to these pointers, so a reference is a read of it, and the read is what precedes every call (the code may
    keep the address in a callee-saved register over a loop before the LDR + BLR, out of reach of a straight-code
    follow: the reference itself is what is counted)."""
    md = md or disassembler()
    by_addr, got = pointers(elf)
    target = {n: a for a, n in by_addr.items()}
    loader = next(s for s in elf.symbols if s[0] == LOADER)
    hits = {}

    def outside(pc):
        return not loader[1] <= pc < loader[1] + loader[2]

    def on_load(pc, address, dest):
        if address in got:   # &pfncpp_<name>
            return target[got[address]]
        if address in by_addr and outside(pc):
            hits.setdefault(by_addr[address], []).append(pc)
        return None

    def on_value(pc, value):
        if value in by_addr and outside(pc):
            hits.setdefault(by_addr[value], []).append(pc)

    for label in ('.text', 'Rc2Hot'):
        s = elf.sections.get(label)
        if s:
            scan(elf, md, s['addr'], s['addr'] + s['size'], on_load, on_value)
    return {n: sorted(set(pcs)) for n, pcs in hits.items()}


# The build's view of the preprocessor conditions around registrations: the Makefile defines no GAME_* for FC 26 and
# builds for macOS. Any other condition around a registration is refused rather than guessed.
MAC_BUILD = {'TARGET_OS_OSX': 1, 'TARGET_OS_IPHONE': 0, 'TARGET_OS_SIMULATOR': 0, '__APPLE__': 1}
REGISTRATION = re.compile(r'^\s*(NVN|NVN_NOPROTO|NVN_EXTRA)\((nvn\w+)\s*,')


def condition(line, defines):
    """Truth of one #if / #ifdef / #ifndef line under defines, None for a form this reader does not evaluate."""
    m = re.match(r'#\s*(ifdef|ifndef)\s+(\w+)', line)
    if m:
        return (m.group(2) in defines) == (m.group(1) == 'ifdef')
    m = re.match(r'#\s*if\s+(!?)\s*(\w+)\s*(?:/[/*].*)?$', line)
    if m:
        value = int(m.group(2)) if m.group(2).isdigit() else defines.get(m.group(2), 0)
        return bool(value) != bool(m.group(1))
    m = re.match(r'#\s*if\s+defined\((\w+)\)\s*&&\s*(\w+)\s*$', line)
    if m:
        return m.group(1) in defines and bool(defines.get(m.group(2), 0))
    return None


def registrations(text, defines=MAC_BUILD, label='source'):
    """[(macro, name)] of the NVN() / NVN_NOPROTO() / NVN_EXTRA() lines the build compiles in text."""
    out, stack = [], []   # stack: (this branch on, some earlier branch taken, evaluable)
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if re.match(r'#\s*if', stripped):
            value = condition(stripped, defines)
            stack.append((bool(value), bool(value), value is not None, number))
        elif re.match(r'#\s*elif', stripped):
            _, taken, _, _ = stack.pop()
            stack.append((False, taken, False, number))   # no #elif is evaluated: registrations under one are refused
        elif re.match(r'#\s*else', stripped):
            _, taken, known, first = stack.pop()
            stack.append((not taken, True, known, first))
        elif re.match(r'#\s*endif', stripped):
            stack.pop()
        else:
            m = REGISTRATION.match(line)
            if not m:
                continue
            unknown = [first for on, _, known, first in stack if not known]
            if unknown:
                raise ValueError(f'{label}:{number}: {m.group(2)} under a condition this reader cannot evaluate (line {unknown[0]})')
            if all(on for on, _, _, _ in stack):
                out.append((m.group(1), m.group(2)))
    return out


def binary_registrations(binary):
    """The same from a built runtime: the e_<name> (swnvn) / ex_<name> (totknvnx) statics of nvn_impl.h, by nm."""
    import subprocess
    listing = subprocess.run(['nm', str(binary)], capture_output=True, text=True, check=True).stdout
    return [('NVN_EXTRA' if kind == 'ex' else 'NVN', name)
            for kind, name in re.findall(r' _?(e|ex)_(nvn\w+)$', listing, re.M)]


def host(nvn_dir=NVN_DIR, binary=None, defines=MAC_BUILD):
    """{name: kind} for every name the NVN layer knows (see the module docstring), and main's name table (names.txt).
    Registrations come from the sources of nvn_dir as the build compiles them, or from a built runtime (binary)."""
    names = (nvn_dir / 'names.txt').read_text().split()
    kinds = {n: 'unimpl' for n in names}
    if binary:
        found = [('binary', macro, name) for macro, name in binary_registrations(binary)]
    else:
        found = [(source.name, macro, name) for source in sorted(nvn_dir.glob('*.c')) + sorted(nvn_dir.glob('*.m'))
                 for macro, name in registrations(source.read_text(), defines, source.name)]
    seen = {}
    for where, macro, name in found:
        if name in seen:   # nvn_init_slots keeps the later one silently
            raise ValueError(f'{name} registered twice ({seen[name]}, {where})')
        seen[name] = where
        if macro == 'NVN_EXTRA':
            if name in kinds:
                raise ValueError(f'{where}: NVN_EXTRA({name}) is in names.txt')
            kinds[name] = 'extra'
        else:
            if name not in kinds:
                raise ValueError(f'{where}: {macro}({name}) is not in names.txt (nvn_init_slots would stop)')
            kinds[name] = 'semantic'
    nops = re.search(r'g_nops\[\]\s*=\s*\{(.*?)\};', (nvn_dir / 'hle_nvn.c').read_text(), re.S)
    for name in re.findall(r'"(nvn\w+)"', re.sub(r'//[^\n]*', '', nops.group(1))):
        if kinds.get(name) != 'unimpl':   # nvn_nops_register stops on this
            raise ValueError(f'g_nops: {name} is {kinds.get(name, "not in names.txt")}')
        kinds[name] = 'nop'
    return kinds, names


def answer(kinds, name):
    return kinds.get(name, 'null')


def imported(layout):
    """{module: [name]} of the nvn::pfncpp_ pointers other modules import (undefined symbols of runtime-layout.json):
    they call through the pointers the video module's loader filled."""
    data = json.loads(Path(layout).read_text())
    modules = data.get('modules', data) if isinstance(data, dict) else data
    out = {}
    for m in modules:
        names = sorted({POINTER.match(s['name']).group(1) for s in m['symbols'] if not s['defined'] and POINTER.match(s['name'])})
        if names:
            out[m['name']] = names
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('module', type=Path, help='analysis ELF of Engine.Render.Core2.PlatformNvn (.nrs)')
    ap.add_argument('--nvn-dir', type=Path, default=NVN_DIR)
    ap.add_argument('--binary', type=Path, help='take the registrations from this built runtime instead of the sources')
    ap.add_argument('--layout', type=Path, help='runtime-layout.json: add the pfncpp_ pointers other modules import')
    ap.add_argument('--json', type=Path, help='write the full table here')
    args = ap.parse_args(argv)
    elf = Elf(args.module.read_bytes())
    md = disassembler()
    loads = asked(elf, md)
    mismatched = [(s, p) for s, p in loads if s != p]
    uses = {n: [f'{pc:#x}' for pc in pcs] for n, pcs in called(elf, md).items()}
    callers = {n: ['video module'] for n in uses}
    for module, names in (imported(args.layout) if args.layout else {}).items():
        for n in names:
            callers.setdefault(n, []).append(module)
    kinds, table = host(args.nvn_dir, args.binary)
    names = [s for s, _ in loads]
    rows = [dict(name=n, called=n in callers, callers=callers.get(n, []), pcs=uses.get(n, [])[:4], answer=answer(kinds, n))
            for n in names]
    print(f'asked by nvnLoadCPPProcs: {len(names)} names ({len(set(names))} distinct), {len(mismatched)} not matching '
          f'the pfncpp_ pointer they are stored to; DeviceGetProcAddress calls for the two loads: {2 * len(names)}')
    print(f'referenced by the video module outside the loader: {len(uses)}; called through an import by another module: '
          f'{len([n for n, c in callers.items() if c != ["video module"]])} '
          f'({", ".join(sorted(n for n, c in callers.items() if "video module" not in c)) or "none"} only there); '
          f'called but not asked: {sorted(set(callers) - set(names)) or "none"}')
    print(f'names.txt names nobody asks for: {", ".join(n for n in table if n not in set(names)) or "none"}')
    for kind in ('semantic', 'nop', 'extra', 'unimpl', 'null'):
        both = [r['name'] for r in rows if r['answer'] == kind]
        hot = [r['name'] for r in rows if r['answer'] == kind and r['called']]
        print(f'  {kind:8} asked {len(both):3}, of them called {len(hot):3}')
    bad = [r for r in rows if r['called'] and r['answer'] in ('unimpl', 'null')]
    bad += [dict(name=n, callers=c, pcs=[], answer=answer(kinds, n)) for n, c in callers.items() if n not in set(names)
            and answer(kinds, n) in ('unimpl', 'null')]
    for r in bad:
        print(f'CALLED {r["answer"]}: {r["name"]} by {", ".join(r["callers"])} {" ".join(r["pcs"])}')
    if args.json:
        args.json.write_text(json.dumps(dict(asked=names, mismatched=mismatched, rows=rows), indent=1, ensure_ascii=False) + '\n')
    return 1 if bad or mismatched else 0


if __name__ == '__main__':
    sys.exit(main())
