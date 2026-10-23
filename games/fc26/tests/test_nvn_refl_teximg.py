"""Test shader reflection for tcb image queries (NVN_RB_TEXIMG) and handle validation.
"""
from pathlib import Path
import json
import re
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = HERE / 'third_party/d2r_gfx/gfx/nvn'


class NvnReflTexImgTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('clang not available')

        mtl = (NVN_DIR / 'nvn_mtl.m').read_text(encoding='utf-8')
        beyond = re.search(r'^static int msl_tex_uses_beyond_size\(.*?^}$', mtl, re.M | re.S)
        if beyond is None:
            raise AssertionError('nvn_mtl.m must define msl_tex_uses_beyond_size')
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmpdir.name) / 'runner'

        src = f'''
#import <Foundation/Foundation.h>
#import "{NVN_DIR}/nvn_refl.h"
#import "{NVN_DIR}/nvn_texture_plan.h"
#include <stdio.h>
#include <string.h>

@@BEYOND@@

int main(int argc, const char *argv[]) {{
    @autoreleasepool {{
        if (argc >= 4 && strcmp(argv[1], "--check-msl") == 0) {{
            NSString *msl = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[2]] encoding:NSUTF8StringEncoding error:nil];
            if (!msl) {{
                fprintf(stderr, "Cannot read MSL file: %s\\n", argv[2]);
                return 5;
            }}
            NSString *name = [NSString stringWithUTF8String:argv[3]];
            if (msl_tex_uses_beyond_size(msl, name)) {{
                fprintf(stderr, "FAIL: tex sobre imagem com uso além de tamanho (%s)\\n", argv[3]);
                return 20;
            }}
            printf("OK: query size only (%s)\\n", argv[3]);
            return 0;
        }}
        if (argc < 2) {{
            fprintf(stderr, "Usage: runner <json_path>\\n");
            return 2;
        }}
        NSData *data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
        if (!data) {{
            fprintf(stderr, "Cannot read file: %s\\n", argv[1]);
            return 3;
        }}
        NSError *err = nil;
        NSDictionary *j = [NSJSONSerialization JSONObjectWithData:data options:0 error:&err];
        if (!j) {{
            fprintf(stderr, "JSON error: %s\\n", err.localizedDescription.UTF8String);
            return 4;
        }}
        nvn_refl rf;
        char msg[256] = {{0}};
        int ret = nvn_refl_from_json(j, &rf, msg, sizeof(msg));
        if (ret != 0) {{
            fprintf(stderr, "FAIL: %s\\n", msg);
            return 10;
        }}
        // Print parsed bindings: kind and reg
        for (int i = 0; i < rf.nb; i++) {{
            printf("BINDING %d: kind=%d reg=%d aid=%d\\n", i, rf.b[i].kind, rf.b[i].reg, rf.b[i].aid);
        }}
        uint16_t plan_slots[NVN_REFL_MAXB] = {{0}};
        unsigned nplans = nvn_texture_plan(&rf, plan_slots);
        for (unsigned i = 0; i < nplans; i++) {{
            printf("PLAN %u: slot=%u\\n", i, plan_slots[i]);
        }}
        return 0;
    }}
}}
'''
        src = src.replace('@@BEYOND@@', beyond.group(0))
        src_path = Path(cls.tmpdir.name) / 'runner.m'
        src_path.write_text(src, encoding='utf-8')
        cmd = [
            compiler,
            '-std=c11',
            '-fobjc-arc',
            '-framework', 'Foundation',
            '-framework', 'Metal',
            f'-I{NVN_DIR}',
            str(NVN_DIR / 'nvn_refl.m'),
            str(src_path),
            '-o', str(cls.exe),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cls.tmpdir.cleanup()
            raise AssertionError(f"Compilation failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def run_synthetic(self, bindings):
        refl = {
            "key": "test_synthetic",
            "route": "B",
            "chain": "totk-native-v4-unverified",
            "stage": "cs",
            "entry": "main0",
            "bindings": bindings,
        }
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(refl, f)
            path = f.name
        try:
            res = subprocess.run([str(self.exe), path], capture_output=True, text=True)
            return res.returncode, res.stdout, res.stderr
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_cp_t_tcb_48_resolves_teximg_slot_0(self):
        """Synthetic reflection matching 3d6e... with reg: null must resolve to NVN_RB_TEXIMG slot 0."""
        bindings = [
            {"msl_name": "support_buffer", "msl_type": "constant _10*", "arg_id": 0, "kind": "support"},
            {"msl_name": "cp_c1", "msl_type": "constant _16*", "arg_id": 1, "kind": "c1", "bank": 1},
            {"msl_name": "cp_c3", "msl_type": "constant _16*", "arg_id": 2, "kind": "cbuf", "reg": 0},
            {"msl_name": "cp_t_tcb_48", "msl_type": "texture2d<float>", "arg_id": 3, "kind": "tex", "reg": None},
            {"msl_name": "cp_t_tcb_48Smplr", "msl_type": "sampler", "arg_id": 4, "kind": "samp_tex", "reg": None},
            {"msl_name": "cp_i_cb2_48_", "msl_type": "texture2d_array<float, access::write>", "arg_id": 5, "kind": "img", "reg": 0},
        ]
        code, out, err = self.run_synthetic(bindings)
        self.assertEqual(code, 0, f"Expected success but got:\nSTDOUT: {out}\nSTDERR: {err}")
        # Binding 3: kind=NVN_RB_TEXIMG (14), reg=0
        self.assertIn("BINDING 3: kind=14 reg=0", out)
        # Binding 4: kind=NVN_RB_SAMPT (11), reg=0xffff (empty-slot sampler)
        self.assertIn("BINDING 4: kind=11 reg=65535", out)
        # Texture plan must include image slot 0 as 128 + 0 = 128
        self.assertIn("PLAN 0: slot=128", out)

    def test_handle_boundaries_and_out_of_range(self):
        """[ImgBase, TexBase) = [0x48, 0x5a): 0x48 and 0x58 pass; 0x46, 0x5a, and odd 0x49 must FAIL."""
        # Valid boundary hi: handle 0x58 -> slot (0x58 - 0x48) / 2 = 8
        bindings_58 = [
            {"msl_name": "cp_t_tcb_58", "msl_type": "texture2d<float>", "arg_id": 0, "kind": "tex", "reg": None},
            {"msl_name": "cp_t_tcb_58Smplr", "msl_type": "sampler", "arg_id": 1, "kind": "samp_tex", "reg": None},
        ]
        code, out, err = self.run_synthetic(bindings_58)
        self.assertEqual(code, 0, f"Handle 0x58 must succeed: {out} {err}")
        self.assertIn("BINDING 0: kind=14 reg=8", out)
        self.assertIn("BINDING 1: kind=11 reg=65535", out)

        # Out of range: handle 0x5a (= TexBase = 0x168 / 4) -> must FAIL
        bindings_5a = [
            {"msl_name": "cp_t_tcb_5a", "msl_type": "texture2d<float>", "arg_id": 0, "kind": "tex", "reg": None},
        ]
        code, out, err = self.run_synthetic(bindings_5a)
        self.assertNotEqual(code, 0, "Handle 0x5a is TexBase, out of image range, must fail")
        self.assertIn("没解出槽号", err)

        # Out of range: handle 0x46 (< ImgBase = 0x120 / 4 = 0x48) -> must FAIL
        bindings_46 = [
            {"msl_name": "cp_t_tcb_46", "msl_type": "texture2d<float>", "arg_id": 0, "kind": "tex", "reg": None},
        ]
        code, out, err = self.run_synthetic(bindings_46)
        self.assertNotEqual(code, 0, "Handle 0x46 < 0x48 must fail")
        self.assertIn("没解出槽号", err)

        # Unaligned: handle 0x49 (odd word) -> must FAIL
        bindings_49 = [
            {"msl_name": "cp_t_tcb_49", "msl_type": "texture2d<float>", "arg_id": 0, "kind": "tex", "reg": None},
        ]
        code, out, err = self.run_synthetic(bindings_49)
        self.assertNotEqual(code, 0, "Handle 0x49 is not aligned to 2 words, must fail")
        self.assertIn("没解出槽号", err)

        # Malformed name -> must FAIL
        for bad in ["cp_t_tcb_xyz", "cp_t_tcb_4", "cp_t_tcb_108", "foo_bad_tcb_48"]:
            code, _, err = self.run_synthetic([
                {"msl_name": bad, "msl_type": "texture2d<float>", "arg_id": 0, "kind": "tex", "reg": None}
            ])
            self.assertNotEqual(code, 0, f"{bad} must fail")
            self.assertIn("没解出槽号", err)

    def test_msl_usage_beyond_size_fails(self):
        """MSL querying only size passes; sampling or reading on tex-over-image must fail."""
        size_only_msl = '''
kernel void main0(constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]]) {
    int w = spvDescriptorSet0.cp_t_tcb_48.get_width();
    int h = spvDescriptorSet0.cp_t_tcb_48.get_height();
}
'''
        with tempfile.NamedTemporaryFile('w', suffix='.metal', delete=False) as f:
            f.write(size_only_msl)
            path = f.name
        try:
            res = subprocess.run([str(self.exe), '--check-msl', path, 'cp_t_tcb_48'], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Expected size-only MSL to pass: {res.stdout} {res.stderr}")
        finally:
            os.unlink(path)

        sample_msl = '''
kernel void main0(constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]]) {
    float4 c = spvDescriptorSet0.cp_t_tcb_48.sample(spvDescriptorSet0.cp_t_tcb_48Smplr, float2(0.5, 0.5));
}
'''
        with tempfile.NamedTemporaryFile('w', suffix='.metal', delete=False) as f:
            f.write(sample_msl)
            path = f.name
        try:
            res = subprocess.run([str(self.exe), '--check-msl', path, 'cp_t_tcb_48'], capture_output=True, text=True)
            self.assertEqual(res.returncode, 20, "Expected sampling MSL to fail")
            self.assertIn("tex sobre imagem com uso além de tamanho", res.stderr)
        finally:
            os.unlink(path)

        read_msl = '''
kernel void main0(constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]]) {
    float4 c = spvDescriptorSet0.cp_t_tcb_48.read(uint2(0, 0));
}
'''
        with tempfile.NamedTemporaryFile('w', suffix='.metal', delete=False) as f:
            f.write(read_msl)
            path = f.name
        try:
            res = subprocess.run([str(self.exe), '--check-msl', path, 'cp_t_tcb_48'], capture_output=True, text=True)
            self.assertEqual(res.returncode, 20, "Expected reading MSL to fail")
            self.assertIn("tex sobre imagem com uso além de tamanho", res.stderr)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
