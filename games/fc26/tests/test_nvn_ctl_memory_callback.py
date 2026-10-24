"""FC 26 adds command buffer control memory only when the driver asks through its memory callback (boot cmd1, 2026-10-24:
4,907 recordings, 0 AddControlMemory). Compiles the real ctl_memory_need from hle_nvn.c: it must call the game's callback
with OUT_OF_CONTROL_MEMORY when the recording's 64-byte handle does not fit, and only then. Before it, no recording copy was
ever released (20,000 live, 7 GiB in a match)."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

NVN = Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn'


class ControlMemoryCallback(unittest.TestCase):
    def test_callback_asked_when_the_handle_does_not_fit(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')
        src = (NVN / 'hle_nvn.c').read_text()
        counters = re.search(r'^static uint64_t g_ctl_asks[^\n]*\n', src, re.M)
        fn = re.search(r'^static void ctl_memory_need\(.*?^}\n', src, re.M | re.S)
        self.assertIsNotNone(fn, 'hle_nvn.c has no ctl_memory_need: the game is never asked for control memory')
        self.assertIn('ctl_memory_need(c, o, 64);', src)
        runner = r'''
#include "nvn_obj.h"
#include <stdio.h>
#define LOG(...) (printf(__VA_ARGS__), putchar('\n'))
/*FN*/
static uint8_t mem[2][256]; static int calls, event; static size_t asked;
static void cb(NVNcommandBuffer *c, NVNcommandBufferMemoryEvent e, size_t min, void *d) {
    cmd_t *o = (cmd_t *)c; (void)d; event = e; asked = min; calls++;
    ctl_memory_need(c, o, 64);                       /* re-entered from the callback: must not ask again */
    o->ctl = mem[calls & 1]; o->ctl_size = sizeof mem[0]; o->ctl_used = 0;   /* what AddControlMemory does */
}
int main(void) {
    cmd_t o = {0}; NVNcommandBuffer *c = (NVNcommandBuffer *)&o;
    ctl_memory_need(c, &o, 64);                      /* no callback registered: nothing to ask */
    int none = calls;
    o.cb = cb;
    ctl_memory_need(c, &o, 64);                      /* no control memory */
    int first = calls; int ev = event; size_t sz = asked;
    o.ctl_used = 64; ctl_memory_need(c, &o, 64);     /* 128 of 256: fits */
    int fits = calls;
    o.ctl_used = 200; ctl_memory_need(c, &o, 64);    /* 264 > 256: asked again */
    printf("none=%d first=%d event=%d asked=%zu fits=%d exhausted=%d answered=%llu\n", none, first, ev, sz, fits, calls,
           (unsigned long long)g_ctl_asks_answered);
    return none == 0 && first == 1 && ev == 1 && sz == 64 && fits == 1 && calls == 2 && g_ctl_asks_answered == 2 ? 0 : 1;
}
'''.replace('/*FN*/', (counters.group() if counters else '') + fn.group())
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'runner.c').write_text(runner)
            exe = tmp / 'runner'
            build = subprocess.run([compiler, '-std=gnu11', '-I', str(NVN), '-I', str(NVN / 'include'), str(tmp / 'runner.c'), '-o', str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            print(run.stdout.strip())
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
