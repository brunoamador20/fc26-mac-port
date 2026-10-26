"""Compile the actual first-upload branch; inject a write after its snapshot."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

NVN = Path(os.environ.get('FC26_NVN_DIR') or Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn')

class InitialUploadHash(unittest.TestCase):
    def test_write_between_upload_and_cache_publication(self):
        source = (NVN / 'nvn_mtl.m').read_text()
        hashing = re.search(r'^static uint64_t pkg_hash\(.*?^}', source, re.M | re.S).group()
        start = source.index('        TILELOG(t, "first upload from the pool bytes");')
        end = source.index('        return pk->tex;', start) + len('        return pk->tex;')
        branch = source[start:end].replace('NvPkg *npk = [NvPkg new]', 'NvPkg *npk = new_pkg()')
        runner = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef struct { void *mem; struct {uint64_t size;} L; uint64_t serial;} tex_t;
typedef struct { uintptr_t lo,hi; uint64_t stamp,key,seen,hash,chash,csub; int owned,hashed; void *tex;} NvPkg;
static uint64_t g_sub_serial=1,g_pkg_uploads;
static NvPkg saved;
static unsigned char snapshot[8192];
static int change_during_upload;
#define nil NULL
#define TILELOG(...) ((void)0)
/*HASH*/
static NvPkg *new_pkg(void){memset(&saved,0,sizeof saved);return &saved;}
static int pkg_hashed(const tex_t *t){return 1;}
static int dirtycheck(void){return 0;}
static uint64_t full_hash(const void *p,uint64_t n){return pkg_hash(p,n);}
static void serial_put(uint64_t s,void *p){}
static int gpu_owned(uint64_t s){return 0;}
static int serial_is_dead(uint64_t s){return 0;}
static void dead_put_note(uint64_t s){}
static void *pkg_upload(const tex_t *t,uint64_t *stamp,uint64_t *key,NvPkg *pk){
 memcpy(snapshot,t->mem,t->L.size);*stamp=1;
 if(change_during_upload)memset(t->mem,0x7b,t->L.size);
 return snapshot;
}
static void *first(tex_t *t){NvPkg *pk;
/*BRANCH*/
}
int main(void){unsigned char bytes[8192];
 for(int size=4096;size<=8192;size+=4096)for(int change=0;change<2;change++){
  memset(bytes,0,size);change_during_upload=change;
  tex_t t={.mem=bytes,.L={size},.serial=1};first(&t);
  if(snapshot[0]!=0){fprintf(stderr,"invalid snapshot\n");return 2;}
  uint64_t current=pkg_hash(bytes,size);
  /* Next submission's existing hashed-cache predicate must reject stale data. */
  int clean=current==saved.chash;
  if(clean==change){fprintf(stderr,"size %d: changed=%d clean=%d; stale snapshot accepted\n",size,change,clean);return 1;}
 }
 puts("checks=4");return 0;
}
'''.replace('/*HASH*/', hashing).replace('/*BRANCH*/', branch)
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp)/'initial.c', Path(tmp)/'initial'
            c.write_text(runner)
            build = subprocess.run(['clang','-std=c11',str(c),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('checks=4',run.stdout)

if __name__ == '__main__': unittest.main()
