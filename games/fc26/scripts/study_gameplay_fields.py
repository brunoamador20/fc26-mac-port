#!/usr/bin/env python3
"""Read-only, bounded search for direct GameplayFeatures accesses.

Run from any directory. Output is local evidence, never a patch or game asset.
Requires numpy and capstone. Does not claim exhaustive pointer tracking: copies,
indirect calls, register aliases and accesses beyond each window need review.
"""
import argparse
import re
from pathlib import Path

import capstone
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.image.read_bytes()
    words = np.frombuffer(data[:0xa73adb0], dtype='<u4')
    indices = np.nonzero((words & 0x9f000000) == 0x90000000)[0]
    values = words[indices].astype(np.int64)
    immediate = (((values >> 5) & 0x7ffff) << 2) | ((values >> 29) & 3)
    immediate = np.where(immediate & (1 << 20), immediate - (1 << 21), immediate)
    pcs = indices.astype(np.int64) * 4
    pages = (pcs & ~0xfff) + (immediate << 12)
    dis = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    fields = {0x7e: 'EnableFasterRunSpeeds', 0x6f: 'EnableNextGenLocomotion',
              0x66: 'EnableMultipleAccelCurveBuckets', 0x4e: 'EnableOffBallMarkingSpecificAccel',
              0x57: 'EnableLocomotionProceduralLean', 0x71: 'EnableRunningShield',
              0x30: 'CpuAiObjectivesUpdateMode', 0x81: 'EnableHighPrequencyPerceptionUpdate',
              0x51: 'EnablePPCriticalReducedEvaluation',
              0x56: 'EnablePPAlternateFrameOptimization',
              0x5f: 'EnableExtraPassEvaluations'}
    with args.output.open('w') as out:
        out.write('Bounded direct accesses only; all addresses are main module offsets.\n')
        for pc in pcs[pages == 0xc665000]:
            pc = int(pc)
            window = list(dis.disasm(data[pc:pc + 48], pc))
            page_reg = window[0].op_str.split(',')[0]
            for load in window[1:]:
                if load.mnemonic != 'ldr' or f'[{page_reg}, #0x768]' not in load.op_str:
                    continue
                reg = load.op_str.split(',')[0]
                ins = list(dis.disasm(data[load.address:load.address + 160], load.address))
                for k, item in enumerate(ins[1:], 1):
                    match = re.search(r'\[' + reg + r', #(0x[0-9a-f]+)\]', item.op_str)
                    if match and int(match[1], 16) in fields:
                        out.write('\n' + fields[int(match[1], 16)] + '\n')
                        for row in ins[:k + 10]:
                            out.write(f'{row.address:#x}: {row.mnemonic} {row.op_str}\n')
                    if item.mnemonic in ('ret', 'b'):
                        break
                    if item.op_str.split(',')[0] == reg and item.mnemonic not in (
                            'str', 'strb', 'cmp', 'tst', 'cbz', 'cbnz'):
                        break


if __name__ == '__main__':
    main()
