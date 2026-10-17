#!/usr/bin/env python3
"""Runtime shader translation service for the native runtime (one JSON request per stdin line).

Pipeline per request: Switch Maxwell code -> SPIR-V (tools/totk_xlate, Ryujinx translator, persistent
--serve process) -> MSL (spirv-cross with argument buffers) -> replay reflection JSON in the D2R route-B
format (binding decoding rules ported from D2R Mobile dm/gfx/tools/dmsh_build.py, MIT).
The host answers the translator's queries from the real bound state; the reply records which answers
the translation actually depended on, so the host can reuse it only where those answers still hold.
Request: {"variant", "stage": "vs|ps|cs", "code": path, "c1": hex, "tex": {slot: type}, "img": {slot: {type, fmt}},
          "attr": {loc: float|sint|uint}, "fout": {idx: float|sint|uint}, "local": [x, y, z]}
Reply:   {"ok": true} or {"ok": false, "error": "..."}; outputs <out>/<variant>_b.metal and <variant>_b.json."""
import argparse
import json
import os
import re
import subprocess
import sys

TEX_BASE, SAMP_BASE, IMG_BASE = 0x168, 0x568, 0x120
# TOTK (NVN 55): combined texture handles bound with nvnCommandBufferBindTexture live at c2+0x20, 32 slots of 8 bytes
# (measured over 300 pixel and 400 vertex shaders of the game); separate textures stay at 0x168, samplers at 0x568.
COMBINED_BASE, COMBINED_SLOTS = 0x20, 32
XC = ['--msl', '--msl-version', '20300', '--msl-argument-buffers', '--msl-texture-buffer-native', '--msl-pad-fragment-output']
# Driver-segment words the replay fills, per stage (nvn_mtl.m drv_fillable / encode_args): c0 storage-buffer table of the stage,
# compute thread-group counts (0x200) and uniform-buffer table (0x210), vertex point-size limit (0x610); c2 handle tables.
DRV_FILL = {
    'vs': {0: [(0x110, 0x210), (0x610, 0x620)]},
    'ps': {0: [(0x510, 0x610)]},
    'cs': {0: [(0x200, 0x410)]},
}
DRV_FILL_C2 = [(0x20, 0x120), (0x168, 0x568), (0x568, 0x968)]
STAGE_PREFIX = {'vs': 'vp', 'ps': 'fp', 'cs': 'cp'}


def decode_tex(name):
    m = re.match(r'[a-z]+_[ti]\w*?_(?:cb(\d+)|tcb)_([0-9A-F]+)', name)
    if not m:
        return None
    slots = int(m.group(1)) if m.group(1) else -1
    h = int(m.group(2), 16)
    tb = (slots & 0xffff) if slots >= 0 else 2
    sb = ((slots >> 16) - 1) if slots >= 0 and (slots >> 16) else tb
    o0, o1, ty = h & 0x3fff, (h >> 14) & 0x3fff, h >> 28

    def slot(word, base, cb):
        return (word * 4 - base) // 8 if cb == 2 and word * 4 >= base and (word * 4 - base) % 8 == 0 else None
    words = [o0] + ([o1] if ty else [])
    if re.match(r'[a-z]+_i', name):
        return next((slot(x, IMG_BASE, tb) for x in words if IMG_BASE <= x * 4 < TEX_BASE and slot(x, IMG_BASE, tb) is not None), None), None, ty
    t = next((slot(x, TEX_BASE, tb) for x in words if slot(x, TEX_BASE, tb) is not None and x * 4 < SAMP_BASE), None)
    if t is None:
        t = next((slot(x, COMBINED_BASE, tb) for x in words if COMBINED_BASE <= x * 4 < COMBINED_BASE + 8 * COMBINED_SLOTS and slot(x, COMBINED_BASE, tb) is not None), None)
    s = next((slot(x, SAMP_BASE, sb) for x in words if x * 4 >= SAMP_BASE and slot(x, SAMP_BASE, sb) is not None), None)
    return t, s, ty



# TOTK: depth-format textures sampled through plain texture slots. Metal returns nothing for a depth texture read as
# texture2d and depth formats cannot be viewed as colour formats, so the MSL is rewritten: the declaration becomes
# depth2d / depth2d_array / depthcube (same for _ms), and every .sample / .read on it is wrapped so the scalar depth
# becomes (d, 0, 0, 1) like a depth texture fetch on NVN. .gather already returns float4 on depth textures.
DEPTH_TYPES = {'texture2d': 'depth2d', 'texture2d_array': 'depth2d_array', 'texturecube': 'depthcube',
               'texturecube_array': 'depthcube_array', 'texture2d_ms': 'depth2d_ms', 'texture2d_ms_array': 'depth2d_ms_array'}


