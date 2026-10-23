"""Test NVN buffer mapping and address calculation for CPU_NO_ACCESS memory pools.

Verifies:
- hle_nvn.c nvnBufferMap returns NULL when NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS is set.
- hle_nvn.c nvnBufferGetAddress returns valid GPU address (pool->mem + off) regardless of CPU_NO_ACCESS.
- Frostbite engine calculation (PlatformNvn+0x8979c..0x897bc):
    src = BufferGetAddress(buf) + dataPointer - BufferMap(buf) + offset
  Before the fix, BufferMap returned host pointer (addr) and dataPointer was 0,
  yielding addr + 0 - addr = 0 (FATAL buffer copy abort with src=0).
  With the fix, BufferMap returns NULL (0), yielding addr + 0 - 0 = addr != 0.
- BufferFlushMappedRange does not dereference NULL for CPU_NO_ACCESS buffers.
- Compiles REAL functions extracted from third_party/d2r_gfx/gfx/nvn/hle_nvn.c.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN_DIR = HERE / 'third_party/d2r_gfx/gfx/nvn'
HLE_NVN_C = NVN_DIR / 'hle_nvn.c'


def extract_nvn_fn(name: str, source_text: str) -> str:
    start = source_text.find(f'NVN({name},')
    if start == -1:
        raise AssertionError(f'Function NVN({name}, ...) not found in {HLE_NVN_C}')
    brace_start = source_text.find('{', start)
    if brace_start == -1:
        raise AssertionError(f'Opening brace not found for NVN({name}, ...)')
    depth = 0
    for i in range(brace_start, len(source_text)):
        if source_text[i] == '{':
            depth += 1
        elif source_text[i] == '}':
            depth -= 1
            if depth == 0:
                return source_text[start:i + 1]
    raise AssertionError(f'Matching closing brace not found for NVN({name}, ...)')


class NvnBufferCpuNoAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('clang not available')

        src = HLE_NVN_C.read_text(encoding='utf-8')
        cls.source_text = src

        # Extract REAL function implementations directly from hle_nvn.c
        cls.fn_init = extract_nvn_fn('nvnBufferInitialize', src)
        cls.fn_map = extract_nvn_fn('nvnBufferMap', src)
        cls.fn_addr = extract_nvn_fn('nvnBufferGetAddress', src)
        cls.fn_flush = extract_nvn_fn('nvnBufferFlushMappedRange', src)

        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmpdir.name) / 'runner'

        runner_c = f'''
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "{NVN_DIR}/nvn_obj.h"
#include "{NVN_DIR}/nvn_impl.h"

// Stubs for runtime symbols referenced by extracted functions
int runtime_core_away(void) {{ return 0; }}
void runtime_core_back(int *a) {{ (void)a; }}
static int g_guest_write_prep_called = 0;
void dm_guest_write_prepare(void *p, size_t n) {{ (void)p; (void)n; g_guest_write_prep_called++; }}
void die(const char *msg) {{ fprintf(stderr, "die: %s\\n", msg); abort(); }}

// -------------------------------------------------------------
// Real functions extracted verbatim from hle_nvn.c:
// -------------------------------------------------------------
{cls.fn_init}
{cls.fn_map}
{cls.fn_addr}
{cls.fn_flush}

// -------------------------------------------------------------
// Old implementation prior to the fix (for comparative proof):
// -------------------------------------------------------------
static void *old_nvnBufferMap(const NVNbuffer *b) {{
    const totk_buffer *v = (const void *)b;
    if (!v || v->magic != MAGIC('B','U','F',0) || !v->pool || v->pool->magic != MAGIC('P','O','O','L') || !v->pool->mem) return NULL;
    return v->pool->mem + v->off;
}}
static NVNbufferAddress old_nvnBufferGetAddress(const NVNbuffer *b) {{
    return (NVNbufferAddress)(uintptr_t)old_nvnBufferMap(b);
}}

int main(int argc, char **argv) {{
    uint8_t dummy_pool_mem[4096];
    memset(dummy_pool_mem, 0xAA, sizeof(dummy_pool_mem));

    // Pool with CPU_NO_ACCESS | GPU_CACHED (flags = 0x21, exactly as in FC 26 subresource copy)
    pool_t pool_no_access = {{
        .magic = MAGIC('P','O','O','L'),
        .flags = NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS | NVN_MEMORY_POOL_FLAGS_GPU_CACHED,
        .mem = dummy_pool_mem,
        .size = sizeof(dummy_pool_mem)
    }};

    // Normal pool with CPU access (flags = 0x20)
    pool_t pool_access = {{
        .magic = MAGIC('P','O','O','L'),
        .flags = NVN_MEMORY_POOL_FLAGS_GPU_CACHED,
        .mem = dummy_pool_mem,
        .size = sizeof(dummy_pool_mem)
    }};

    NVNbuffer buf_no_access;
    totk_buffer_builder bld_no_access = {{ .dev = NULL, .pool = &pool_no_access, .off = 0x200, .size = 0x100 }};
    assert(h_nvnBufferInitialize(&buf_no_access, (const NVNbufferBuilder *)&bld_no_access) == 1);

    NVNbuffer buf_access;
    totk_buffer_builder bld_access = {{ .dev = NULL, .pool = &pool_access, .off = 0x200, .size = 0x100 }};
    assert(h_nvnBufferInitialize(&buf_access, (const NVNbufferBuilder *)&bld_access) == 1);

    if (argc > 1 && strcmp(argv[1], "--test-old-logic") == 0) {{
        // Demonstrate old logic failure:
        // Frostbite formula: src = BufferGetAddress(buf) + dataPointer - BufferMap(buf) + offset
        // In CPU_NO_ACCESS, dataPointer is 0 (as verified in getSubresourceDataDesc, Engine.Render.Core2.PlatformNvn.nrs).
        void *map_old = old_nvnBufferMap(&buf_no_access);
        NVNbufferAddress addr_old = old_nvnBufferGetAddress(&buf_no_access);
        NVNbufferAddress frostbite_src_old = addr_old + 0 - (uintptr_t)map_old;
        printf("OLD_SRC=0x%llx\\n", (unsigned long long)frostbite_src_old);
        // Old logic produced 0, causing the FATAL abort in copy_b2b!
        return frostbite_src_old == 0 ? 0 : 1;
    }}

    // Real functions from hle_nvn.c:
    void *map_no_access = h_nvnBufferMap(&buf_no_access);
    NVNbufferAddress addr_no_access = h_nvnBufferGetAddress(&buf_no_access);

    // 1. BufferMap on CPU_NO_ACCESS pool MUST return NULL
    if (map_no_access != NULL) {{
        fprintf(stderr, "FAIL: nvnBufferMap did not return NULL for CPU_NO_ACCESS pool (returned %p)\\n", map_no_access);
        return 10;
    }}

    // 2. BufferGetAddress on CPU_NO_ACCESS pool MUST return GPU address (pool->mem + off)
    NVNbufferAddress expected_gpu_addr = (NVNbufferAddress)((uintptr_t)pool_no_access.mem + 0x200);
    if (addr_no_access != expected_gpu_addr) {{
        fprintf(stderr, "FAIL: nvnBufferGetAddress returned 0x%llx, expected 0x%llx\\n",
                (unsigned long long)addr_no_access, (unsigned long long)expected_gpu_addr);
        return 11;
    }}

    // 3. Frostbite calculation with real functions:
    // src = addr + 0 - NULL + 0 = expected_gpu_addr != 0
    NVNbufferAddress frostbite_src = addr_no_access + 0 - (uintptr_t)map_no_access;
    if (frostbite_src != expected_gpu_addr || frostbite_src == 0) {{
        fprintf(stderr, "FAIL: Frostbite calculation returned 0x%llx\\n", (unsigned long long)frostbite_src);
        return 12;
    }}

    // 4. Normal pool (CPU access allowed): BufferMap returns pointer, BufferGetAddress returns matching address
    void *map_access = h_nvnBufferMap(&buf_access);
    NVNbufferAddress addr_access = h_nvnBufferGetAddress(&buf_access);
    if (map_access != (void *)(dummy_pool_mem + 0x200)) {{
        fprintf(stderr, "FAIL: nvnBufferMap returned wrong pointer for normal pool\\n");
        return 13;
    }}
    if (addr_access != (NVNbufferAddress)(uintptr_t)map_access) {{
        fprintf(stderr, "FAIL: nvnBufferGetAddress did not match nvnBufferMap for normal pool\\n");
        return 14;
    }}

    // 5. BufferFlushMappedRange on CPU_NO_ACCESS pool:
    g_guest_write_prep_called = 0;
    h_nvnBufferFlushMappedRange(&buf_no_access, 0, 0x40);
    if (g_guest_write_prep_called != 0) {{
        fprintf(stderr, "FAIL: dm_guest_write_prepare was called for CPU_NO_ACCESS buffer\\n");
        return 15;
    }}

    // 6. BufferFlushMappedRange on normal pool:
    h_nvnBufferFlushMappedRange(&buf_access, 0, 0x40);
    if (g_guest_write_prep_called != 1) {{
        fprintf(stderr, "FAIL: dm_guest_write_prepare was not called for normal buffer\\n");
        return 16;
    }}

    printf("NEW_SRC=0x%llx\\n", (unsigned long long)frostbite_src);
    printf("PASS_REAL_FUNCTIONS\\n");
    return 0;
}}
'''
        src_path = Path(cls.tmpdir.name) / 'runner.c'
        src_path.write_text(runner_c, encoding='utf-8')
        cmd = [
            compiler,
            '-std=gnu11',
            f'-I{NVN_DIR}/include',
            str(src_path),
            '-o',
            str(cls.exe),
        ]
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            cls.tmpdir.cleanup()
            raise AssertionError(f'Runner compilation failed:\n{build.stderr}')

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_source_code_guards_in_hle_nvn(self):
        """hle_nvn.c must check CPU_NO_ACCESS in nvnBufferMap and return raw GPU address in nvnBufferGetAddress."""
        # 1. nvnBufferMap must check NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS
        self.assertIn('NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS', self.fn_map,
                      'nvnBufferMap must check NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS')
        self.assertIn('return NULL', self.fn_map,
                      'nvnBufferMap must return NULL when CPU_NO_ACCESS is set')

        # 2. nvnBufferGetAddress must NOT delegate to h_nvnBufferMap
        self.assertNotIn('h_nvnBufferMap', self.fn_addr,
                         'nvnBufferGetAddress must not delegate to h_nvnBufferMap')
        self.assertIn('(NVNbufferAddress)((uintptr_t)v->pool->mem+v->off)', self.fn_addr,
                      'nvnBufferGetAddress must return (uintptr_t)v->pool->mem+v->off')

        # 3. nvnBufferFlushMappedRange must check if mapped pointer is non-null
        self.assertIn('if(m)dm_guest_write_prepare', self.fn_flush,
                      'nvnBufferFlushMappedRange must check if mapped pointer is non-null')

    def test_old_logic_fails_and_produces_zero_address(self):
        """Demonstrate that before the fix, the old logic returned 0 for CPU_NO_ACCESS buffers."""
        res = subprocess.run([str(self.exe), '--test-old-logic'], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn('OLD_SRC=0x0', res.stdout)

    def test_real_functions_pass_and_compute_valid_gpu_address(self):
        """With the real functions from hle_nvn.c, BufferMap returns NULL and Frostbite computes valid GPU address."""
        res = subprocess.run([str(self.exe)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f'Runner failed:\n{res.stdout}\n{res.stderr}')
        self.assertIn('PASS_REAL_FUNCTIONS', res.stdout)
        self.assertIn('NEW_SRC=', res.stdout)
        self.assertNotIn('NEW_SRC=0x0', res.stdout)


if __name__ == '__main__':
    unittest.main()
