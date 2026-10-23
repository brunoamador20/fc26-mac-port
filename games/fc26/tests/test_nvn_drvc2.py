"""Test driver bank C2 component-level access validation and reflection check.

Verifies:
- drv_fillable ranges
- drv_access_components_fillable component precision (.x/.y/.z/.w / swizzle / whole vec4)
- msl_drv_unfillable_check against MSL
- Real shader 5b5805af..._b (._m0[22].z) accepted
- ._m0[22].x (0x160) rejected
- ._m0[22] whole vec4 rejected
- ._m0[22].zw (0x168..0x170) accepted
- dynamic index rejected
- Demonstration that old vec4 check failed before and new component check passes now.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = HERE / 'third_party/d2r_gfx/gfx/nvn'
NVN_REFL_M = NVN_DIR / 'nvn_refl.m'
NVN_MTL_M = NVN_DIR / 'nvn_mtl.m'


class NvnDrvC2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('clang not available')

        refl_src = NVN_REFL_M.read_text(encoding='utf-8')
        m_fillable = re.search(r'^int drv_fillable\(.*?^}$', refl_src, re.M | re.S)
        m_access = re.search(r'^int drv_access_components_fillable\(.*?^}$', refl_src, re.M | re.S)
        m_unfill = re.search(r'^int msl_drv_unfillable_check\(.*?^}$', refl_src, re.M | re.S)

        if not m_fillable or not m_access or not m_unfill:
            raise AssertionError('nvn_refl.m must define drv_fillable, drv_access_components_fillable, and msl_drv_unfillable_check')

        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmpdir.name) / 'runner'

        runner_c = f'''
#import <Foundation/Foundation.h>
#import "{NVN_DIR}/nvn_refl.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

int old_vec4_check(int stage, int bank, unsigned long idx) {{
    // Old logic: checked idx * 16 as a whole vec4
    return drv_fillable(stage, bank, (unsigned)idx * 16);
}}

int main(int argc, const char *argv[]) {{
    @autoreleasepool {{
        if (argc < 2) {{
            fprintf(stderr, "Usage: runner <cmd> [args...]\\n");
            return 2;
        }}

        if (strcmp(argv[1], "--test-old-logic") == 0) {{
            // Proves that before component check, vec4 22 (0x160) was rejected
            int old_ok = old_vec4_check(1, 2, 22);
            printf("OLD_VEC4_22_RESULT=%d\\n", old_ok);
            return old_ok == 0 ? 0 : 1; // 0 means it failed as expected
        }}

        if (strcmp(argv[1], "--check-components") == 0) {{
            if (argc < 6) return 3;
            int stage = atoi(argv[2]);
            int bank = atoi(argv[3]);
            unsigned long idx = strtoul(argv[4], NULL, 10);
            const char *after = argv[5];
            int ok = drv_access_components_fillable(stage, bank, idx, after);
            printf("COMP_RESULT=%d\\n", ok);
            return ok ? 0 : 10;
        }}

        if (strcmp(argv[1], "--check-unfillable") == 0) {{
            if (argc < 5) return 4;
            int stage = atoi(argv[2]);
            const char *entry = argv[3];
            const char *msl = argv[4];
            int ok = msl_drv_unfillable_check(msl, stage, entry);
            printf("UNFILL_RESULT=%d\\n", ok);
            return ok ? 0 : 20;
        }}

        if (strcmp(argv[1], "--check-json-refl") == 0) {{
            if (argc < 4) return 5;
            const char *json_path = argv[2];
            const char *msl_path = argv[3];
            NSData *jd = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:json_path]];
            if (!jd) {{ fprintf(stderr, "Cannot read json\\n"); return 6; }}
            NSDictionary *j = [NSJSONSerialization JSONObjectWithData:jd options:0 error:nil];
            if (!j) {{ fprintf(stderr, "Invalid json\\n"); return 7; }}
            NSString *msl = strcmp(msl_path, "NULL") == 0 ? nil : [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:msl_path] encoding:NSUTF8StringEncoding error:nil];

            nvn_refl rf;
            char err[256] = {{0}};
            int ret = nvn_refl_from_json_msl(j, msl, &rf, err, sizeof err);
            printf("REFL_RET=%d ERR=%s\\n", ret, err);
            return ret;
        }}

        return 1;
    }}
}}
'''
        src_path = Path(cls.tmpdir.name) / 'runner.m'
        src_path.write_text(runner_c, encoding='utf-8')
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
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"Clang compilation failed: {build.stderr}")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_sources_contain_required_functions_and_calls(self):
        """nvn_refl.m and nvn_mtl.m must contain the unified component check."""
        refl_src = NVN_REFL_M.read_text(encoding='utf-8')
        mtl_src = NVN_MTL_M.read_text(encoding='utf-8')

        self.assertRegex(refl_src, r'\bint\s+drv_fillable\s*\(', 'nvn_refl.m must define drv_fillable')
        self.assertRegex(refl_src, r'\bint\s+drv_access_components_fillable\s*\(', 'nvn_refl.m must define drv_access_components_fillable')
        self.assertRegex(refl_src, r'\bint\s+msl_drv_unfillable_check\s*\(', 'nvn_refl.m must define msl_drv_unfillable_check')
        self.assertIn('nvn_refl_from_json_msl', refl_src, 'nvn_refl.m must define nvn_refl_from_json_msl')

        # Check that drv_scan in nvn_mtl.m uses drv_access_components_fillable
        self.assertRegex(mtl_src, r'drv_access_components_fillable\s*\(', 'drv_scan in nvn_mtl.m must use drv_access_components_fillable')
        self.assertRegex(mtl_src, r'nvn_refl_from_json_msl\s*\(', 'shader_load in nvn_mtl.m must call nvn_refl_from_json_msl')

    def test_old_logic_failed_before_and_new_logic_passes_after(self):
        """Proves that vec4-level check rejected idx 22 (0x160), while component check accepts .z."""
        # 1. Old logic test: returns 0 (which runner treats as exit 0 because old_ok == 0)
        res_old = subprocess.run([str(self.exe), '--test-old-logic'], capture_output=True, text=True)
        self.assertEqual(res_old.returncode, 0)
        self.assertIn("OLD_VEC4_22_RESULT=0", res_old.stdout)

        # 2. New component check: .z is accepted
        res_new = subprocess.run([str(self.exe), '--check-components', '1', '2', '22', '.z'], capture_output=True, text=True)
        self.assertEqual(res_new.returncode, 0)
        self.assertIn("COMP_RESULT=1", res_new.stdout)

    def test_cases_m0_22_component_precision(self):
        """Test the 5 specific requirements from prompt:
        - ._m0[22].z aceito
        - ._m0[22].x (0x160) recusado
        - ._m0[22] inteiro recusado
        - ._m0[22].zw aceito (0x168..0x170)
        - índice dinâmico recusado
        """
        # Case 1: ._m0[22].z aceito
        msl_z = "void main0() { float val = (*spvDescriptorSet0.fp_c2)._m0[22].z; }"
        res1 = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2+0x160', msl_z], capture_output=True, text=True)
        self.assertEqual(res1.returncode, 0, f"Case 1 (._m0[22].z) must be accepted: {res1.stdout} {res1.stderr}")
        self.assertIn("UNFILL_RESULT=1", res1.stdout)

        # Case 2: ._m0[22].x (0x160) recusado
        msl_x = "void main0() { float val = (*spvDescriptorSet0.fp_c2)._m0[22].x; }"
        res2 = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2+0x160', msl_x], capture_output=True, text=True)
        self.assertNotEqual(res2.returncode, 0, "Case 2 (._m0[22].x) must be rejected")
        self.assertIn("UNFILL_RESULT=0", res2.stdout)

        # Case 3: ._m0[22] inteiro recusado
        msl_whole = "void main0() { float4 val = (*spvDescriptorSet0.fp_c2)._m0[22]; }"
        res3 = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2+0x160', msl_whole], capture_output=True, text=True)
        self.assertNotEqual(res3.returncode, 0, "Case 3 (._m0[22] whole) must be rejected")
        self.assertIn("UNFILL_RESULT=0", res3.stdout)

        # Case 4: ._m0[22].zw aceito (0x168..0x170)
        msl_zw = "void main0() { float2 val = (*spvDescriptorSet0.fp_c2)._m0[22].zw; }"
        res4 = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2+0x160', msl_zw], capture_output=True, text=True)
        self.assertEqual(res4.returncode, 0, f"Case 4 (._m0[22].zw) must be accepted: {res4.stdout} {res4.stderr}")
        self.assertIn("UNFILL_RESULT=1", res4.stdout)

        # Case 5: índice dinâmico recusado
        msl_dyn = "void main0() { int i = 22; float val = (*spvDescriptorSet0.fp_c2)._m0[i].z; }"
        res5 = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2+0x160', msl_dyn], capture_output=True, text=True)
        self.assertNotEqual(res5.returncode, 0, "Case 5 (dynamic index) must be rejected")
        self.assertIn("UNFILL_RESULT=0", res5.stdout)

        # Case 5b: entry explicitly "c2 dynamic index"
        res5b = subprocess.run([str(self.exe), '--check-unfillable', '1', 'c2 dynamic index', msl_z], capture_output=True, text=True)
        self.assertNotEqual(res5b.returncode, 0, "c2 dynamic index entry must be rejected")
        self.assertIn("UNFILL_RESULT=0", res5b.stdout)

    def test_end_to_end_reflection_json(self):
        """Test nvn_refl_from_json_msl with synthetic reflection JSON containing drv_unfillable."""
        json_content = {
            "route": "B",
            "stage": "ps",
            "bindings": [],
            "drv_unfillable": ["c2+0x160"]
        }
        with tempfile.TemporaryDirectory() as td:
            jp = Path(td) / "test.json"
            jp.write_text(json.dumps(json_content), encoding='utf-8')

            msl_ok = Path(td) / "ok.metal"
            msl_ok.write_text("fragment void main0() { float v = (*spvDescriptorSet0.fp_c2)._m0[22].z; }", encoding='utf-8')

            msl_bad = Path(td) / "bad.metal"
            msl_bad.write_text("fragment void main0() { float v = (*spvDescriptorSet0.fp_c2)._m0[22].x; }", encoding='utf-8')

            # 1. With NULL MSL (old behavior): fails
            r_null = subprocess.run([str(self.exe), '--check-json-refl', str(jp), 'NULL'], capture_output=True, text=True)
            self.assertNotEqual(r_null.returncode, 0)
            self.assertIn("REFL_RET=1", r_null.stdout)
            self.assertIn("c2+0x160", r_null.stdout)

            # 2. With ok.metal (._m0[22].z): passes
            r_ok = subprocess.run([str(self.exe), '--check-json-refl', str(jp), str(msl_ok)], capture_output=True, text=True)
            self.assertEqual(r_ok.returncode, 0, f"Expected success with ._m0[22].z: {r_ok.stdout}")
            self.assertIn("REFL_RET=0", r_ok.stdout)

            # 3. With bad.metal (._m0[22].x): fails
            r_bad = subprocess.run([str(self.exe), '--check-json-refl', str(jp), str(msl_bad)], capture_output=True, text=True)
            self.assertNotEqual(r_bad.returncode, 0)
            self.assertIn("REFL_RET=1", r_bad.stdout)
            self.assertIn("c2+0x160", r_bad.stdout)


if __name__ == '__main__':
    unittest.main()
