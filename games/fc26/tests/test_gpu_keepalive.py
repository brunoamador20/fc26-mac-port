"""Compile the policy used by the real keepalive_start, not a parallel implementation."""
from pathlib import Path
import os,re,subprocess,tempfile,unittest
SRC=Path(__file__).resolve().parents[1]/'third_party/d2r_gfx/gfx/nvn/nvn_mtl.m'
class GpuKeepalive(unittest.TestCase):
    def test_fc26_does_not_spin_gpu_by_default(self):
        source=SRC.read_text()
        function=re.search(r'^static int keepalive_enabled\(void\) \{.*?^}',source,re.M|re.S)
        self.assertIsNotNone(function)
        self.assertIn('!keepalive_enabled()',source[source.index('static void keepalive_start'):source.index('void mtl_init')])
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'policy'
            code='#include <stdlib.h>\n'+function[0]+'\nint main(int argc,char **argv){(void)argc;return keepalive_enabled()!=atoi(argv[1]);}\n'
            build=subprocess.run(['clang','-x','c','-std=c11','-Wall','-Wextra','-Werror','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(build.returncode,0,build.stderr)
            env=dict(os.environ);env.pop('TOTK_GPU_KEEPALIVE',None)
            self.assertEqual(subprocess.run([str(exe),'0'],env=env).returncode,0,'default starts unnecessary GPU spinner')
            for value,expected in [('0','0'),('1','1')]:
                env['TOTK_GPU_KEEPALIVE']=value
                self.assertEqual(subprocess.run([str(exe),expected],env=env).returncode,0)
