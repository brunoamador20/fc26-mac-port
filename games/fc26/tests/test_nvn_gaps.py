"""The eight NVN entry points FC 26's video module calls that the NVN layer did not implement (docs/BRIEFING.md, audited
22/10: 241 used, 233 present). third_party/d2r_gfx/gfx/nvn/fc26_nvn_ext.c implements them; tests/nvn_gaps.c includes it
and checks what each returns or records, plus the copy stride arithmetic of nvn_copy_stride.h. The Metal side
(nvn_mtl.m) only builds on macOS: here its handling of the new record is checked as text. Runs on Linux and on the Mac.
clang is required: the layer's registration table uses a Mach-O section name ("__DATA,swnvn") that GNU as rejects."""
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
NVN = HERE / 'third_party/d2r_gfx/gfx/nvn'
GAPS = ['nvnBufferBuilderGetMemoryOffset', 'nvnBufferBuilderGetSize', 'nvnEventGetMemoryOffset', 'nvnSamplerPoolGetMemoryOffset',
        'nvnTexturePoolGetMemoryOffset', 'nvnTextureBuilderGetRawStorageClass', 'nvnCommandBufferSetCopyImageStride',
        'nvnMultisampleStateSetSampleLocationsGridEnable']
NO_PROTOTYPE = {'nvnEventGetMemoryOffset', 'nvnTextureBuilderGetRawStorageClass'}


class NvnGaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('clang is required')
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.folder.name) / 'nvn_gaps'
        flags = ['-std=gnu11', '-Wall', '-Wextra', '-Werror'] + ([] if platform.system() == 'Darwin' else ['-D_GNU_SOURCE'])
        build = subprocess.run([compiler, *flags, f'-I{NVN / "include"}', str(HERE / 'tests/nvn_gaps.c'), '-o', str(cls.exe)],
                               capture_output=True, text=True)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, mode):
        return subprocess.run([str(self.exe), mode], capture_output=True, text=True, timeout=30)

    def test_checks_pass(self):
        run = self.run_case('run')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)

    def test_registered_under_the_names_of_main_name_table(self):
        # The thunk table is generated from names.txt: slot i = line i, label Ln<i> in nvn_thunks.S. A name outside it would
        # stop nvn_init_slots ("not in main's name table").
        run = self.run_case('run')
        registered = [l.split(' ', 1)[1] for l in run.stdout.splitlines() if l.startswith('name ')]
        self.assertEqual(registered, GAPS)
        names = (NVN / 'names.txt').read_text().split()
        thunks = (NVN / 'nvn_thunks.S').read_text()
        count = int(re.search(r'#define NVN_NFUNC (\d+)', (NVN / 'nvn_count.h').read_text()).group(1))
        self.assertEqual(len(names), count)
        for name in GAPS:
            with self.subTest(name=name):
                self.assertEqual(names.count(name), 1)
                self.assertIn(f'Ln{names.index(name)}: .asciz "{name}"\n', thunks)

    def test_each_gap_is_implemented_once(self):
        # nvn_init_slots fills a slot per registration without checking for duplicates: the later one would win silently.
        found = {}
        for source in sorted(NVN.glob('*.c')):
            for name in re.findall(r'^\s*NVN(?:_NOPROTO)?\((nvn\w+)', source.read_text(), re.M):
                found.setdefault(name, []).append(source.name)
        for name in GAPS:
            with self.subTest(name=name):
                self.assertEqual(found.get(name), ['fc26_nvn_ext.c'])

    def test_signatures_follow_the_header(self):
        # NVN() checks the signature against nvn_protos.h at compile time; NVN_NOPROTO() is only for names the header lacks.
        protos = (NVN / 'nvn_protos.h').read_text()
        ext = (NVN / 'fc26_nvn_ext.c').read_text()
        for name in GAPS:
            with self.subTest(name=name):
                has_proto = f'(*NVNT_{name})(' in protos
                self.assertEqual(has_proto, name not in NO_PROTOTYPE)
                macro = 'NVN_NOPROTO' if name in NO_PROTOTYPE else 'NVN'
                self.assertIsNotNone(re.search(rf'^{macro}\({name},', ext, re.M), f'{macro}({name}, ...) in fc26_nvn_ext.c')

    def test_negative_image_stride_stops(self):
        run = self.run_case('negative-stride')
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('nvnCommandBufferSetCopyImageStride -16: negative image stride', run.stderr)
        self.assertNotIn('not stopped', run.stdout)

    def test_sample_location_grid_is_stored_and_reported_once(self):
        run = self.run_case('grid-log')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.split(), ['grid', '0', 'grid', '1', 'grid', '0'])
        self.assertEqual(run.stderr.count('SetSampleLocationsGridEnable(1): no Metal equivalent'), 1)

    def test_metal_replay_handles_the_image_stride(self):
        # nvn_mtl.m (Objective-C, Metal) builds only on macOS. Every replay switch that lists the row stride record must
        # list the image stride record (an unlisted op is dropped by the replay), and both copies take the new stride.
        mtl = (NVN / 'nvn_mtl.m').read_text()
        self.assertEqual(mtl.count('case OP_COPY_STRIDE:'), mtl.count('case OP_COPY_IMG_STRIDE:'))
        self.assertIn('case OP_COPY_IMG_STRIDE: S.copy_img_stride = ((const p_copy_stride *)a)->stride; break;', mtl)
        self.assertEqual(mtl.count('nvn_copy_layout_of(c->r.width, c->r.height, nz, bw, bh, bpb, S.copy_stride, S.copy_img_stride)'), 2)
        # the buffer range is the layout's span now (aimg / uimg * nz are the host's own tightly packed staging buffers)
        for start, end in [('static void copy_t2b(', '// CPU 读贴图'), ('static void copy_b2t(', '// 无 BC + 老机型补充包')]:
            self.assertIsNone(re.search(r'\bimg \* nz', mtl[mtl.index(start):mtl.index(end)]), start)


if __name__ == '__main__':
    unittest.main()
