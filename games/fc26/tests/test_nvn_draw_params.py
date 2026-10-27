"""Draw parameters in the NVN driver segment c0 (base vertex / base instance / draw index at 0x640 / 0x644 / 0x648).

The base game aborted entering "Encontro Clássico" (logs/boot_base2a.log): vertex shader 3d1d0a08..._b computes its
instance as instance_id - base_instance + c0[0x644] (`vp_c0)._m0[100].y`), the translator marked c0+0x640 unfillable and
the runtime refused the reflection ("运行时读驱动段的回放层填不了的位置：c0+0x640"). vendor/ryujinx Constants.cs gives
the offsets (NvnBaseVertexByteOffset 0x640, NvnBaseInstanceByteOffset 0x644, NvnDrawIndexByteOffset 0x648).

Compiles the real nvn_refl.m and the real driver_bank_fill cut out of nvn_mtl.m. FC26_NVN_DIR points the test at another
copy of the nvn sources (e.g. the previous commit, to see it fail).
"""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = Path(os.environ.get('FC26_NVN_DIR') or HERE / 'third_party/d2r_gfx/gfx/nvn')
RYU_CONSTANTS = HERE / 'vendor/ryujinx/src/Ryujinx.Graphics.Shader/Constants.cs'

# Line 83 of the shader that aborted, with its reflection (the translator's JSON, bindings left out).
REAL_MSL = '''vertex main0_out main0(main0_in in [[stage_in]], constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]], uint gl_InstanceIndex [[instance_id]], uint gl_BaseInstance [[base_instance]])
{
    float _65 = as_type<float>(int(gl_InstanceIndex));
    float _67 = as_type<float>(int(gl_BaseInstance));
    int _69 = as_type<int>(_65) - as_type<int>(_67);
    int _71 = _69 + as_type<int>((*spvDescriptorSet0.vp_c0)._m0[100].y);
}
'''
REAL_JSON = {'route': 'B', 'stage': 'vs', 'bindings': [], 'drv_reads': {'0': {'vec4_offsets': [1600], 'dynamic': False}},
             'drv_unfillable': ['c0+0x640']}


def _cut(src, pattern, what):
    m = re.search(pattern, src, re.M | re.S)
    if not m:
        raise AssertionError(f'{what} not found in nvn_mtl.m')
    return m.group(0)


class NvnDrawParamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('clang not available')
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)

        refl_runner = t / 'refl.m'
        refl_runner.write_text(f'''
#import <Foundation/Foundation.h>
#import "{NVN_DIR}/nvn_refl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, const char **argv) {{ @autoreleasepool {{
    if (!strcmp(argv[1], "fillable")) {{ int ok = drv_fillable(atoi(argv[2]), atoi(argv[3]), (unsigned)strtoul(argv[4], NULL, 0)); printf("FILL=%d\\n", ok); return 0; }}
    NSDictionary *j = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:nil];
    NSString *msl = [NSString stringWithContentsOfFile:@(argv[3]) encoding:NSUTF8StringEncoding error:nil];
    nvn_refl rf; char err[256] = {{0}};
    int ret = nvn_refl_from_json_msl(j, msl, &rf, err, sizeof err);
    printf("REFL_RET=%d ERR=%s\\n", ret, err); return 0;
}} }}
''', encoding='utf-8')
        cls.refl = t / 'refl'
        b = subprocess.run([cc, '-std=c11', '-fobjc-arc', '-framework', 'Foundation', '-framework', 'Metal', f'-I{NVN_DIR}',
                            str(NVN_DIR / 'nvn_refl.m'), str(refl_runner), '-o', str(cls.refl)], capture_output=True, text=True)
        if b.returncode:
            raise AssertionError('nvn_refl.m runner build failed: ' + b.stderr)

        mtl = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        fill = _cut(mtl, r'^static void driver_bank_fill\(uint8_t \*d, int bank, int stage\) \{.*?^\}$', 'driver_bank_fill')
        params = re.search(r'^static int32_t g_draw_params\[3\];$', mtl, re.M)
        fill_runner = t / 'fill.c'
        fill_runner.write_text(f'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct {{ int32_t stage, index; uint64_t addr, size; }} p_bind_buf;
static struct {{ p_bind_buf ssbo[6][16], ubo[6][16]; uint64_t tex[6][128], samp[6][128]; }} S;
static int g_red_once[64];
#define RED_ONCE(k, ...) do {{ g_red_once[k]++; }} while (0)
static uint32_t g_dispatch_grid[3];
{params.group(0) if params else 'static int32_t g_draw_params[3];   /* not in this nvn_mtl.m: driver_bank_fill cannot read it */'}
{fill}
int main(void) {{
    static uint8_t d[0xA00];
    g_draw_params[0] = 7; g_draw_params[1] = 300; g_draw_params[2] = 0;
    driver_bank_fill(d, 0, 0);
    int32_t got[3]; memcpy(got, d + 0x640, sizeof got);
    float ps; memcpy(&ps, d + 0x610, 4);
    printf("VS=%d,%d,%d PS_MAX=%g\\n", got[0], got[1], got[2], ps);
    driver_bank_fill(d, 0, 1); memcpy(got, d + 0x640, sizeof got);
    printf("FS=%d,%d,%d\\n", got[0], got[1], got[2]);
    return 0;
}}
''', encoding='utf-8')
        cls.fill = t / 'fill'
        b = subprocess.run([cc, '-std=c11', '-w', str(fill_runner), '-o', str(cls.fill)], capture_output=True, text=True)
        if b.returncode:
            raise AssertionError('driver_bank_fill runner build failed: ' + b.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_refl(self, msl, js=REAL_JSON):
        t = Path(self.tmp.name)
        (t / 'r.json').write_text(json.dumps(js), encoding='utf-8')
        (t / 'r.metal').write_text(msl, encoding='utf-8')
        return subprocess.run([str(self.refl), 'refl', str(t / 'r.json'), str(t / 'r.metal')], capture_output=True, text=True).stdout

    def fillable(self, stage, bank, off):
        out = subprocess.run([str(self.refl), 'fillable', str(stage), str(bank), hex(off)], capture_output=True, text=True).stdout
        return out.strip() == 'FILL=1'

    def test_offsets_match_ryujinx(self):
        if not RYU_CONSTANTS.exists():
            self.skipTest('vendor/ryujinx not present')
        src = RYU_CONSTANTS.read_text(encoding='utf-8')
        self.assertIn('NvnBaseVertexByteOffset = 0x640', src)
        self.assertIn('NvnBaseInstanceByteOffset = 0x644', src)
        self.assertIn('NvnDrawIndexByteOffset = 0x648', src)

    def test_real_shader_reflection_accepted(self):
        out = self.run_refl(REAL_MSL)
        self.assertIn('REFL_RET=0', out, out)

    def test_vertex_draw_parameter_words_fillable(self):
        for off in (0x640, 0x644, 0x648):
            self.assertTrue(self.fillable(0, 0, off), hex(off))
        self.assertFalse(self.fillable(0, 0, 0x64c))   # .w of the vec4 stays unfilled
        self.assertFalse(self.fillable(1, 0, 0x644))   # fragment shaders: not a draw-parameter word
        out = self.run_refl(REAL_MSL.replace('_m0[100].y', '_m0[100].w'))
        self.assertIn('REFL_RET=1', out)
        self.assertIn('c0+0x640', out)

    def test_driver_bank_fill_writes_draw_parameters(self):
        out = subprocess.run([str(self.fill)], capture_output=True, text=True).stdout
        self.assertIn('VS=7,300,0 PS_MAX=2047.94', out)
        self.assertIn('FS=0,0,0', out)


if __name__ == '__main__':
    unittest.main()
