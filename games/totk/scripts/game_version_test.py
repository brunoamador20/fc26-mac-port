"""Version-aware addresses for instruction emulation tests (runtime guards remain independent)."""
import argparse,re,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def options():
    p=argparse.ArgumentParser();p.add_argument('--version',choices=('v0','v112'),default='v0');return p.parse_args()
def offsets(version):
    source=(ROOT/'runtime/game_version.h').read_text().split('#elif defined(TOTK_GAME_V112)',1)[1].split('#else',1)[0]
    mapping={int(a,16):int(b,16) for a,b in re.findall(r'#define GAME_ADDR_(0x[0-9a-f]+) (0x[0-9a-f]+)',source)}
    def address(value):return mapping[value] if version=='v112' else value
    return address
def adrp_ldr(image,pc,ldr_pc):
    a=struct.unpack_from('<I',image,pc)[0];b=struct.unpack_from('<I',image,ldr_pc)[0]
    assert a&0x9f000000==0x90000000 and b&0xffc00000==0xf9400000
    assert a&31==(b>>5)&31
    imm=((a>>29)&3)|(((a>>5)&0x7ffff)<<2);imm=(imm^(1<<20))-(1<<20)
    return (pc&~4095)+(imm<<12)+((b>>10)&4095)*8
