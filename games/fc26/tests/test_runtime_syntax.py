"""The runtime sources compile (syntax and types, -Wall -Wextra -Werror as the Makefile builds them) before any game data
exists: the three headers make prepare would generate are replaced by small stand-ins.
On the Mac every runtime source is checked with xcrun clang (Homebrew's opus and libvpx headers as in the Makefile).
Elsewhere (the Linux cloud) only the sources that use no macOS header can be checked; PORTABLE lists them, and a
change that makes one of them depend on macOS fails here."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import game_config  # noqa: E402
PORTABLE = ['applet_host.c', 'audio_effects.c', 'audio_reverb.c', 'autoload.c', 'gfx_probe.c', 'hid_feedback.c', 'hle_stack.c',
            'input.c', 'ipc.c', 'missing.c', 'motion_fusion.c', 'system_services.c', 'world_survey.c']
STAND_INS = {
    'runtime_tables.h': '''static const Reloc reloc_0[] = {{0ULL,1027,0,0LL},};
static const Symbol symbol_0[] = {{"",0ULL,0ULL,0,0,0},};
static const Gate gate_0[] = {{0,0,0,0},};
static Module modules[] = {''' + ','.join(f'{{.name="{m}",.digest="",.symbols=symbol_0,.nsym=1,.relocs=reloc_0,.nreloc=1,.gates=gate_0,.ngate=1}}'
                            for m in game_config.MODULES) + '''};
#define PROBE_PLT 0ULL
#define PROBE_SLOT 0ULL
''',
    'romfs_config.h': '#define ROMFS_IMAGE_SIZE 1ULL\n#define ROMFS_IMAGE_SHA256 ""\n#define ROMFS_INDEX_SHA256 ""\n',
    'shared_fonts_config.h': '#define SHARED_FONT_COUNT 6\n#define SHARED_FONT_ROWS ' + ','.join(['{"",0ULL,0ULL,""}'] * 6) + '\n',
}


class RuntimeSyntax(unittest.TestCase):
    def check(self, compiler, sources, extra):
        with tempfile.TemporaryDirectory() as gen:
            for name, text in STAND_INS.items():
                (Path(gen) / name).write_text(text)
            failures = []
            for source in sources:
                flags = ['-std=c11', '-fsyntax-only', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                         f'-I{HERE / "third_party/d2r_gfx/gfx/nvn/include"}', f'-I{gen}', *extra]
                if source.suffix == '.m':
                    flags.append('-fobjc-arc')
                run = subprocess.run([*compiler, *flags, str(source)], capture_output=True, text=True)
                if run.returncode:
                    failures.append(f'{source.name}:\n{run.stderr[-2000:]}')
            self.assertEqual(failures, [], '\n'.join(failures))

    def test_runtime_sources(self):
        if platform.system() == 'Darwin' and shutil.which('xcrun'):
            sources = sorted(p for p in (HERE / 'runtime').iterdir() if p.suffix in ('.c', '.m'))
            self.check(['xcrun', 'clang'], sources, ['-I/opt/homebrew/opt/opus/include/opus', '-I/opt/homebrew/opt/libvpx/include'])
            return
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('A C compiler is required')
        self.check([compiler], [HERE / 'runtime' / name for name in PORTABLE], ['-D_GNU_SOURCE'])


if __name__ == '__main__':
    unittest.main()
