#!/usr/bin/env python3
"""What fc26-native compiled while the game was running, run by run: the measure of the shader cache
(docs/SHADERS_NUVEM.md, "Como medir o ganho").

Reads the runtime's log (its stderr: make boot writes it to FC26_LOG) of one or more runs of the same sequence, best
made with TOTK_SURVEY_SHADER_LOG=1 (one line per translation, Metal library and pipeline made on demand, with its frame
and how long it took), and optionally the per-frame table DM_NVN_TSV wrote (--frames, one per run, same order). Prints,
per run, the work done on demand (the stalls a cache removes), the long frames the graphics layer reported, the warm-up
and the cache layer's own lines; with two or more runs, the change from the first one to each next one. --json prints
the numbers instead. No game data is read: only the runtime's own log lines."""
import argparse
import json
import re
import sys
from pathlib import Path

SURVEY = re.compile(r'\[survey-shader\] frame (\d+) (translated|translation FAILED|Metal library(?: FAILED)?|render pipeline|compute pipeline)'
                    r' .*? (?:in|after) ([0-9.]+) ms')
COUNTER = re.compile(r'\[shader\] translated (\d+):')
LONG = re.compile(r'\[长帧\] 帧 (\d+)（([0-9.]+) s）整帧 ([0-9.]+) ms，提交\+出图 ([0-9.]+) ms，GPU ([-0-9.]+) ms；'
                  r'新建管线 (\d+) 条 \+ 着色器库 (\d+) 个共 ([0-9.]+) ms')
WARM_FIRST = re.compile(r'启动关键管线已就绪：等待 (\d+) ms')
WARM_DONE = re.compile(r'管线预热完成：着色器 (\d+) 个 / 渲染管线 (\d+) 个（跳过特化片元 \d+）/ 计算管线 (\d+) 个，后台用时 ([0-9.]+) ms')
WORLD_WAIT = re.compile(r'首次进局等管线预热 (\d+) ms')
GATE = re.compile(r'\[fc26-shader-cache\] warm-up: the first shader use waited (\d+) ms')
FC26 = '[fc26-shader-cache]'


def stats(values):
    """count, total, max and the 95th percentile (nearest rank) of a list of milliseconds."""
    v = sorted(values)
    return dict(count=len(v), total_ms=round(sum(v), 2), max_ms=round(v[-1], 2) if v else 0.0,
                p95_ms=round(v[min(len(v) - 1, int(0.95 * len(v)))], 2) if v else 0.0)


def read_log(path):
    """The numbers of one run's log."""
    on_demand = dict(translations=[], libraries=[], pipelines=[])
    failed, counter, survey, cache_lines = 0, 0, False, []
    long_frames = []
    warm = dict(first_list_ms=None, gate_ms=None, world_ms=None, shaders=None, render_pipelines=None,
                compute_pipelines=None, background_ms=None)
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = SURVEY.search(line)
            if m:
                survey = True
                kind, ms = m.group(2), float(m.group(3))
                if kind == 'translated':
                    on_demand['translations'].append(ms)
                elif kind.startswith('Metal library'):
                    on_demand['libraries'].append(ms)
                elif kind.endswith('pipeline'):
                    on_demand['pipelines'].append(ms)
                if 'FAILED' in kind:
                    failed += 1
                continue
            m = COUNTER.search(line)
            if m:
                counter = max(counter, int(m.group(1)))
                continue
            m = LONG.search(line)
            if m:
                long_frames.append(dict(frame=int(m.group(1)), t_s=float(m.group(2)), frame_ms=float(m.group(3)),
                                        pipelines=int(m.group(6)), libraries=int(m.group(7)), make_ms=float(m.group(8)),
                                        hidden='不可见' in line))
                continue
            for pattern, keys in [(WARM_FIRST, ['first_list_ms']), (WORLD_WAIT, ['world_ms']), (GATE, ['gate_ms']),
                                  (WARM_DONE, ['shaders', 'render_pipelines', 'compute_pipelines', 'background_ms'])]:
                m = pattern.search(line)
                if m:
                    for k, v in zip(keys, m.groups()):
                        warm[k] = float(v) if '.' in v else int(v)
            if FC26 in line:
                cache_lines.append(line.split(FC26, 1)[1].strip())
    making = [f for f in long_frames if f['pipelines'] or f['libraries']]
    return dict(log=str(path), survey=survey, translated_counter=counter, failed=failed,
                on_demand={k: stats(v) for k, v in on_demand.items()},
                stall_ms=round(sum(sum(v) for v in on_demand.values()), 2),
                long_frames=dict(count=len(long_frames), visible=sum(not f['hidden'] for f in long_frames),
                                 with_compiles=len(making), visible_with_compiles=sum(not f['hidden'] for f in making),
                                 compile_ms=round(sum(f['make_ms'] for f in making), 2),
                                 worst=sorted(long_frames, key=lambda f: -f['frame_ms'])[:5]),
                warm=warm, cache=cache_lines)


