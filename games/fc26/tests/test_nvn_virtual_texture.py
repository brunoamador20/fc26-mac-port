"""Compila a decisão real de importação dos materiais em pools virtuais (0x221).

Sem dados do jogo. FC26_NVN_DIR permite testar a revisão anterior.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import tempfile
import unittest

NVN = Path(os.environ.get('FC26_NVN_DIR') or Path(__file__).resolve().parents[1] / 'third_party/d2r_gfx/gfx/nvn')

@unittest.skipUnless(platform.system() == 'Darwin', 'requer clang do macOS')
class VirtualTextureTest(unittest.TestCase):
    def test_virtual_materials_import_pool_contents(self):
        src = (NVN / 'nvn_mtl.m').read_text()
        # O caminho real de upload protege páginas apenas quando não usa hash.
        self.assertIn('if (!pkg_hashed(t)) nvn_dirty_protect(t->mem, t->L.size);', src)
        funcs = []
        for pat in [r'^static int fmt_compressed\(.*?\n', r'^static uint64_t pkg_hash\(const void \*p, uint64_t n\) \{.*?\n}\n', r'^static int pkg_hashed\(const tex_t \*t\) \{.*?\n}\n', r'^static int tex_mirrored\(const tex_t \*t\) \{.*?\n}\n']:
            m = re.search(pat, src, re.M | re.S)
            self.assertIsNotNone(m)
            funcs.append(m.group())
        harness = '''#include <stdio.h>
#include <stdlib.h>
#include "nvn_obj.h"
#define PKG_HASH_MAX (4u << 10)
''' + '\n'.join(funcs) + '''
int main(void) {
 uint8_t bytes[4096]={1}; pool_t p={0};p.flags=0x221;p.mem=bytes;p.host=bytes;
 tex_t t={0};t.mem=bytes;t.pool=&p;t.d.target=1;t.d.samples=1;t.L.size=65536;
 for(int fmt=0x41;fmt<=0x50;fmt++) {t.d.format=fmt;printf("virtual_bc_%x=%d\\n",fmt,tex_mirrored(&t));}
 printf("virtual_hash=%d\\n",pkg_hashed(&t));
 t.d.format=0x25;printf("virtual_rgba=%d\\n",tex_mirrored(&t));
 t.d.format=0x38;printf("virtual_srgba=%d\\n",tex_mirrored(&t));printf("virtual_srgba_hash=%d\\n",pkg_hashed(&t));
 t.d.format=0x46;t.d.flags=NVN_TEXTURE_FLAGS_DISPLAY;printf("display=%d\\n",tex_mirrored(&t));
 t.d.flags=NVN_TEXTURE_FLAGS_COMPRESSIBLE;printf("compressible=%d\\n",tex_mirrored(&t));
 t.d.flags=0;t.d.format=0x36;printf("depth=%d\\n",tex_mirrored(&t));
 t.d.format=0x38;t.d.target=10;printf("buffer=%d\\n",tex_mirrored(&t));
 t.d.target=1;t.d.samples=4;printf("msaa=%d\\n",tex_mirrored(&t));
 t.d.samples=1;p.flags=0x121;printf("physical_hash=%d\\n",pkg_hashed(&t));printf("physical=%d\\n",tex_mirrored(&t));
 p.flags=NVN_MEMORY_POOL_FLAGS_CPU_CACHED;p.host=NULL;printf("cpu=%d\\n",tex_mirrored(&t));
 t.mem=NULL;printf("no_storage=%d\\n",tex_mirrored(&t));
 uint64_t h=pkg_hash(bytes,sizeof bytes);bytes[200]=7;printf("changed=%d\\n", h!=pkg_hash(bytes,sizeof bytes));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / 'h.c').write_text(harness)
            r = subprocess.run(['clang', '-std=c11', '-Werror', f'-I{NVN}', f'-I{NVN / "include"}', str(p / 'h.c'), '-o', str(p / 'h')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(p / 'h')], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            for fmt in range(0x41, 0x51):
                with self.subTest(format=fmt):
                    self.assertIn(f'virtual_bc_{fmt:x}=1', r.stdout)
            for name in ['physical', 'display', 'compressible', 'depth', 'buffer', 'msaa', 'no_storage']:
                self.assertIn(f'{name}=0', r.stdout)
            self.assertIn('virtual_rgba=1', r.stdout)
            self.assertIn('virtual_srgba=1', r.stdout)
            self.assertIn('virtual_srgba_hash=1', r.stdout)
            self.assertIn('cpu=1', r.stdout)
            self.assertIn('virtual_hash=1', r.stdout)
            self.assertIn('physical_hash=0', r.stdout)
            self.assertIn('changed=1', r.stdout)
