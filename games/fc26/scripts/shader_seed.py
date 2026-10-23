#!/usr/bin/env python3
"""FC 26's shaders, found in the game's data and translated before play (docs/SHADER_SEED.md).

The runtime translates a shader the first time the game binds it (nvn_mtl.m prog_get -> totk_shader_rt.m
totk_rt_variant), which is a stall in play. Frostbite keeps the shaders in its .cas packages, in blocks compressed with
Oodle; each one is stored as the NVN code (0x30-byte header 0x12345678 / compute 0x12345679, instructions, c1 constants)
followed by its 0x880-byte control section (GLSLC magic 0x98761234) -- the same bytes the game hands nvnProgramSetShaders,
so the shader key computed here is the runtime's: SHA-256(control[:ctl_key_len] without +0x7d0..+0x7e7 + code[:u32 at
control+0x704]).

  scan       every .cas of the RomFS -> <out>/shaders/<key>.shader (the journal's FC26SHD1 format) + inventory.tsv
  translate  extracted shaders -> the translation cache (<key>-<suffix>.code/_b.metal/_b.json, <key>.variants), with the
             translator the runtime starts (totk_xlate --service), for the default bind state (or the journal's)
  prove      one shader the runtime already translated: same key, same bytes as the journal, same variant name and the
             same translation as in the cache (the cache is only read; the translation goes to a scratch folder)
  coverage   how many of the journal's shaders (the ones the game bound) the extracted shaders give, by the key their
             bytes hash to now (journal and extraction are only read)

Decompression is the game's own OodleLZ_Decompress, run by fc26-native's "oodle" mode (runtime/oodle_tool.c) on the
loaded main module, without starting the game. Everything written is game data: work folder only, never the repo."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parents[1]
CONTROL_MAGIC = struct.pack('<I', 0x98761234)
CONTROL_LEN = 0x880
CODE_MAGIC = {0x12345678: 'graphics', 0x12345679: 'compute'}
STAGES = {0: 'vs', 1: 'ps', 5: 'cs'}          # totk_rt_variant: the stages with a translation chain
CODE_MAX = 16 << 20                           # totk_rt_variant's bound on the code area
BLOCK_RAW, BLOCK_OODLE = 0x00, 0x19           # Frostbite block kinds seen in FC 26's .cas (main+0x8af0d30 dispatches them)
BLOCK_MAX = 1 << 20
JOURNAL_MAGIC = b'FC26SHD1'
JOURNAL_FORMAT = 1
DEFAULT_ANSWERS = dict(tex={}, img={}, attr={}, fout={})   # the bind state nothing is known about (prepare_shader_seed.py)


# ---------- the runtime's key and names ----------
def control_key_len(control):
    """nvn_mtl.m ctl_key_len: the word at +0x20 when it is between 0x7cc and 0x880, else 0x880."""
    n = struct.unpack_from('<I', control, 0x20)[0]
    return n if 0x7cc <= n < 0x880 else 0x880


def code_length(control):
    return struct.unpack_from('<I', control, 0x704)[0]


KEY_SKIP = (0x7d0, 0x7e8)   # nvn_mtl.m CTL_KEY_SKIP_LO/HI: an identifier of the compiled record, not read by the translation


def shader_key(control, code):
    """nvn_mtl.m prog_get ctl_key_update (and runtime/shader_cache.c fc26_sc_shader_key)."""
    n, (lo, hi) = control_key_len(control), KEY_SKIP
    return hashlib.sha256(control[:min(n, lo)] + control[hi:n] + code[:code_length(control)]).hexdigest()


def _natural(key):
    return [(0, int(t), '') if t.isdigit() else (1, 0, t) for t in re.findall(r'\d+|\D+', key)]


def ns_json(value):
    """NSJSONSerialization with NSJSONWritingSortedKeys, as totk_rt_variant writes requests and indexes: compact, keys in
    NSString numeric order ("9" before "10"; the journal's 371 rows of 2026-10-23 all match), "/" escaped."""
    if isinstance(value, dict):
        return '{' + ','.join(ns_json(str(k)) + ':' + ns_json(value[k]) for k in sorted(value, key=lambda k: _natural(str(k)))) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(ns_json(v) for v in value) + ']'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace('/', '\\/')
    return json.dumps(value)


def variant_name(key, answers):
    """totk_rt_variant: <key>-<first 6 bytes of SHA-256 of the answers' JSON, in hex>."""
    return f'{key}-{hashlib.sha256(ns_json(answers).encode()).hexdigest()[:12]}'


def thread_group(control):
    """nvn_mtl.m rt_local: the compute thread group size at control+0x748."""
    return list(struct.unpack_from('<3I', control, 0x748))


def request(variant, stage, control, code, answers, code_path, depth_minus_w=False):
    """The translator request totk_rt_variant sends, and the code bytes it writes to <variant>.code."""
    c1o, c1t = struct.unpack_from('<II', control, 0x700)
    if not c1t or c1t > CODE_MAX or c1o > c1t or (stage != 5 and c1o < 0x30):
        raise ValueError(f'code area {c1t:#x} / c1 {c1o:#x}')
    if stage not in STAGES:
        raise ValueError(f'NVN stage {stage} has no translation chain')
    skip = 0 if stage == 5 else 0x30
    rq = dict(variant=variant, stage=STAGES[stage], code=str(code_path), c1=code[c1o:c1t].hex())
    rq.update(answers)
    if stage == 5:
        rq['local'] = thread_group(control)
    rq['depth_minus_w'] = bool(depth_minus_w)
    return rq, code[skip:c1t]


# ---------- Frostbite blocks ----------
def block_header(buf, off, end):
    """(raw size, kind, payload size) of the block at off, or None. Header: big-endian u32 raw size, u8 kind, u8 0x70 |
    payload size bits 16-19, big-endian u16 payload size bits 0-15; a raw block's payload is its raw size."""
    if off + 8 > end:
        return None
    raw, kind, flags, low = struct.unpack_from('>IBBH', buf, off)
    if flags & 0xf0 != 0x70 or not 0 < raw <= BLOCK_MAX:
        return None
    size = (flags & 0xf) << 16 | low
    if off + 8 + size > end or kind not in (BLOCK_RAW, BLOCK_OODLE):
        return None
    if kind == BLOCK_RAW and size != raw:
        return None
    if kind == BLOCK_OODLE and (not size or buf[off + 8] & 0xf != 0xc):   # Oodle's own stream header: low nibble 0xC
        return None
    return raw, kind, size


def iter_blocks(buf, decompress, start=0, end=None):
    """(offset, raw bytes) of every block, in file order. A .cas starts with a catalogue (big-endian u32 size, then that
    many bytes) and has stretches that are not blocks; those are skipped one byte at a time, as is a header whose payload
    does not decompress to its raw size. decompress(payload, raw size) -> bytes or None."""
    end = len(buf) if end is None else end
    off = start
    while off < end:
        h = block_header(buf, off, end)
        if not h:
            off += 1
            continue
        raw_size, kind, size = h
        payload = buf[off + 8:off + 8 + size]
        raw = bytes(payload) if kind == BLOCK_RAW else decompress(bytes(payload), raw_size)
        if raw is None:
            off += 1
            continue
        yield off, raw
        off += 8 + size


def find_shaders(data, start=0):
    """Shaders in decompressed data: each control section (magic 0x98761234 + u32 1) whose code (u32 at +0x704 bytes,
    stored just before it) starts with the NVN code magic. Returns ([(position of the control, stage, control, code)],
    keep): keep is where an incomplete control section at the end starts (or len(data)), for streaming."""
    found, pos, keep = [], start, len(data)
    while True:
        i = data.find(CONTROL_MAGIC, pos)
        if i < 0:
            break
        pos = i + 1
        if i + CONTROL_LEN > len(data):
            keep = i
            break
        control = bytes(data[i:i + CONTROL_LEN])
        if struct.unpack_from('<I', control, 4)[0] != 1:
            continue
        n = code_length(control)
        if not 0x30 <= n <= CODE_MAX or n > i:
            continue
        code = bytes(data[i - n:i])
        if struct.unpack_from('<I', code, 0)[0] not in CODE_MAGIC:
            continue
        found.append((i, struct.unpack_from('<I', control, 0x714)[0], control, code))
    return found, keep


def journal_bytes(stage, control, code):
    """runtime/shader_cache.c fc26_sc_journal_put_shader's <key>.shader."""
    return JOURNAL_MAGIC + struct.pack('<4I', JOURNAL_FORMAT, stage, CONTROL_LEN, len(code)) + control + code


def read_journal_shader(path):
    b = Path(path).read_bytes()
    if b[:8] != JOURNAL_MAGIC:
        raise ValueError(f'{path}: not an FC26SHD1 shader')
    fmt, stage, clen, n = struct.unpack_from('<4I', b, 8)
    if fmt != JOURNAL_FORMAT or clen != CONTROL_LEN or len(b) != 24 + clen + n:
        raise ValueError(f'{path}: bad FC26SHD1 header')
    return stage, b[24:24 + clen], b[24 + clen:]


# ---------- the game's Oodle decoder ----------
def find_oodle_decompress(image, text_end):
    """main's OodleLZ_Decompress: the function whose prologue (stp x29, x30, [sp, #-n]!) is the closest one before the
    adrp+add of its own name, "OodleLZ_Decompress" (Oodle's timing/log plugin is called with it on entry)."""
    name = image.find(b'\0OodleLZ_Decompress\0')
    if name < 0:
        raise ValueError('no "OodleLZ_Decompress" string in main')
    name += 1
    words = memoryview(image)[:text_end - text_end % 4].cast('I')
    hits = []
    for at in range(len(words)):
        w = words[at]
        if w & 0x9f000000 != 0x90000000:
            continue
        imm = ((w >> 5) & 0x7ffff) << 2 | (w >> 29) & 3
        if imm & 1 << 20:
            imm -= 1 << 21
        if (at * 4 & ~0xfff) + (imm << 12) != name & ~0xfff:
            continue
        rd = w & 31
        add = words[at + 1] if at + 1 < len(words) else 0
        if add & 0xffc00000 == 0x91000000 and (add >> 5) & 31 == rd and (add >> 10) & 0xfff == name & 0xfff:
            hits.append(at * 4)
    for xref in hits:
        for back in range(xref, max(xref - 0x100, 0), -4):
            if words[back // 4] & 0xffc07fff == 0xa9807bfd:
                return back
    raise ValueError('OodleLZ_Decompress entry not found')


def module_layout(rewritten, name='main'):
    """TEXT_END of a rewritten module (<name>.fixups.tsv)."""
    for line in (Path(rewritten) / f'{name}.fixups.tsv').read_text().splitlines():
        if line.startswith('# TEXT_END'):
            return int(line.split()[-1], 16)
    raise ValueError('TEXT_END missing')


class Oodle:
    """fc26-native <rewritten> oodle, restarted if a block makes it stop (the decoder asserts on corrupt data)."""

    def __init__(self, native, rewritten, offset, log):
        self.cmd = [str(native), str(rewritten), 'oodle']
        self.env = dict(os.environ, FC26_OODLE_OFFSET=f'{offset:x}', TOTK_HEADLESS='1')
        self.log, self.proc, self.restarts = log, None, 0

    def _start(self):
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, env=self.env,
                                     cwd=str(Path(self.cmd[1]).resolve().parents[1]))

    def decompress(self, payload, raw_size):
        if self.proc is None:
            self._start()
        try:
            self.proc.stdin.write(struct.pack('<3I', 0x4c444f4f, len(payload), raw_size)); self.proc.stdin.write(payload)
            self.proc.stdin.flush()
            head = self.proc.stdout.read(8)
            if len(head) != 8:
                raise BrokenPipeError
        except BrokenPipeError:
            for pipe in (self.proc.stdin, self.proc.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass
            self.proc.wait(); self.proc = None; self.restarts += 1
            return None
        got = struct.unpack('<q', head)[0]
        return self.proc.stdout.read(got) if got == raw_size else None

    def close(self):
        if self.proc:
            self.proc.stdin.close(); self.proc.wait(); self.proc.stdout.close(); self.proc = None


def cas_files(romfs):
    """(path, offset, size) of every .cas inside romfs.bin (scripts/extract_romfs.py index.json)."""
    index = json.loads((Path(romfs) / 'index.json').read_text())
    return [(f['path'], f['offset'], f['size']) for f in index['files'] if f['path'].endswith('.cas')]


def scan_buffer(buf, decompress, on_shader, window=8 << 20, tail=2 << 20):
    """Every shader in one .cas's bytes: the blocks decompressed in order into one stream (a shader can cross blocks).
    The stream is searched every window bytes; the last tail bytes stay for the code of a control section that comes
    next (a code area longer than tail across a cut would be missed: FC 26's are a few KiB)."""
    stream, searched, stats = bytearray(), 0, dict(blocks=0, raw_bytes=0)
    for _, raw in iter_blocks(buf, decompress):
        stats['blocks'] += 1; stats['raw_bytes'] += len(raw)
        stream += raw
        if len(stream) > window:
            found, searched = find_shaders(stream, searched)
            for s in found:
                on_shader(*s[1:])
            cut = max(0, searched - tail)
            del stream[:cut]
            searched -= cut
    for s in find_shaders(stream, searched)[0]:
        on_shader(*s[1:])
    return stats


def cmd_scan(args):
    out = Path(args.out); shaders = out / 'shaders'; shaders.mkdir(parents=True, exist_ok=True)
    rewritten = Path(args.rewritten)
    image = (rewritten / 'main.patched.bin').read_bytes()
    offset = find_oodle_decompress(image, module_layout(rewritten)); del image
    log = open(out / 'oodle.log', 'ab')
    oodle = Oodle(args.native, rewritten, offset, log)
    files = [f for f in cas_files(args.romfs) if not args.only or any(o in f[0] for o in args.only)]
    inventory, stages, total = {}, {}, dict(blocks=0, raw_bytes=0, controls=0)
    started = time.time()
    with open(Path(args.romfs) / 'romfs.bin', 'rb') as f:
        whole = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for path, base, size in files:
            t0, before = time.time(), len(inventory)

            def keep(stage, control, code, path=path):
                total['controls'] += 1
                key = shader_key(control, code)
                if key in inventory:
                    inventory[key]['seen'] += 1
                    return
                inventory[key] = dict(stage=stage, code_len=len(code), source=path, seen=1)
                stages[stage] = stages.get(stage, 0) + 1
                target = shaders / f'{key}.shader'
                if not target.exists():
                    tmp = target.with_suffix('.tmp'); tmp.write_bytes(journal_bytes(stage, control, code)); tmp.replace(target)
            st = scan_buffer(memoryview(whole)[base:base + size], oodle.decompress, keep)
            for k in ('blocks', 'raw_bytes'):
                total[k] += st[k]
            print(f'{path}: {st["blocks"]} blocos ({st["raw_bytes"] >> 20} MiB), {len(inventory) - before} shaders novos, '
                  f'{time.time() - t0:.0f} s', flush=True)
        del whole
    oodle.close()
    with open(out / 'inventory.tsv', 'w') as f:
        f.write('key\tstage\tcode_len\tseen\tsource\n')
        for key in sorted(inventory):
            e = inventory[key]; f.write(f'{key}\t{e["stage"]}\t{e["code_len"]}\t{e["seen"]}\t{e["source"]}\n')
    summary = dict(cas_files=len(files), shaders=len(inventory), by_stage={STAGES.get(k, str(k)): v for k, v in sorted(stages.items())},
                   control_sections=total['controls'], blocks=total['blocks'],
                   decompressed_mib=total['raw_bytes'] >> 20, oodle_offset=f'{offset:#x}', oodle_restarts=oodle.restarts,
                   seconds=round(time.time() - started, 1), shader_bytes=sum(e['code_len'] + CONTROL_LEN for e in inventory.values()))
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


# ---------- translation into the cache ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_identity(cache):
    """runtime/shader_cache.c's fc26-cache.id as a dict (None when absent)."""
    try:
        lines = (Path(cache) / 'fc26-cache.id').read_text().splitlines()
    except FileNotFoundError:
        return None
    return dict(line.split(' ', 1) for line in lines if ' ' in line)


def check_identity(cache, translator, spirv_cross, chain):
    """The cache must be stamped for this translator: else the runtime's identity check empties it at the next start
    (docs/SHADERS_NUVEM.md 2.3) and everything translated here is lost. Returns depth_minus_w."""
    ident = read_identity(cache)
    if ident is None:
        raise SystemExit(f'{cache}: no fc26-cache.id (open the cache once with fc26-native first, or copy the live one)')
    want = dict(chain=chain, translator=sha256_file(translator), spirv_cross=sha256_file(spirv_cross))
    for field, value in want.items():
        if ident.get(field) != value:
            raise SystemExit(f'{cache}: fc26-cache.id {field} is {ident.get(field)}, this translation would be {value}: '
                             'the runtime would discard it')
    if ident.get('debug_mode', 'default') != os.environ.get('TOTK_SHADER_DEBUGMODE', 'default'):
        raise SystemExit('TOTK_SHADER_DEBUGMODE differs from the cache identity')
    return ident.get('depth_minus_w') == '1'


def lock_cache(cache):
    """The runtime's lock (fc26-cache.lock, flock): a running game holds it; translating next to it would race its index
    writes."""
    fd = os.open(Path(cache) / 'fc26-cache.lock', os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise SystemExit(f'{cache}: a run holds fc26-cache.lock')
    return fd


class Service:
    """totk_xlate --service, started with the runtime's arguments (totk_shader_rt.m service_start)."""

    def __init__(self, translator, spirv_cross, cache, chain):
        self.proc = subprocess.Popen([str(translator), '--service', '--spirv-cross', str(spirv_cross), '--out', str(cache),
                                      '--chain', chain], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def translate(self, rq):
        self.proc.stdin.write(ns_json(rq) + '\n'); self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError('translator exited')
        return json.loads(line)

    def close(self):
        self.proc.stdin.close(); self.proc.wait(); self.proc.stdout.close()


def read_variants(cache, key):
    try:
        v = json.loads((Path(cache) / f'{key}.variants').read_text())
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def write_atomic(path, text):
    tmp = Path(str(path) + f'.tmp{os.getpid()}'); tmp.write_text(text); tmp.replace(path)


def translate_one(service, cache, key, stage, control, code, answers, depth_minus_w):
    """One variant, as totk_rt_variant makes it: .code, request, reply, reflection; returns (variant, deps or error)."""
    variant = variant_name(key, answers)
    code_path = Path(cache) / f'{variant}.code'
    rq, body = request(variant, stage, control, code, answers, code_path, depth_minus_w)
    code_path.write_bytes(body)
    reply = service.translate(rq)
    if not reply.get('ok'):
        return variant, None, str(reply.get('error'))
    refl = json.loads((Path(cache) / f'{variant}_b.json').read_text())
    return variant, refl.get('deps') or {}, None


def journal_answers(journal, key):
    """The bind states the runtime translated a shader for (the journal's <key>.rows), without the thread group."""
    out = []
    try:
        lines = (Path(journal) / f'{key}.rows').read_text().splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        parts = line.split('\t')
        if len(parts) == 4 and parts[0] == 'V':
            a = json.loads(parts[3]); a.pop('local', None)
            out.append((parts[1], a))
    return out


def extracted(shaders):
    """key -> (stage, control, code) of every extracted shader, keyed by its bytes (an extraction made under an older key
    rule keeps its old file names; records that differ only in the bytes the key leaves out are one shader)."""
    out = {}
    for p in sorted(Path(shaders).glob('*.shader')):
        stage, control, code = read_journal_shader(p)
        out.setdefault(shader_key(control, code), (stage, control, code))
    return out


def cmd_translate(args):
    cache, shaders = Path(args.cache), Path(args.out) / 'shaders'
    if not cache.is_dir():
        raise SystemExit(f'{cache}: not a folder')
    depth = check_identity(cache, args.translator, args.spirv_cross, args.chain)
    lock = lock_cache(cache)
    found = extracted(shaders)
    keys = sorted(found)
    if args.keys:
        keys = [k for k in keys if k in set(args.keys)]
    jobs = []
    for key in keys:
        stage, control, code = found[key]
        if stage not in STAGES:
            continue
        have = read_variants(cache, key)
        if args.journal_answers:
            plans = [a for _, a in journal_answers(args.journal_answers, key)] or [DEFAULT_ANSWERS]
        else:
            plans = [DEFAULT_ANSWERS]
        for answers in plans:
            name = variant_name(key, answers)
            if any(v.get('variant') == name for v in have) and (cache / f'{name}_b.metal').exists():
                continue
            jobs.append((key, stage, control, code, answers))
    if args.limit:
        jobs = jobs[:args.limit]
    print(f'{len(keys)} shaders selecionados, {len(jobs)} variantes a traduzir em {args.jobs} tradutores', flush=True)
    index_lock, done, failed, started = threading.Lock(), [0], [], time.time()
    pool = [Service(args.translator, args.spirv_cross, cache, args.chain) for _ in range(min(args.jobs, len(jobs)) or 1)]
    free = list(pool); free_lock = threading.Condition()

    def work(job):
        key, stage, control, code, answers = job
        with free_lock:
            while not free:
                free_lock.wait()
            svc = free.pop()
        try:
            variant, deps, error = translate_one(svc, cache, key, stage, control, code, answers, depth)
        finally:
            with free_lock:
                free.append(svc); free_lock.notify()
        with index_lock:
            done[0] += 1
            if error:
                failed.append((variant, error))
            else:
                vs = [v for v in read_variants(cache, key) if v.get('variant') != variant]
                vs.append(dict(deps=deps, variant=variant))
                write_atomic(cache / f'{key}.variants', ns_json(vs))
            if done[0] % 100 == 0 or done[0] == len(jobs):
                el = time.time() - started
                print(f'  {done[0]}/{len(jobs)} em {el:.0f} s ({el / done[0] * 1000:.0f} ms cada), {len(failed)} falhas', flush=True)
    with concurrent.futures.ThreadPoolExecutor(len(pool)) as ex:
        list(ex.map(work, jobs))
    for s in pool:
        s.close()
    os.close(lock)
    for variant, error in failed[:20]:
        print(f'  FALHOU {variant}: {error[:200]}')
    print(f'traduzidas {len(jobs) - len(failed)}, falhas {len(failed)}, {time.time() - started:.0f} s')
    return 1 if failed else 0   # a variant that fails here would stop the game where it is used (totk_rt_variant die)


def cmd_prove(args):
    """The extracted shader <key> against what the runtime made of it: journal bytes, variant name, translation."""
    key, shaders = args.key, Path(args.out) / 'shaders'
    named = shaders / f'{key}.shader'
    found = {key: read_journal_shader(named)} if named.is_file() else extracted(shaders)
    if key not in found:
        raise SystemExit(f'{key}: no extracted shader hashes to it')
    stage, control, code = found[key]
    result = dict(key=key, stage=stage, key_recomputed=shader_key(control, code))
    jstage, jcontrol, jcode = read_journal_shader(Path(args.journal) / f'{key}.shader')
    result['journal_bytes_equal'] = (jstage, jcontrol, jcode) == (stage, control, code)
    live = Path(args.cache)
    rows = journal_answers(args.journal, key)
    names = {v['variant'] for v in read_variants(live, key)}
    scratch = Path(args.scratch); scratch.mkdir(parents=True, exist_ok=True)
    shutil.copy2(live / 'fc26-cache.id', scratch / 'fc26-cache.id')
    depth = check_identity(scratch, args.translator, args.spirv_cross, args.chain)
    svc = Service(args.translator, args.spirv_cross, scratch, args.chain)
    result['variants'] = []
    for recorded, answers in rows:
        name = variant_name(key, answers)
        variant, deps, error = translate_one(svc, scratch, key, stage, control, code, answers, depth)
        same = {}
        for end in ('.code', '_b.metal', '_b.json'):
            a, b = live / f'{name}{end}', scratch / f'{name}{end}'
            same[end] = a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes()
        result['variants'].append(dict(recorded=recorded, computed=name, name_equal=recorded == name, in_cache_index=name in names,
                                       error=error, files_equal=same))
    svc.close()
    result['ok'] = (result['key_recomputed'] == key and result['journal_bytes_equal'] and bool(result['variants'])
                    and all(v['name_equal'] and v['in_cache_index'] and all(v['files_equal'].values()) for v in result['variants']))
    print(json.dumps(result, indent=1))
    return 0 if result['ok'] else 1


def cmd_coverage(args):
    """The journal's shaders (what the game bound) that the extraction gives, both keyed by their bytes."""
    seed = extracted(Path(args.out) / 'shaders')
    journal = {}
    for p in sorted(Path(args.journal).glob('*.shader')):
        stage, control, code = read_journal_shader(p)
        journal.setdefault(shader_key(control, code), []).append(p.name[:64])
    hit = [k for k in journal if k in seed]
    files = sum(len(v) for v in journal.values())
    result = dict(journal_files=files, journal_shaders=len(journal), extracted_shaders=len(seed), found=len(hit),
                  missing=sorted(set(journal) - set(seed)),
                  journal_files_under_another_key=sum(n != k for k, v in journal.items() for n in v))
    print(json.dumps(result, indent=1) if args.json else
          f'diário: {files} arquivos, {len(journal)} shaders pela chave atual; extraídos: {len(seed)}; '
          f'achados {len(hit)}/{len(journal)}; arquivos do diário com o nome de outra regra: {result["journal_files_under_another_key"]}')
    return 0 if len(hit) == len(journal) else 1


def main(argv=None):
    work = Path(os.environ.get('WORK', Path.home() / 'fc26-switch/work'))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--out', default=work / 'build/shader-seed-fc26', help='extracted shaders + inventory (game data)')
    tools = argparse.ArgumentParser(add_help=False)
    tools.add_argument('--translator', default=work / 'build/shader-service/totk_xlate')
    tools.add_argument('--spirv-cross', default=work / 'build/spirv-cross/spirv-cross')
    tools.add_argument('--chain', default=re.search(r'#define DMSH_CHAIN "([^"]+)"',
                       (HERE / 'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text()).group(1))
    s = sub.add_parser('scan', parents=[common])
    s.add_argument('--romfs', default=work / 'extracted/v100/romfs')
    s.add_argument('--rewritten', default=work / 'rewritten/v100')
    s.add_argument('--native', default=work / 'build/fc26-native', help='an fc26-native with the "oodle" mode')
    s.add_argument('--only', nargs='*', help='only .cas whose path contains one of these')
    t = sub.add_parser('translate', parents=[common, tools])
    t.add_argument('--cache', required=True, help='the translation cache to fill (rt-<chain>; stamped fc26-cache.id)')
    t.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    t.add_argument('--limit', type=int, default=0)
    t.add_argument('--keys', nargs='*')
    t.add_argument('--journal-answers', help='translate each shader for the bind states of this journal (fc26-journal)')
    p = sub.add_parser('prove', parents=[common, tools])
    p.add_argument('--key', required=True)
    p.add_argument('--cache', default=work / 'build/shader-cache/rt-totk-native-v4-unverified', help='read only')
    p.add_argument('--journal', default=work / 'build/shader-cache/fc26-journal', help='read only')
    p.add_argument('--scratch', required=True)
    c = sub.add_parser('coverage', parents=[common])
    c.add_argument('--journal', default=work / 'build/shader-cache/fc26-journal', help='read only')
    c.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    return dict(scan=cmd_scan, translate=cmd_translate, prove=cmd_prove, coverage=cmd_coverage)[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
