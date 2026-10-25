"""Summarize encoder spans. Contains no game data; raw captures stay in work/."""
import argparse
import collections
import statistics
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('capture', type=Path)
p.add_argument('--first', type=int)
p.add_argument('--last', type=int)
p.add_argument('--families', action='store_true', help='Merge repeated stages with matching shader/attachments')
a = p.parse_args()
rows = []
for line in a.capture.read_text().splitlines():
    v = line.split('\t')
    if len(v) != 13:
        raise ValueError(f'Invalid capture row ({len(v)} columns)')
    frame, renderpass, kind, ms, draws, w, h, fmt, depth, nc, copies, dispatches, key = v
    f = int(frame)
    if a.first is not None and f < a.first or a.last is not None and f > a.last:
        continue
    rows.append(dict(frame=f, renderpass=int(renderpass), kind=kind, ms=float(ms), draws=int(draws), w=int(w), h=int(h),
                     fmt=fmt, depth=int(depth), nc=int(nc), copies=int(copies), dispatches=int(dispatches), key=key))
frames = sorted({r['frame'] for r in rows if r['kind'] in 'ROBCD'})
if not frames:
    raise ValueError('No replay frames measured')
print(f'Quadros: {len(frames)} ({min(frames)}–{max(frames)}); linhas: {len(rows)}.')
print('Etapas identificadas pela posição da passagem no quadro, tipo, tamanho e formatos; mostramos o primeiro shader mais frequente. Tempos são intervalos de GPU, com possível sobreposição, não custo exclusivo.')
formats = {10:'R8',30:'RG8',70:'RGBA8',80:'BGRA8',92:'RGB11/11/10F',115:'RGBA16F',252:'D32F',260:'D32F+S8'}
base = {}
for r in rows:
    if r['kind'] in 'ROBCD':
        base[r['frame']] = min(base.get(r['frame'], r['renderpass']), r['renderpass'])
groups = collections.defaultdict(list)
for r in rows:
    slot = r['renderpass'] - base.get(r['frame'], 0) if r['kind'] in 'ROBCD' and not a.families else None
    groups[slot, r['kind'], bool(r['draws']), r['w'], r['h'], r['fmt'], r['depth'], r['key'] if a.families else None].append(r)
rank = sorted(groups.values(), key=lambda rr: sum(r['ms'] for r in rr) / len(frames), reverse=True)
print('| # | Origem | Etapa / primeiro shader | Tamanho | Cor; profundidade | ms por quadro¹ | ms por ocorrência | Desenhos médios | Ocorrências/quadro |')
print('|---|---|---|---|---|---:|---:|---:|---:|')
for i, rr in enumerate(rank[:15], 1):
    r = rr[0]
    label = collections.Counter(x['key'] for x in rr).most_common(1)[0][0]
    origin = 'do jogo' if (r['kind'] == 'R' and r['draws']) or r['kind'] == 'D' else 'nossa'
    names = {'R':'desenho', 'O':'conversão por desenho', 'B':'cópias', 'C':'conversão/cálculo', 'D':'cálculo do jogo + cópias', 'P':'apresentação', 'U':'envio/conversão de texturas'}
    stage_name = 'limpeza' if r['kind'] == 'R' and not r['draws'] else names[r['kind']]
    fmt = ','.join(formats.get(int(v), v) for v in r['fmt'].split(',') if v != '0') or '—'
    depth = formats.get(r['depth'], str(r['depth'])) if r['depth'] else '—'
    avg = lambda col: statistics.mean(x[col] for x in rr)
    print(f"| {i} | {origin} | {stage_name} `{label}` p{r['renderpass'] - base.get(r['frame'], 0) if r['kind'] in 'ROBCD' and not a.families else '—'} | {r['w']}×{r['h']} | {fmt}; {depth} | {sum(x['ms'] for x in rr)/len(frames):.4f} | {avg('ms'):.4f} | {avg('draws'):.1f} | {len(rr)/len(frames):.2f} |")
print('¹ Soma dos intervalos do grupo dividida pelos quadros medidos. Não somar a coluna para estimar ocupação total.')
print('Tipos: ' + ', '.join(f'{kind}: {sum(r["kind"]==kind for r in rows)}' for kind in sorted({r['kind'] for r in rows})))
