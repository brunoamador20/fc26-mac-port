"""scripts/nvn_coverage.py: the NVN names FC 26's video module asks nvnDeviceGetProcAddress for (nvn::nvnLoadCPPProcs),
the ones it references afterwards, and what the NVN layer answers for each. A synthetic aarch64 ELF shaped like the
module's loader and call sites (no game data), synthetic layer sources, and the real layer sources against the list of
names FC 26 1.0.0 calls (assets/nvn-called-v1.0.0.txt, made by the script from the real module)."""
from pathlib import Path
import io
import json
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import nvn_coverage  # noqa: E402

TEXT, RO, GOT, ZI = 0x1000, 0x3000, 0x4000, 0x5000


def adrp(rd, pc, target):
    imm = (target >> 12) - (pc >> 12)
    return 0x90000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def adr(rd, pc, target):
    imm = target - pc
    return 0x10000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def add(rd, rn, imm):
    return 0x91000000 | (imm << 10) | (rn << 5) | rd


def ldr(rt, rn, imm=0):
    return 0xF9400000 | ((imm // 8) << 10) | (rn << 5) | rt


def str_(rt, rn):
    return 0xF9000000 | (rn << 5) | rt


def mov(rd, rm):
    return 0xAA0003E0 | (rm << 16) | rd


def blr(rn):
    return 0xD63F0000 | (rn << 5)


def bl(pc, target):
    return 0x94000000 | (((target - pc) >> 2) & 0x3FFFFFF)


RET = 0xD65F03C0


def pointer_symbol(name):
    tail = 'pfncpp_' + name
    return f'_ZN3nvn{len(tail)}{tail}E'


def module(names, stored=None, code=None):
    """An ELF64 with nvnLoadCPPProcs asking for names (the result of call k stored to the pfncpp_ of stored[k]) and the
    functions of code: [(symbol, [word or callable(pc, where) -> word])], where(name) = (GOT entry, pointer)."""
    stored = stored or names
    pointers = sorted(set(names) | set(stored))
    where = {n: (GOT + 8 * k, ZI + 8 * k) for k, n in enumerate(pointers)}
    strings, offsets = b'', {}
    for n in names:
        offsets[n] = RO + len(strings)
        strings += n.encode() + b'\0'
    words = [mov(19, 1), mov(20, 0)]
    for n, s in zip(names, stored):
        pc = TEXT + 4 * len(words)
        words += [adrp(1, pc, offsets[n]), add(1, 1, offsets[n] & 0xFFF), mov(0, 20), blr(19),
                  adrp(8, pc + 16, where[s][0]), ldr(8, 8, where[s][0] & 0xFFF), str_(0, 8)]
    words.append(RET)
    funcs = [(nvn_coverage.LOADER, TEXT, 4 * len(words))]
    for label, body in code or []:
        start = TEXT + 4 * len(words)
        for item in body:
            pc = TEXT + 4 * len(words)
            words.append(item(pc, where) if callable(item) else item)
        funcs.append((label, start, TEXT + 4 * len(words) - start))
    text = b''.join(struct.pack('<I', w) for w in words)
    got = b''.join(struct.pack('<Q', where[n][1]) for n in pointers)
    symbols = [(label, addr, size, 2, 1) for label, addr, size in funcs] + \
              [(pointer_symbol(n), where[n][1], 8, 1, 4) for n in pointers]
    strtab, symtab = b'\0', b'\0' * 24
    for label, value, size, kind, shndx in symbols:
        symtab += struct.pack('<IBBHQQ', len(strtab), 0x10 | kind, 0, shndx, value, size)
        strtab += label.encode() + b'\0'
    # sections: null, .text, RO, .got, ZI, .symtab, .strtab, .shstrtab
    shstr, names_at = b'\0', {}
    for label in ('.text', 'RO', '.got', 'ZI', '.symtab', '.strtab', '.shstrtab'):
        names_at[label] = len(shstr)
        shstr += label.encode() + b'\0'
    body, placed = bytearray(0x40), {}
    for label, data in (('.text', text), ('RO', strings), ('.got', got), ('.symtab', symtab), ('.strtab', strtab), ('.shstrtab', shstr)):
        placed[label] = (len(body), len(data))
        body += data + b'\0' * (-len(data) % 8)
    rows = [b'\0' * 64]
    for label, kind, addr, link, entsize in (('.text', 1, TEXT, 0, 0), ('RO', 1, RO, 0, 0), ('.got', 1, GOT, 0, 0),
                                             ('ZI', 8, ZI, 0, 0), ('.symtab', 2, 0, 6, 24), ('.strtab', 3, 0, 0, 0),
                                             ('.shstrtab', 3, 0, 0, 0)):
        off, size = placed.get(label, (0, 8 * len(pointers)))
        rows.append(struct.pack('<IIQQQQIIQQ', names_at[label], kind, 0, addr, off, size, link, 0, 8, entsize))
    shoff = len(body)
    body += b''.join(rows)
    header = b'\x7fELF' + bytes([2, 1, 1]) + b'\0' * 9 + struct.pack('<HHIQQQIHHHHHH', 3, 183, 1, 0, 0, shoff, 0, 64, 0, 0, 64, len(rows), 7)
    body[:0x40] = header
    return bytes(body)


def got_ldr(rd, name):        # ADRP + LDR of name's GOT entry: rd = &pfncpp_<name>
    return [lambda pc, w: adrp(rd, pc, w[name][0]), lambda pc, w: ldr(rd, rd, w[name][0] & 0xFFF)]


class Loader(unittest.TestCase):
    def test_names_in_order_and_checked_against_the_pointer_they_fill(self):
        elf = nvn_coverage.Elf(module(['nvnA', 'nvnBb', 'nvnCcc']))
        self.assertEqual(nvn_coverage.asked(elf), [('nvnA', 'nvnA'), ('nvnBb', 'nvnBb'), ('nvnCcc', 'nvnCcc')])

    def test_a_name_stored_to_another_pointer_is_shown(self):
        elf = nvn_coverage.Elf(module(['nvnA', 'nvnB'], stored=['nvnB', 'nvnA']))
        self.assertEqual(nvn_coverage.asked(elf), [('nvnA', 'nvnB'), ('nvnB', 'nvnA')])


class Called(unittest.TestCase):
    def test_references_as_the_game_makes_them(self):
        names = ['nvnGot', 'nvnAdr', 'nvnHoisted', 'nvnClobbered', 'nvnNever']
        code = [
            # DeviceNvn::enqueueProcessFrame shape: the GOT entry in a callee-saved register, called later
            ('hoisted', [*got_ldr(21, 'nvnHoisted'), lambda pc, w: bl(pc, TEXT), ldr(8, 21), blr(8), RET]),
            ('direct', [*got_ldr(8, 'nvnGot'), ldr(8, 8), mov(0, 19), blr(8), RET]),
            # PlatformEncoderNvn shape: ADR of the pointer itself (0x8b74c)
            ('adr', [lambda pc, w: adr(8, pc, w['nvnAdr'][1]), ldr(8, 8), blr(8), RET]),
            # the page register dies in the call: the LDR after it is not a reference
            ('clobbered', [lambda pc, w: adrp(8, pc, w['nvnClobbered'][0]), lambda pc, w: bl(pc, TEXT),
                           lambda pc, w: ldr(9, 8, w['nvnClobbered'][0] & 0xFFF), RET]),
        ]
        elf = nvn_coverage.Elf(module(names, code=code))
        self.assertEqual(sorted(nvn_coverage.called(elf)), ['nvnAdr', 'nvnGot', 'nvnHoisted'])

    def test_the_loader_own_reads_do_not_count(self):
        self.assertEqual(nvn_coverage.called(nvn_coverage.Elf(module(['nvnA', 'nvnB']))), {})


class Host(unittest.TestCase):
    def layer(self, files):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name, text in files.items():
            (Path(folder.name) / name).write_text(text)
        return Path(folder.name)

    def test_kinds(self):
        nvn = self.layer({
            'names.txt': 'nvnSem\nnvnProto\nnvnNop\nnvnStub\nnvnBotw\nnvnMac\n',
            'hle_nvn.c': 'NVN(nvnSem, void, int x) {}\nNVN_NOPROTO(nvnProto, int, int x) { return 0; }\n'
                         '#ifdef GAME_BOTW\nNVN(nvnBotw, void, int x) {}\n#else\nNVN(nvnMac, void, int x) {}\n#endif\n'
                         'static const char *const g_nops[] = {\n    "nvnNop",\n    // "nvnStub",\n};\n',
            'ext.c': 'NVN_EXTRA(nvnOutside, void, int x) {}\n',
        })
        kinds, names = nvn_coverage.host(nvn)
        self.assertEqual(kinds, {'nvnSem': 'semantic', 'nvnProto': 'semantic', 'nvnNop': 'nop', 'nvnStub': 'unimpl',
                                 'nvnBotw': 'unimpl', 'nvnMac': 'semantic', 'nvnOutside': 'extra'})
        self.assertEqual(nvn_coverage.answer(kinds, 'nvnUnknown'), 'null')

    def test_refused(self):
        base = {'names.txt': 'nvnA\n', 'hle_nvn.c': 'static const char *const g_nops[] = { };\n'}
        for label, extra in [('outside the name table', 'NVN(nvnB, void, int x) {}\n'),
                             ('extra inside the name table', 'NVN_EXTRA(nvnA, void, int x) {}\n'),
                             ('twice', 'NVN(nvnA, void, int x) {}\nNVN(nvnA, void, int x) {}\n'),
                             ('condition not evaluated', '#if FOO > 1\nNVN(nvnA, void, int x) {}\n#endif\n')]:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    nvn_coverage.host(self.layer({**base, 'ext.c': extra}))

    def test_every_name_fc26_calls_is_answered(self):
        # The real layer as the Makefile builds it. Before fc26_nvn_ext.c this listed the 8 names of docs/NVN_LACUNAS_NUVEM.md.
        called = [l.split()[0] for l in (HERE / 'assets/nvn-called-v1.0.0.txt').read_text().splitlines()
                  if l and not l.startswith('#')]
        self.assertEqual(len(called), 243)
        kinds, _ = nvn_coverage.host()
        self.assertEqual({n: nvn_coverage.answer(kinds, n) for n in called
                          if nvn_coverage.answer(kinds, n) not in ('semantic', 'nop')}, {})


class Report(unittest.TestCase):
    def test_exit_status_and_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'm.nrs').write_bytes(module(['nvnGot', 'nvnIdle'], code=[('f', [*got_ldr(8, 'nvnGot'), ldr(8, 8), blr(8), RET])]))
            nvn = folder / 'nvn'
            nvn.mkdir()
            (nvn / 'hle_nvn.c').write_text('static const char *const g_nops[] = { };\n')
            for implemented, status in ((True, 0), (False, 1)):
                (nvn / 'names.txt').write_text('nvnGot\nnvnIdle\n')
                (nvn / 'ext.c').write_text('NVN(nvnGot, void, int x) {}\n' if implemented else '')
                out = io.StringIO()
                with redirect_stdout(out):
                    code = nvn_coverage.main([str(folder / 'm.nrs'), '--nvn-dir', str(nvn), '--json', str(folder / 'o.json')])
                with self.subTest(implemented=implemented):
                    self.assertEqual(code, status, out.getvalue())
                    self.assertIn('DeviceGetProcAddress calls for the two loads: 4', out.getvalue())
                    self.assertEqual('CALLED unimpl: nvnGot by video module' in out.getvalue(), not implemented)
                    rows = json.loads((folder / 'o.json').read_text())['rows']
                    self.assertEqual([(r['name'], r['called']) for r in rows], [('nvnGot', True), ('nvnIdle', False)])


if __name__ == '__main__':
    unittest.main()
