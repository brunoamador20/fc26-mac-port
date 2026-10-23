#!/usr/bin/env python3
"""FC 26's identity and module list (assets/game.json), the one place the build reads them from.

As a program it prints one value for the Makefile:
  game_config.py modules            main sdk
  game_config.py <key>              e.g. version_dir -> v100, title_id -> 01004FF021942000
  game_config.py rewrite-env        DM_RULESET=native DM_PRIVATE_GATES=0
  game_config.py check              runtime/game_version.h agrees with assets/game.json (exit 1 if not)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CONFIG = json.loads((HERE / 'assets/game.json').read_text())
MODULES = list(CONFIG['modules'])
VERSION = CONFIG['version_dir']
EXPECTED_PATH = HERE / f"assets/expected-v{CONFIG['display_version']}.json"


def check_config():
    """The module list must be usable by the loader (runtime/loader.c): main first, no duplicates."""
    problems = []
    if not MODULES or MODULES[0] != 'main':
        problems.append(f'modules must start with main (the probe calls main\'s PLT), got {MODULES}')
    if len(set(MODULES)) != len(MODULES):
        problems.append(f'duplicate module in {MODULES}')
    for name in MODULES + list(CONFIG['analysis_modules']):
        if not re.fullmatch(r'[a-z][a-z0-9]*', name):
            problems.append(f'module name {name!r} is not a plain lower-case name')
    if not set(MODULES) <= set(CONFIG['analysis_modules']):
        problems.append('every loaded module must also be in analysis_modules')
    return problems


def game_version_defines(path=HERE / 'runtime/game_version.h'):
    """The #define lines of runtime/game_version.h that must match assets/game.json."""
    found = dict(re.findall(r'^#define\s+(GAME_TITLE_ID|TOTK_GAME_DIR|TOTK_GAME_VERSION)\s+(\S+)', path.read_text(), re.M))
    return found


def check_game_version_h(path=HERE / 'runtime/game_version.h'):
    found = game_version_defines(path)
    want = {'GAME_TITLE_ID': f"0x{CONFIG['title_id'].lower()}ULL",
            'TOTK_GAME_DIR': json.dumps(VERSION),
            'TOTK_GAME_VERSION': json.dumps(CONFIG['display_version'])}
    return [f'{path.name}: {k} is {found.get(k)}, assets/game.json says {v}' for k, v in want.items() if found.get(k) != v]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    what = sys.argv[1]
    if what == 'modules':
        print(' '.join(MODULES))
    elif what == 'analysis_modules':
        print(' '.join(CONFIG['analysis_modules']))
    elif what == 'rewrite-env':
        print(' '.join(f'{k}={v}' for k, v in CONFIG['rewrite_env'].items()))
    elif what == 'check':
        problems = check_config() + check_game_version_h()
        for p in problems:
            print(p, file=sys.stderr)
        sys.exit(1 if problems else 0)
    elif what in CONFIG and isinstance(CONFIG[what], str):
        print(CONFIG[what])
    else:
        sys.exit(f'unknown key {what!r}')


if __name__ == '__main__':
    main()
