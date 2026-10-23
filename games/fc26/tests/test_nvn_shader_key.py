"""The shader key in its three places: nvn_mtl.m prog_get (ctl_key_len + ctl_key_update, compiled here from the source
with CommonCrypto), runtime/shader_cache.c fc26_sc_shader_key (the journal) and scripts/shader_seed.py shader_key (the
offline seed). They must agree byte for byte, and all three leave control+0x7d0..+0x7e7 out: the game binds the control
section of another record that differs from the shader's own only there (docs/SHADER_SEED.md). Synthetic shaders only."""
from pathlib import Path
import platform
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import shader_seed  # noqa: E402

CONTROL_LEN = 0x880


def make_shader(seed, code_len=0x200, key_len_word=0):
    rnd = random.Random(seed)
    control = bytearray(rnd.randbytes(CONTROL_LEN))
    struct.pack_into('<I', control, 0x20, key_len_word)
    struct.pack_into('<II', control, 0x700, 0x100, code_len)
    struct.pack_into('<I', control, 0x714, 1)
    return control, rnd.randbytes(code_len + 32)


class NvnShaderKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if platform.system() != 'Darwin' or not compiler:
            raise unittest.SkipTest('nvn_mtl.m hashes with CommonCrypto: macOS and clang')
        mtl = (HERE / 'third_party/d2r_gfx/gfx/nvn/nvn_mtl.m').read_text(encoding='utf-8')
        parts = [re.search(r'^static inline uint32_t ctl_key_len\(.*$', mtl, re.M),
                 re.search(r'^#define CTL_KEY_SKIP_LO .*$', mtl, re.M), re.search(r'^#define CTL_KEY_SKIP_HI .*$', mtl, re.M),
                 re.search(r'^static void ctl_key_update\(.*?^}$', mtl, re.M | re.S)]
        if not all(parts):
            raise AssertionError('nvn_mtl.m must define ctl_key_len, CTL_KEY_SKIP_LO/HI and ctl_key_update')
        # prog_get's key is ctl_key_update over the control section, then the code's first u32@+0x704 bytes
        if not re.search(r'CC_SHA256_Init\(&ctx\);\s*ctl_key_update\(&ctx,\s*control\);\s*'
                         r'CC_SHA256_Update\(&ctx,\s*\(const void \*\)\(uintptr_t\)p->sd\[i\]\.data,\s*length\);', mtl):
            raise AssertionError('nvn_mtl.m prog_get no longer keys a shader with ctl_key_update + the code')
        cls.build = tempfile.TemporaryDirectory()
        src = Path(cls.build.name) / 'key.c'
        src.write_text('#include <CommonCrypto/CommonDigest.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n'
                       '#include "shader_cache.h"\n' + '\n'.join(m.group(0) for m in parts) + r'''
static unsigned char *load(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb"); if (!f) exit(2);
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *p = malloc((size_t)len + 1); if (fread(p, 1, (size_t)len, f) != (size_t)len) exit(2);
    fclose(f); *n = (size_t)len; return p;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    size_t nc, nd; unsigned char *control = load(argv[1], &nc), *code = load(argv[2], &nd), md[32];
    uint32_t length; memcpy(&length, control + 0x704, 4);
    CC_SHA256_CTX ctx; CC_SHA256_Init(&ctx); ctl_key_update(&ctx, control);
    CC_SHA256_Update(&ctx, code, length); CC_SHA256_Final(md, &ctx);
    for (int i = 0; i < 32; i++) printf("%02x", md[i]);
    char key[65]; printf(" %s\n", fc26_sc_shader_key(control, code, key) ? "invalid" : key);
    return 0;
}
''')
        cls.exe = Path(cls.build.name) / 'key'
        run = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                              f'-I{HERE / "runtime"}', str(src), str(HERE / 'runtime/shader_cache.c'), '-o', str(cls.exe)],
                             capture_output=True, text=True)
        if run.returncode:
            cls.build.cleanup()
            raise AssertionError(run.stdout + run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def keys(self, control, code):
        d = Path(self.build.name)
        (d / 'c').write_bytes(bytes(control)); (d / 'k').write_bytes(code)
        run = subprocess.run([str(self.exe), str(d / 'c'), str(d / 'k')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        mtl, journal = run.stdout.split()
        return mtl, journal, shader_seed.shader_key(bytes(control), code)

    def test_three_places_agree(self):
        for i, word in enumerate([0, 0x7cc, 0x7d1, 0x7e8, 0x7e9, 0x848, 0x880, 0x900]):
            control, code = make_shader(i, key_len_word=word)
            with self.subTest(word=hex(word)):
                mtl, journal, seed = self.keys(control, code)
                self.assertEqual(mtl, journal)
                self.assertEqual(mtl, seed)

    def test_record_identifier_is_left_out_everywhere(self):
        control, code = make_shader(20)
        base = self.keys(control, code)
        self.assertEqual(len(set(base)), 1)
        twin = bytearray(control); twin[0x7d0:0x7e8] = bytes(0x18)   # another record of the same shader
        self.assertEqual(self.keys(twin, code), base)
        for at in (0x7cf, 0x7e8, 0x714, 0x0):                          # everything else around it still counts
            other = bytearray(control); other[at] ^= 1
            with self.subTest(at=hex(at)):
                self.assertNotEqual(self.keys(other, code)[0], base[0])


if __name__ == '__main__':
    unittest.main()
