#!/usr/bin/env python3
"""Decode TOTK's dictionary-compressed shader packages; no D2R shader facts."""
import hashlib,json,struct
from pathlib import Path
import compression.zstd as zstd
root=Path(__file__).resolve().parents[1]
folder=root/'extracted/v0/graphics';folder.mkdir(exist_ok=True)
manifest=json.loads((root/'extracted/v0/romfs/index.json').read_text())
assert manifest['status']=='pass'
files={f['path']:f for f in manifest['files']}

def sarc(data):
    assert data[:4]==b'SARC'
    endian='<' if data[6:8]==b'\xff\xfe' else '>'
    header,size,start=struct.unpack_from(endian+'HxxII',data,4)
    assert size==len(data) and header>=20 and header+12<=size and data[header:header+4]==b'SFAT'
    count=struct.unpack_from(endian+'H',data,header+6)[0];names=header+12+count*16
    assert data[names:names+4]==b'SFNT';names+=8
    result={}
    for i in range(count):
        _,attribute,lo,hi=struct.unpack_from(endian+'4I',data,header+12+i*16)
        assert attribute>>24==1 and start+lo<=start+hi<=len(data)
        offset=names+(attribute&0xffffff)*4;assert names<=offset<start
        name=data[offset:data.index(0,offset,start)].decode()
        path=Path(name);assert not path.is_absolute() and all(p not in ['.','..',''] for p in path.parts) and '\\' not in name
        assert name not in result;result[name]=data[start+lo:start+hi]
    return result

report=[]
with (root/'extracted/v0/romfs/romfs.bin').open('rb') as image:
    def read(path):
        f=files[path];image.seek(f['offset']);b=image.read(f['size']);assert len(b)==f['size'];return b
    dictionary_pack=zstd.decompress(read('Pack/ZsDic.pack.zs'))
    dictionaries={}
    for name,data in sarc(dictionary_pack).items():
        dictionary=zstd.ZstdDict(data);dictionaries[dictionary.dict_id]=dictionary
        (folder/name).write_bytes(data)
    wanted=[name for name in files if name.startswith('Shader/') and name.endswith('.zs')]
    wanted+=['Lib/NintendoSDK/TextureShader.bnsh','Pack/Bootup.Nin_NX_NVN.pack.zs']
    for path in wanted:
        raw=read(path);decoded=raw
        if path.endswith('.zs'):
            info=zstd.get_frame_info(raw);assert info.decompressed_size is not None and info.decompressed_size<=512<<20
            dictionary=dictionaries[info.dictionary_id] if info.dictionary_id else None
            decoded=zstd.decompress(raw,zstd_dict=dictionary)
        destination=folder/Path(path).name.removesuffix('.zs');destination.write_bytes(decoded)
        members={}
        if decoded[:4]==b'SARC':
            target=folder/(destination.name+'.contents');target.mkdir(exist_ok=True)
            for name,data in sarc(decoded).items():
                output=target/name;output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data)
                members[name]=dict(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        report.append(dict(path=path,compressed_size=len(raw),size=len(decoded),magic=decoded[:8].hex(),sha256=hashlib.sha256(decoded).hexdigest(),members=members))
        print(json.dumps(dict(path=path,size=len(decoded),members=len(members),magic=decoded[:8].hex())),flush=True)
(root/'analysis/graphics-assets.json').write_text(json.dumps(report,indent=2)+'\n')
