#!/usr/bin/env python3
"""Story 4 on the Mac, after make prepare: who answers each nn::ec / ldn / web / aoc / pctl / codec function a module
imports (docs/SERVICOS_NUVEM.md). Reads <work>/analysis/runtime-layout.json (prepare_runtime.py), the rewritten modules
and the runtime sources; it writes nothing.

For every undefined symbol of a module in those namespaces:
  host (name)     a string in runtime/*.c names it exactly, or runtime/offline_applets.c's prefix table matches it: the
                  host function runs instead of the sdk's
  sdk (native)    another module defines it: the game's own code runs; what it asks over IPC reaches the services the
                  host registers (listed at the end: runtime/offline_services.c, hwopus.c, ...)
  nro (late)      an NRO loaded later by nn::ro exports it (the layout's late_symbols): the loader leaves the slot for it
  weak, stays 0   a weak import nobody defines: the slot stays 0, which the SDK tests
  MISSING         nobody defines it and the host does not answer it: boot stops with "strong import unresolved"
Then, for the service names of story 4: whether each rewritten module holds it as a string and whether the host
registers it (a name built in code instead of stored as a string is not found: absence proves nothing).
--all lists every MISSING import of every namespace, not only these six (boot stops at the first one).
"host (name)" is read from the sources: any string literal naming the symbol counts, also one that names it for another
reason (an observer, a symbol lookup); in the six namespaces every such string today is a replacement.
Exit 1 when something is MISSING.
Usage: python3 scripts/check_offline_imports.py [--work <work>] [--all]   (default work: FC26_WORK or assets/game.json)"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))   # also under python -I
import game_config

NAMESPACES = ['ec', 'ldn', 'web', 'aoc', 'pctl', 'codec']
SERVICES = ['aoc:u', 'pctl', 'pctl:a', 'pctl:s', 'pctl:r', 'ldn:u', 'ldn:s', 'ldn:m', 'nim:eca', 'nim:ecas', 'hwopus']
SCOPE = re.compile(r'^_ZNK?2nn(?:' + '|'.join(f'{len(n)}{n}' for n in NAMESPACES) + r')(?=\d)')


def host_names(runtime=HERE / 'runtime'):
    """Exact names (string literals starting with _Z) -> the file naming them; the applet prefixes; registered services."""
    exact, services = {}, set()
    for path in sorted(runtime.glob('*.[cm]')):
        text = path.read_text(errors='replace')
        for name in re.findall(r'"(_Z[A-Za-z0-9_]+)"', text):
            exact.setdefault(name, path.name)
        services.update(re.findall(r'runtime_ipc_register\("([^"]+)"', text))
    applets = (runtime / 'offline_applets.c').read_text()
    prefixes = [f'_ZN2nn{len(a)}{a}{len(f)}{f}E{p}' for a, f, p in re.findall(r'\{"(\w+)", "(\w+)", "(\w*)", \w+\}', applets)]
    return exact, prefixes, services


def demangle(names):
    tool = shutil.which('c++filt') or shutil.which('llvm-cxxfilt')
    if not tool or not names:
        return list(names)
    cmd = [tool, '-n'] if platform.system() == 'Darwin' else [tool]
    out = subprocess.run(cmd, input='\n'.join(names) + '\n', capture_output=True, text=True).stdout.splitlines()
    return out if len(out) == len(names) else list(names)


def classify(modules, exact, prefixes, everything=False, late=()):
    """[(module, name, status, detail)] for the undefined symbols in scope (every namespace's MISSING ones with everything).
    late: the layout's late_symbols, [{name, nro}]."""
    late = {s['name']: s['nro'] for s in late}
    defined = {}
    for m in modules:
        for s in m['symbols']:
            if s['defined'] and s['name']:
                defined.setdefault(s['name'], []).append(m['name'])
    rows = []
    for m in modules:
        for s in m['symbols']:
            name = s['name']
            if s['defined'] or not name:
                continue
            in_scope = bool(SCOPE.match(name))
            prefix = next((p for p in prefixes if name.startswith(p)), None)
            if name in exact:
                status, detail = 'host (name)', f'exact name in runtime/{exact[name]}'
            elif prefix:
                status, detail = 'host (name)', f'runtime/offline_applets.c prefix {prefix}'
            elif name in defined:
                status, detail = 'sdk (native)', 'defined by ' + ', '.join(defined[name])
            elif name in late:
                status, detail = 'nro (late)', f'exported by {late[name]}, bound when nn::ro loads it'
            elif s.get('binding') == 2:
                status, detail = 'weak, stays 0', 'nobody defines it'
            else:
                status, detail = 'MISSING', 'nobody defines it; boot stops: strong import unresolved'
            if in_scope or (everything and status == 'MISSING'):
                rows.append((m['name'], name, status, detail))
    return rows


def service_strings(work, module_names, services):
    """{service: [modules holding it as a NUL-terminated string]} from the rewritten images that exist."""
    found = {s: [] for s in services}
    for name in module_names:
        path = work / f'rewritten/{game_config.VERSION}/{name}.patched.bin'
        if not path.exists():
            continue
        image = path.read_bytes()
        for s in services:
            if b'\0' + s.encode() + b'\0' in image:
                found[s].append(name)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--work', type=Path, default=Path(os.environ.get('FC26_WORK') or HERE / game_config.CONFIG['work']))
    parser.add_argument('--all', action='store_true', help='also list every MISSING import outside the six namespaces')
    args = parser.parse_args()
    layout = args.work / 'analysis/runtime-layout.json'
    if not layout.exists():
        raise SystemExit(f'check_offline_imports: {layout} missing: run make prepare first')
    data = json.loads(layout.read_text())   # {modules, late_symbols} (prepare_runtime.py); a bare module list before
    modules, late = (data['modules'], data.get('late_symbols', [])) if isinstance(data, dict) else (data, [])
    exact, prefixes, registered = host_names()
    rows = classify(modules, exact, prefixes, args.all, late)
    names = demangle([r[1] for r in rows])
    print(f'imports in nn::{{{",".join(NAMESPACES)}}}' + (' and every MISSING import' if args.all else '') + f': {len(rows)}')
    for (module, name, status, detail), readable in zip(rows, names):
        print(f'  {status:<14} {module}: {readable}\n  {"":<14} {name}  ({detail})')
    found = service_strings(args.work, [m['name'] for m in modules], SERVICES)
    print('services of story 4 (string in module / registered by the host):')
    for s in SERVICES:
        print(f'  {s:<9} {",".join(found[s]) or "-":<12} {"registered" if s in registered else "NOT registered"}')
    missing = [r for r in rows if r[2] == 'MISSING']
    print(f'{len(missing)} MISSING' if missing else 'nothing MISSING')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