def read_frames(path):
    """The per-frame table (DM_NVN_TSV): frame time distribution and the frames that made shaders or pipelines."""
    frame_ms, made = {}, {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) != 3 or not parts[1].startswith('@'):
                continue
            try:
                frame, value = int(parts[0]), float(parts[2])
            except ValueError:
                continue
            if parts[1] == '@frame_ms':
                frame_ms[frame] = value
            elif parts[1] in ('@lib_new', '@pso_new') and value > 0:
                made[frame] = made.get(frame, 0) + int(value)
    times = sorted(frame_ms.values())

    def pct(p):
        return round(times[min(len(times) - 1, int(p * len(times)))], 2) if times else 0.0
    return dict(frames=len(times), p50_ms=pct(0.50), p95_ms=pct(0.95), p99_ms=pct(0.99), max_ms=round(times[-1], 2) if times else 0.0,
                over_33ms=sum(t > 1000 / 30 for t in times), over_100ms=sum(t > 100 for t in times),
                frames_making=len(made), slow_frames_making=sum(frame_ms.get(f, 0) > 1000 / 30 for f in made))


def change(a, b):
    if not a:
        return '—' if not b else '+∞'
    return f'{(b - a) / a * 100:+.0f}%'


def text(runs):
    out = []
    for i, r in enumerate(runs, 1):
        d = r['on_demand']
        out.append(f'== Rodada {i}: {r["log"]}')
        if not r['survey']:
            out.append('  (log sem TOTK_SURVEY_SHADER_LOG=1: só o contador de traduções e os quadros longos)')
        out.append(f'  feito durante o jogo (travadas): {r["stall_ms"]:.0f} ms no total')
        for key, name in [('translations', 'traduções'), ('libraries', 'bibliotecas Metal'), ('pipelines', 'pipelines')]:
            s = d[key]
            out.append(f'    {name:18} {s["count"]:6}  total {s["total_ms"]:9.1f} ms  p95 {s["p95_ms"]:7.1f} ms  máx {s["max_ms"]:7.1f} ms')
        out.append(f'    contador do kit: {r["translated_counter"]} traduções nesta rodada; falhas: {r["failed"]}')
        lf = r['long_frames']
        out.append(f'  quadros longos (log [长帧]): {lf["count"]} ({lf["visible"]} visíveis); com compilação: {lf["with_compiles"]} '
                   f'({lf["visible_with_compiles"]} visíveis), {lf["compile_ms"]:.0f} ms compilando neles')
        for f in lf['worst']:
            out.append(f'    quadro {f["frame"]} ({f["t_s"]:.1f} s): {f["frame_ms"]:.1f} ms, {f["pipelines"]} pipelines + {f["libraries"]} bibliotecas '
                       f'({f["make_ms"]:.1f} ms){" — atrás da tela de carregamento" if f["hidden"] else ""}')
        w = r['warm']
        parts = [f'{k}={v}' for k, v in w.items() if v is not None]
        out.append(f'  pré-aquecimento: {", ".join(parts) if parts else "nada no log"}')
        if 'frames' in r:
            fr = r['frames']
            out.append(f'  quadros (DM_NVN_TSV): {fr["frames"]}; p50 {fr["p50_ms"]} / p95 {fr["p95_ms"]} / p99 {fr["p99_ms"]} / máx {fr["max_ms"]} ms; '
                       f'> 33 ms: {fr["over_33ms"]}; > 100 ms: {fr["over_100ms"]}; quadros que compilaram: {fr["frames_making"]} '
                       f'({fr["slow_frames_making"]} deles > 33 ms)')
        for line in r['cache']:
            out.append(f'  {FC26} {line}')
    if len(runs) > 1:
        a = runs[0]
        out.append('== Ganho (rodada 1 → cada seguinte)')
        for i, b in enumerate(runs[1:], 2):
            out.append(f'  rodada {i}: travadas {a["stall_ms"]:.0f} → {b["stall_ms"]:.0f} ms ({change(a["stall_ms"], b["stall_ms"])}); '
                       + '; '.join(f'{name} {a["on_demand"][k]["count"]} → {b["on_demand"][k]["count"]}'
                                   for k, name in [('translations', 'traduções'), ('libraries', 'bibliotecas'), ('pipelines', 'pipelines')])
                       + f'; quadros longos com compilação {a["long_frames"]["with_compiles"]} → {b["long_frames"]["with_compiles"]}')
            if 'frames' in a and 'frames' in b:
                out.append(f'    quadros > 33 ms {a["frames"]["over_33ms"]} → {b["frames"]["over_33ms"]}; p99 {a["frames"]["p99_ms"]} → '
                           f'{b["frames"]["p99_ms"]} ms; máx {a["frames"]["max_ms"]} → {b["frames"]["max_ms"]} ms')
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('logs', nargs='+', type=Path, help='the log of each run, first run first')
    ap.add_argument('--frames', nargs='*', type=Path, default=[], help='DM_NVN_TSV table of each run, same order')
    ap.add_argument('--json', action='store_true', help='print the numbers as JSON')
    args = ap.parse_args(argv)
    missing = [str(p) for p in args.logs + args.frames if not p.is_file()]
    if missing:
        ap.error('not found: ' + ', '.join(missing))
    if args.frames and len(args.frames) != len(args.logs):
        ap.error('--frames needs one table per log')
    runs = [read_log(p) for p in args.logs]
    for r, p in zip(runs, args.frames):
        r['frames'] = read_frames(p)
    sys.stdout.write(json.dumps(runs, ensure_ascii=False, indent=1) + '\n' if args.json else text(runs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
