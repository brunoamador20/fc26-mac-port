#!/usr/bin/env python3
"""Validate extracted shader identities and generate a code-sensitive runtime map."""
import collections,hashlib,json,struct
from pathlib import Path
root=Path(__file__).resolve().parents[1];source=root/'extracted/v0/shaders-v2'
inv=json.loads((source/'inventory.json').read_text());assert inv['status']=='pass'
unique={};control_keys=collections.defaultdict(set);stages={'vs':'顶点','ps':'像素','cs':'计算','hs':'外壳','ds':'域'};canonical={};skipped=[]
for row in inv['rows']:
 signature=(row['stage'],row['control_sha256'],row['code_sha256'])
 assert row['key'] not in unique or unique[row['key']][0]==signature
 unique[row['key']]=(signature,row);control_keys[row['control_key']].add(signature)
for key,(_,row) in unique.items():
 control=(source/(key+'.control')).read_bytes();code=(source/(key+'.code')).read_bytes()
 assert len(control)==row['control_size'] and len(code)==row['code_size']
 assert hashlib.sha256(control).hexdigest()==row['control_sha256']
 assert hashlib.sha256(code).hexdigest()==row['code_sha256']
 assert hashlib.sha256(control+code).hexdigest()==key
 assert struct.unpack_from('<I',control,0x704)[0]==len(code)
 if len(control)<0x880:skipped.append(key);continue
 ck=hashlib.sha256(control[:0x880]+code).hexdigest()
 if ck in canonical:assert canonical[ck][0:2]==(row['stage'],row['code_sha256'])
 else:canonical[ck]=(row['stage'],row['code_sha256'],key)
lines=['# TOTK control-code-sha256-v1']+[f'{key}\t{stages[stage]}\t{asset}' for key,(stage,_,asset) in sorted(canonical.items())]
(root/'build/shader-map.tsv').write_text('\n'.join(lines)+'\n')
report=dict(status='pass',records=len(inv['rows']),unique=len(unique),control_key_collisions=sum(len(v)>1 for v in control_keys.values()),runtime_keys=len(canonical),short_control_excluded=skipped,scope='asset identity and map only; no full shader translation/reflection or game frame')
(root/'analysis/shader-inventory-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