def tex_slot_of_name(name):
    m = re.match(r'\w+_t_tcb_([0-9A-Fa-f]+)$', name)
    return (int(m.group(1), 16) - 8) // 2 if m else -1


def rewrite_depth_textures(src, depth_slots):
    names = []
    for m in re.finditer(r'\b(texture\w+)<float>\s+(\w+)\s*\[\[id\((\d+)\)\]\]', src):
        ty, name = m.group(1), m.group(2)
        if tex_slot_of_name(name) in depth_slots:
            if ty not in DEPTH_TYPES:
                raise RuntimeError(f'depth texture {name} declared as {ty}: no depth equivalent')
            names.append((ty, name))
    for ty, name in names:
        src = re.sub(r'\b' + ty + r'<float>\s+' + name + r'\b', DEPTH_TYPES[ty] + '<float> ' + name, src, count=1)
        # compare sampling: spirv-cross casts the texture2d to depth2d itself; the declaration is now depth2d, drop the cast
        src = re.sub(r'spvDepthCast\(((?:\w+\.)*' + name + r')\)', r'\1', src)
        # depth2d.gather takes no component argument (only the depth component exists)
        gpat = re.compile(r'((?:\w+\.)*' + name + r')\.gather\(')
        pos = 0
        while True:
            m = gpat.search(src, pos)
            if not m:
                break
            i = m.end(); depth = 1
            while i < len(src) and depth:
                depth += {'(': 1, ')': -1}.get(src[i], 0)
                i += 1
            call = src[m.end():i - 1]
            if re.search(r'component::[yzw]', call):
                raise RuntimeError(f'gather of a non-x component on depth texture {name}')
            call2 = re.sub(r',\s*component::x', '', call)
            src = src[:m.end()] + call2 + src[i - 1:]
            pos = m.end() + len(call2) + 1
        pat = re.compile(r'((?:\w+\.)*' + name + r')\.(sample|read)\(')
        pos = 0
        while True:
            m = pat.search(src, pos)
            if not m:
                break
            start = m.start(1)
            i = m.end()
            depth = 1
            while i < len(src) and depth:
                depth += {'(': 1, ')': -1}.get(src[i], 0)
                i += 1
            if depth:
                raise RuntimeError(f'unbalanced call on depth texture {name}')
            src = src[:start] + 'totk_depth_fetch(' + src[start:i] + ')' + src[i:]
            pos = i + len('totk_depth_fetch()')
    if names:
        src = src.replace('using namespace metal;', 'using namespace metal;\nstatic inline float4 totk_depth_fetch(float d) { return float4(d, 0.0, 0.0, 1.0); }', 1)
    return src

def msl_stores_through(msl, name):
    """True when the MSL stores or does atomics through storage binding `name` (same rule as nvn_mtl.m msl_stores_through)."""
    if f'&(*spvDescriptorSet0.{name})' in msl:
        return True
    return re.search(r'\(\*spvDescriptorSet0\.%s\)\._m0\[(?:[^\[\]]|\[[^\[\]]*\])*\](?:\.[xyzw]+)?\s*=(?!=)' % re.escape(name), msl) is not None


