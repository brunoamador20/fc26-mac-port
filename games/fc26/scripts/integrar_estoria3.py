#!/usr/bin/env python3
"""Hook runtime/ro (story 3, nn::ro modules) into FC 26's runtime: loader.c, services.c and the Makefile.

Every edit is anchored on text that must occur exactly once; a missing or repeated anchor stops before anything is
written, so a runtime that drifted from the one this was written against is reported, not half-edited. Running it again
changes nothing. --check only reports, --diff also prints what would change. Edits, as described in
docs/ESTORIA3_NUVEM.md ("Pontos de ligação"):
  loader.c   include; ro_module_set_dir(argv[1]); gates, svcSetMemoryPermission / Attribute, svcQueryMemory and
             diagnostics fall through to loaded modules; the probe-ro mode
  services.c svcQueryMemory asks the modules before the "host-owned: Inaccessible" gap (an NRO is mapped after the
             guest reservations, so it can sit in that gap)
  Makefile   build runtime/ro/*.c and depend on runtime/ro/*.h
"""
import argparse
import difflib
import sys
from pathlib import Path

# The code inserted, by name (tests/test_fc26_integration.py compiles each one in the function it goes into).
DIAG = '{const char *mn;uint64_t mo;if(ro_module_offset(%s,&mn,&mo))%s}'   # name / offset inside a loaded NRO
FRAGMENTS = {
    'dispatch': 'if(ro_module_dispatch(ret,regs))return;',
    'permission': 'return ro_module_permission(address,size,permission);',
    'lock': 'return ro_module_lock_permission(address,size,mask,attribute);',
    'query': 'return ro_module_query(address,base,size,state,permission,attribute);',
    'offset': 'return ro_module_offset(pc,name,off);',
    'describe': DIAG % ('a', '{snprintf(out,n,"%s+0x%llx",mn,(unsigned long long)mo);return;}'),
    'trace': DIAG % ('lr', 'fprintf(stderr,"[totk] caller %s+0x%llx\\n",mn,(unsigned long long)mo);'),
    'crash_pc': DIAG % ('pc', '{write(2,mn,strlen(mn));signal_hex(" offset=",mo);}'),
    'crash_frame': DIAG % ('frame[1]', '{write(2,mn,strlen(mn));signal_hex(" offset=",mo);}'),
    'set_dir': 'ro_module_set_dir(argv[1]);',
    'probe': 'if(!strcmp(argv[2],"probe-ro"))return ro_module_probe()?1:0;',
    'svc_query': 'else if(ro_module_query(addr,&base,&size,&state,&perm,&attr)){}',
}
F = FRAGMENTS
EDITS = {
    'runtime/loader.c': [
        ('#include "game_version.h"\n',
         '#include "game_version.h"\n#include "ro/ro_module.h"   /* nn::ro modules loaded at run time (runtime/ro, story 3) */\n'),
        (' runtime_fail("unknown gate return address");\n',
         f' {F["dispatch"]}   /* a gate of a module loaded through nn::ro */\n runtime_fail("unknown gate return address");\n'),
        (' return 0xd401;\n}\nuint64_t runtime_module_lock_permission(', f' {F["permission"]}\n}}\nuint64_t runtime_module_lock_permission('),
        (' return 0xd401;\n}\nint runtime_module_query(', f' {F["lock"]}\n}}\nint runtime_module_query('),
        (' return 0;\n}\nvoid runtime_describe_address(', f' {F["query"]}\n}}\nvoid runtime_describe_address('),
        ('Dl_info di;if(dladdr((void *)(uintptr_t)a,&di)', F['describe'] + 'Dl_info di;if(dladdr((void *)(uintptr_t)a,&di)'),
        (' return 0;\n}\nuintptr_t runtime_frame_controller_return_pc(', f' {F["offset"]}\n}}\nuintptr_t runtime_frame_controller_return_pc('),
        ('fprintf(stderr,"[totk] caller %s+0x%llx\\n",modules[i].name,(unsigned long long)(lr-(uintptr_t)modules[i].base));\n',
         'fprintf(stderr,"[totk] caller %s+0x%llx\\n",modules[i].name,(unsigned long long)(lr-(uintptr_t)modules[i].base));\n'
         f'  {F["trace"]}\n'),
        ('signal_hex(" offset=",pc-(uintptr_t)modules[i].base);}\n',
         f'signal_hex(" offset=",pc-(uintptr_t)modules[i].base);}}\n {F["crash_pc"]}\n'),
        ('signal_hex(" offset=",frame[1]-(uintptr_t)modules[i].base);}if(frame[0]==fp)break;',
         'signal_hex(" offset=",frame[1]-(uintptr_t)modules[i].base);}' + F['crash_frame'] + 'if(frame[0]==fp)break;'),
        (' need(argc==3,', None),   # set_dir goes at the end of main's argument check line (see edit())
        (' for(unsigned i=0;i<NM;i++){seal(&modules[i]);check_permissions(&modules[i]);}\n',
         ' for(unsigned i=0;i<NM;i++){seal(&modules[i]);check_permissions(&modules[i]);}\n'
         f' {F["probe"]}   /* every image of nro_manifest.tsv: map, imports */\n'),
    ],
    'runtime/services.c': [
        ('#include "runtime.h"\n', '#include "runtime.h"\n#include "ro/ro_module.h"\n'),
        ('  else if(addr>=(uintptr_t)low_space+LOW_SIZE&&addr<ALIAS_START){',
         f'  {F["svc_query"]}   /* an nn::ro module, mapped after the reservations */\n'
         '  else if(addr>=(uintptr_t)low_space+LOW_SIZE&&addr<ALIAS_START){'),
    ],
    'Makefile': [
        ('$(wildcard runtime/*.c runtime/*.m runtime/*.S)', '$(wildcard runtime/*.c runtime/*.m runtime/*.S runtime/ro/*.c)'),
        ('RUNTIME_HEADERS := $(wildcard runtime/*.h)', 'RUNTIME_HEADERS := $(wildcard runtime/*.h runtime/ro/*.h)'),
    ],
}


