"""Compila o filtro real do registro; nenhum dado do jogo ou dispositivo GPU."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

NVN = Path(os.environ.get('FC26_NVN_DIR') or Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn')

class PassdumpTarget(unittest.TestCase):
    def test_target_filter_preserves_frame_requests(self):
        source = (NVN/'nvn_mtl.m').read_text()
        func = re.search(r'^static int passdump\(void\) \{.*?^}', source, re.M|re.S)
        self.assertIsNotNone(func)
        runner = r'''
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static _Atomic uint64_t g_cur_frame;
static long g_pd_at=-1,g_pd_n;
typedef struct {struct {unsigned width,height;} d;} tex_t;
static struct {int has_rt;struct {int n;tex_t *color[8],*depth;} rt;} R;
/*REAL*/
#define CHECK(want) do {int got=passdump();if(got!=(want)){fprintf(stderr,"line %d: got %d expected %d\n",__LINE__,got,(want));return 1;}checks++;}while(0)
int main(int argc,char **argv){(void)argv;int checks=0;
 tex_t small={{16,16}},target={{512,1024}};
 R.has_rt=1;R.rt.n=2;R.rt.color[0]=&small;R.rt.color[1]=&target;
 CHECK(argc==1);
 target.d.height=1023;CHECK(0);
 R.rt.color[1]=NULL;target.d.height=1024;R.rt.depth=&target;CHECK(argc==1);
 R.has_rt=0;CHECK(0);
 g_pd_at=10;g_pd_n=2;atomic_store(&g_cur_frame,10);CHECK(1);
 atomic_store(&g_cur_frame,11);CHECK(1);
 atomic_store(&g_cur_frame,12);CHECK(0);
 atomic_store(&g_cur_frame,20);CHECK(1);
 atomic_store(&g_cur_frame,21);CHECK(1);
 atomic_store(&g_cur_frame,22);CHECK(0);
 printf("checks=%d\n",checks);return 0;}
'''.replace('/*REAL*/',func.group())
        with tempfile.TemporaryDirectory() as tmp:
            c,exe=Path(tmp)/'filter.c',Path(tmp)/'filter'
            c.write_text(runner)
            build=subprocess.run(['clang','-std=c11',str(c),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            for target,extra in [('512x1024',[]),('bad',['invalid']),('0x0',['invalid'])]:
                env=dict(os.environ,DM_NVN_PASSDUMP_RT=target,DM_NVN_PASSDUMP='20-21')
                run=subprocess.run([str(exe),*extra],env=env,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertIn('checks=10',run.stdout)

if __name__=='__main__':unittest.main()