def reflect(stage, msl, res):
    body = re.search(r'struct spvDescriptorSetBuffer0\s*\{(.*?)\};', msl, re.S)
    binds = []
    for m in re.finditer(r'^\s*(.+?)\s+(\w+)\s*\[\[id\((\d+)\)\]\];', body.group(1) if body else '', re.M):
        ty, nm, aid = m.group(1).strip(), m.group(2), int(m.group(3))
        e = {'msl_name': nm, 'msl_type': ty, 'arg_id': aid}
        if nm == 'support_buffer':
            e.update(kind='support')
        elif re.fullmatch(r'[a-z]+_c(\d+)', nm):
            n = int(re.fullmatch(r'[a-z]+_c(\d+)', nm).group(1))
            e.update(kind='cbuf', reg=n - 3) if 3 <= n <= 16 else e.update(kind='c1' if n == 1 else 'drvcb', bank=n)
        elif re.fullmatch(r'[a-z]+_s(\d+)', nm):
            e.update(kind='sbuf', index=int(re.fullmatch(r'[a-z]+_s(\d+)', nm).group(1)))
        elif nm.endswith('Smplr'):
            t, s, ty2 = decode_tex(nm[:-5])
            e.update(kind='samp', reg=s) if ty2 else e.update(kind='samp_tex', reg=t)
        else:
            d = decode_tex(nm)
            if not d:
                e.update(kind='?')
            else:
                e.update(kind='img' if re.match(r'[a-z]+_i', nm) else ('tbuf' if 'texture_buffer' in ty else 'tex'), reg=d[0])
        binds.append(e)
    base = {'vs': 0x110, 'cs': 0x310, 'ps': 0x510}.get(stage)
    sb_sorted = sorted(res['sbufs'], key=lambda b: b['binding'])
    for e in binds:
        if e['kind'] == 'sbuf':
            b = sb_sorted[e['index']] if e['index'] < len(sb_sorted) else None
            off = b['cb_offset'] * 4 if b and b['cb_slot'] == 0 else None
            if stage == 'cs' and off is not None and 0x210 <= off < 0x310 and (off - 0x210) % 16 == 0:
                e.update(kind='ubo_ptr', reg=(off - 0x210) // 16)
            elif b and b['cb_slot'] != 0 and 3 <= b['cb_slot'] <= 16:
                # TOTK: the shader itself loads this storage buffer's address from a user uniform block
                # (NVN uniform slot cb_slot-3, byte offset cb_offset*4); the replay reads that pointer at bind time
                e.update(kind='sbuf_ubo', reg=b['cb_slot'] - 3, off=b['cb_offset'] * 4)
            else:
                e['reg'] = (off - base) // 16 if off is not None and base is not None and 0 <= off - base < 0x100 and (off - base) % 16 == 0 else None
            # Ryujinx BufferUsageFlags.Write is 1 << 0 (this tested bit 2 until 2026-10-16, so no cached reflection ever said rw);
            # the MSL is the other witness: a store `(*spvDescriptorSet0.<name>)._m0[...] = ` or an atomic `&(*spvDescriptorSet0.<name>)`
            # (a non-const `device` pointer alone is not: spirv-cross emits it for most fragment shaders that only read)
            e['rw'] = bool(b and b['flags'] & 1) or msl_stores_through(msl, nm)
    return binds


def drv_reads(src, stage):
    # spirv-cross names the driver segments <stage>p_c0 / <stage>p_c2; until 2026-10-15 only fp_ was matched, so vertex and
    # compute shaders reading c0 got the all-zero segment at run time
    out = {}
    for bank in (0, 2):
        offs, dyn = set(), False
        for m in re.finditer(r'%s_c%d\)\._m0\[([^\]]+)\]' % (STAGE_PREFIX[stage], bank), src):
            idx = m.group(1).rstrip('u')
            if idx.isdigit():
                offs.add(int(idx) * 16)
            else:
                dyn = True
        if offs or dyn:
            out[str(bank)] = {'vec4_offsets': sorted(offs), 'dynamic': dyn}
    return out


def unfillable(dr, stage):
    bad = []
    for bank, d in dr.items():
        if d['dynamic']:
            bad.append(f'c{bank} dynamic index')
        ranges = DRV_FILL_C2 if int(bank) == 2 else DRV_FILL[stage].get(int(bank), [])
        for o in d['vec4_offsets']:
            if not any(a <= o < b for a, b in ranges):
                bad.append(f'c{bank}+{o:#x}')
    return bad


class Service:
    def __init__(self, args):
        self.args = args
        self.xlate = subprocess.Popen([args.dotnet, args.xlate, '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def translate(self, job, out):
        self.xlate.stdin.write(json.dumps({'job': job, 'out': out}) + '\n')
        self.xlate.stdin.flush()
        line = self.xlate.stdout.readline()
        if not line:
            raise RuntimeError('translator exited')
        if not line.startswith('ok '):
            raise RuntimeError(line.strip()[:300])

    def handle(self, rq):
        out, variant, stage = self.args.out, rq['variant'], rq['stage']
        if stage not in ('vs', 'ps', 'cs'):
            raise RuntimeError(f'stage {stage} not supported by the translation chain')
        if stage == 'cs' and not rq.get('local'):
            raise RuntimeError('compute shader without thread group size')
        # TOTK (2026-10-13): the Ryujinx AST optimizer drops atomics whose result is unused (the luminance-histogram kernel
        # c7830fac lost its OpAtomicSMin; with DebugMode = optimizer off it is kept). DebugMode changes no semantics, only
        # code shape. --debug-mode / TOTK_SHADER_DEBUGMODE selects it (2026-10-16: made switchable to A/B the optimizer
        # after the dead-code cascade fix, tools/totk_xlate/patches/0002).
        job = {'key': variant, 'stage': stage, 'code': rq['code'], 'c1': rq.get('c1', ''), 'debug': bool(self.args.debug_mode), 'reduced': True,
               'tex': rq.get('tex', {}), 'img': rq.get('img', {}), 'attr': rq.get('attr', {}), 'fout': rq.get('fout', {})}
        if rq.get('local'):
            job['local'] = rq['local']
        job['depth_minus_w'] = bool(rq.get('depth_minus_w', False))   # nvnDeviceSetDepthMode(NEAR_IS_MINUS_W): clip z converted to Metal's 0..w in the shader
        self.translate(job, out)
        res = json.load(open(os.path.join(out, variant + '.res.json')))
        msl = os.path.join(out, variant + '_b.metal')
        r = subprocess.run([self.args.spirv_cross, *XC, os.path.join(out, variant + '.spv'), '--output', msl], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError('spirv-cross: ' + r.stderr.strip()[:300])
        src = open(msl).read()
        softfloat64 = bool(re.search(r'\bdouble\b|unsupported_GLSLstd450(?:Pack|Unpack)Double2x32', src))
        if softfloat64:
            # Metal has no FP64 in shaders. Ask Ryujinx's existing
            # DoubleToFloat lowering pass to emit a supported fallback for
            # this variant, keeping ordinary shaders on their original path.
            job['softfloat64'] = True
            self.translate(job, out)
            res = json.load(open(os.path.join(out, variant + '.res.json')))
            r = subprocess.run([self.args.spirv_cross, *XC, os.path.join(out, variant + '.spv'), '--output', msl], capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError('spirv-cross FP64 fallback: ' + r.stderr.strip()[:300])
            src = open(msl).read()
            if re.search(r'\bdouble\b|unsupported_GLSLstd450(?:Pack|Unpack)Double2x32', src):
                raise RuntimeError('Ryujinx FP64 fallback still emitted Metal-unsupported double')
        depth_slots = {int(k) for k, v in rq.get('tex', {}).items() if isinstance(v, str) and v.endswith('_depth')}
        if depth_slots:
            src = rewrite_depth_textures(src, depth_slots)
            with open(msl, 'w') as f:
                f.write(src)
        entry = re.search(r'(vertex|fragment|kernel)\s+\S+\s+(\w+)\s*\(', src)
        dr = drv_reads(src, stage)
        vertex_inputs = [{'location': int(m.group(2)), 'msl_type': m.group(1)} for m in re.finditer(r'(\w+)\s+\w+\s*\[\[attribute\((\d+)\)\]\]', src)]
        out_struct = re.search(r'struct main0_out\s*\{(.*?)\};', src, re.S)
        colors = sorted({int(x) for x in re.findall(r'\[\[color\((\d+)\)\]\]', out_struct.group(1) if out_struct else '')})
        # Answers this translation depends on: queried texture/image slots, consumed vertex inputs, written colour outputs.
        # TOTK: every texture slot the MSL actually binds is a dependency too (not only the slots the translator queried):
        # a depth-format texture in such a slot changes the MSL (depth2d rewrite), so the variant must be keyed on it.
        used_slots = {tex_slot_of_name(m.group(2)) for m in re.finditer(r'\b(texture\w+|depth\w+)<float>\s+(\w+)\s*\[\[id\(\d+\)\]\]', src)}
        used_slots.discard(-1)
        deps = {'tex': {str(s): rq.get('tex', {}).get(str(s), '2d') for s in set(res.get('tex_queried', [])) | used_slots},
                'img': {str(s): rq.get('img', {}).get(str(s), {}) for s in res.get('img_queried', [])},
                'attr': {str(v['location']): rq.get('attr', {}).get(str(v['location']), 'float') for v in vertex_inputs} if stage == 'vs' else {},
                'fout': {str(c): rq.get('fout', {}).get(str(c), 'float') for c in colors} if stage == 'ps' else {}}
        refl = {'key': variant + '_b', 'route': 'B', 'chain': self.args.chain, 'stage': stage,
                'entry': entry.group(2) if entry else 'main0', 'msl_entry_kind': entry.group(1) if entry else None,
                'threadgroup_size': rq.get('local'), 'c1': rq.get('c1', ''), 'notes': res['notes'],
                'drv_reads': dr, 'drv_unfillable': unfillable(dr, stage), 'bindings': reflect(stage, src, res),
                'vertex_inputs': vertex_inputs, 'raster': {}, 'deps': deps, 'softfloat64': softfloat64}
        tmp = os.path.join(out, variant + '_b.json.tmp')
        with open(tmp, 'w') as f:
            json.dump(refl, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(out, variant + '_b.json'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dotnet', required=True)
    ap.add_argument('--xlate', required=True)
    ap.add_argument('--spirv-cross', dest='spirv_cross', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--chain', required=True)
    ap.add_argument('--debug-mode', dest='debug_mode', type=int, default=int(os.environ.get('TOTK_SHADER_DEBUGMODE', '1')),
                    help='1 = translator DebugMode (AST optimizer off, the default since 2026-10-13); 0 = optimizer on')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    svc = Service(args)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            svc.handle(json.loads(line))
            reply = {'ok': True}
        except Exception as e:  # reported to the host, which stops with the message
            reply = {'ok': False, 'error': f'{type(e).__name__}: {e}'[:500]}
        sys.stdout.write(json.dumps(reply) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
