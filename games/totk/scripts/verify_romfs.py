#!/usr/bin/env python3
"""Compare native filesystem reads with independent local-image reads."""
import json,subprocess,tempfile,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
run=subprocess.run([str(root/'build/totk-native'),'rewritten/v0','probe-fs'],cwd=root,capture_output=True,text=True,check=True)
report=json.loads(run.stdout);files=json.loads((root/'extracted/v0/romfs/index.json').read_text())['files']
digest=0;count=0
with (root/'extracted/v0/romfs/romfs.bin').open('rb') as image:
    for item in files[::len(files)//64]:
        image.seek(item['offset']);data=image.read(min(257,item['size']))
        for byte in data:digest=(digest*131+byte)&((1<<64)-1)
        count+=1
assert report['sampled_files']==count and report['read_digest']==f'{digest:016x}'
with tempfile.TemporaryDirectory(dir=root/'build') as folder:
    (Path(folder)/'runtime-index.bin').write_bytes(b'invalid index data'*20)
    env=os.environ.copy();env['TOTK_ROMFS']=folder
    failed=subprocess.run([str(root/'build/totk-native'),'rewritten/v0','probe-fs'],cwd=root,capture_output=True,text=True,env=env)
    assert failed.returncode==1 and 'RomFS integrity mismatch' in failed.stderr
report['independent_read_comparison']='pass';report['corrupted_index_negative_control']='rejected'
(root/'analysis/native-romfs-probe.json').write_text(json.dumps(report,indent=2)+'\n')
(root/'analysis/native-romfs-probe.log').write_text(run.stderr)
print(json.dumps(report))
