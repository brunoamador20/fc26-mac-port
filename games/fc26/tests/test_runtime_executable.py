"""Compile the actual path functions, without linking Metal or opening a window."""
from pathlib import Path
import os
import platform
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system() == 'Darwin', 'macOS')
class RuntimeExecutable(unittest.TestCase):
    def test_real_shader_paths_and_unchanged_fallback(self):
        for relative, function in (
            ('runtime/shader_cache_mac.m', 'root_dir'),
            ('third_party/d2r_gfx/gfx/nvn/totk_shader_rt.m', 'root_dir'),
            ('third_party/d2r_gfx/gfx/nvn/nvn_mtl.m', 'exe_rel'),
        ):
            with self.subTest(source=relative), tempfile.TemporaryDirectory() as tmp:
                source = (ROOT / relative).read_text()
                start = source.index('static NSString *' + function + '(')
                end = source.index('\n}', start) + 2
                # The function body is taken verbatim from the production source.
                header = ROOT / 'third_party/d2r_gfx/gfx/nvn/runtime_executable.h'
                code = '#import <Foundation/Foundation.h>\n#include <libgen.h>\n#include <limits.h>\n#include <mach-o/dyld.h>\n'
                if header.exists():
                    code += f'#include "{header}"\n'
                code += '#define die(...) abort()\nstatic NSString *g_root;\n' + source[start:end]
                call = 'exe_rel("shader-libs")' if function == 'exe_rel' else 'root_dir()'
                code += f'\nint main(void) {{ @autoreleasepool {{ puts([{call} UTF8String]); }} }}\n'
                src, exe = Path(tmp)/'probe.m', Path(tmp)/'probe'
                src.write_text(code)
                subprocess.run(['xcrun','clang','-fobjc-arc',str(src),'-framework','Foundation','-o',str(exe)],check=True,capture_output=True)
                env = dict(os.environ)
                env.pop('FC26_RUNTIME_EXECUTABLE', None)
                expected_plain = str(exe.parent/'shader-libs') if function == 'exe_rel' else str(exe.parent.parent)
                self.assertEqual(subprocess.check_output([str(exe)],env=env,text=True).strip(),expected_plain)
                env['FC26_RUNTIME_EXECUTABLE'] = '/test/work/build-modojogo/fc26-native'
                expected = '/test/work/build-modojogo/shader-libs' if function == 'exe_rel' else '/test/work'
                self.assertEqual(subprocess.check_output([str(exe)],env=env,text=True).strip(),expected)