def edit(name, text):
    """The edited text and how many edits were already in; ValueError when an anchor is not there exactly once."""
    done = 0
    for old, new in EDITS[name]:
        if new is None:
            line = next((l for l in text.splitlines(keepends=True) if l.startswith(old)), None)
            if line is None: raise ValueError(f'{name}: no line starting with {old!r}')
            if F['set_dir'] in line: done += 1; continue
            old, new = line, line.rstrip('\n') + F['set_dir'] + "   /* NRO images sit next to main's */\n"
        if new in text: done += 1; continue
        count = text.count(old)
        if count != 1: raise ValueError(f'{name}: anchor found {count} times: {old.strip()[:90]!r}')
        text = text.replace(old, new)
    return text, done


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path, nargs='?', default=Path(__file__).resolve().parents[1], help='games/fc26')
    parser.add_argument('--check', action='store_true', help='report only, write nothing')
    parser.add_argument('--diff', action='store_true', help='print the changes')
    a = parser.parse_args()
    results = {}
    for name in EDITS:   # every file is edited in memory first: nothing is written if one of them does not fit
        old = (a.game / name).read_text()
        results[name] = (old, *edit(name, old))
    for name, (old, new, already) in results.items():
        total = len(EDITS[name])
        print(f'{name}: {"already integrated" if already == total else f"{total - already} edits"}')
        if a.diff and old != new:
            sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f'a/{name}', f'b/{name}'))
        if not a.check and old != new:
            (a.game / name).write_text(new)
    if not (a.game / 'runtime/ro/ro_module.h').exists():
        print('note: runtime/ro is not in this tree yet (merge the story-3 branch first)')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(f'integrar_estoria3: {error}')
