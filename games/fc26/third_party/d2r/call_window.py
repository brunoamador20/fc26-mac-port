"""BLR x18 preparation without changing callee entry registers or return PC.

The preceding, movable stack access is replayed first. A borrowed register is
saved/restored in the Apple red zone, then x30 receives virtual x18. Returning
to BLR x30 at the ORIGINAL call address preserves its architectural link value.
Precondition: no alternate entry into the second word of this two-word window.
"""
import struct
import re
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

BLR_X18 = 0xD63F0240
BLR_X30 = 0xD63F03C0

CALL_PREFIX_MNEMONICS = (
    'str', 'stp', 'stur',
    'strb', 'sturb', 'strh', 'sturh',
    'ldr', 'ldp', 'ldur',
    'ldrb', 'ldurb', 'ldrh', 'ldurh',
    'ldrsb', 'ldursb', 'ldrsh', 'ldursh', 'ldrsw', 'ldursw',
)

# Registered call prefix exceptions by build ID.
# Format: {build_id: {call_address: expected_word}}
SIGNED_CALL_PREFIXES = {
    '863e52bfec7ab17b92fb347967f0619d': {
        0x814c01c: 0xad090aa1,  # stp q1, q2, [x21, #0x120]
    },
    '323f3a9f3f0426c97610dc9066f4e67e': {
        0x827558c: 0xad090aa1,  # stp q1, q2, [x21, #0x120]
    },
}
PREFIX_EXCEPTIONS = SIGNED_CALL_PREFIXES


def branch(source, target):
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError('Call-window branch out of range')
    return 0x14000000 | ((delta >> 2) & 0x3FFFFFF)


def movable_store(word, address, build_id=None, call_address=None):
    exception_table = SIGNED_CALL_PREFIXES.get(build_id, {}) if build_id else {}
    targets = [a for a in (call_address, address, address + 4 if address is not None else None, address - 4 if address is not None else None) if a is not None]
    matched_addr = next((a for a in targets if a in exception_table), None)

    if matched_addr is not None:
        expected_word = exception_table[matched_addr]
        if word != expected_word:
            raise ValueError(f'Registered call prefix mismatch at {matched_addr:#x}: expected {expected_word:#010x}, got {word:#010x}')

    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoder.detail = True
    ins = next(decoder.disasm(struct.pack('<I', word), address), None)
    if ins is None or ins.mnemonic not in CALL_PREFIX_MNEMONICS or ins.writeback:
        raise ValueError(f'Call prefix must be a non-writeback stack access: {address:#x}')
    mem = ins.operands[-1].mem
    base = ins.reg_name(mem.base)
    if matched_addr is None:
        if base not in ('sp', 'fp') or mem.index or (base == 'sp' and mem.disp < 0):
            raise ValueError(f'Call prefix must access the SP/FP stack frame: {address:#x}')
    if re.search(r'\b[xw]18\b', ins.op_str):
        raise ValueError(f'Call prefix also uses virtual x18: {address:#x}')


def prepare_call(prefix_word, prefix_address, call_address, patch_address,
                 key_page_address, key_index, scratch=0, build_id=None):
    if call_address != prefix_address + 4 or not 0 <= scratch < 18:
        raise ValueError('Invalid call window or scratch register')
    movable_store(prefix_word, prefix_address, build_id=build_id, call_address=call_address)
    if not 0 <= key_index < 8:
        raise ValueError('Invalid key-page index')
    adrp_pc = patch_address + 12
    pages = ((key_page_address & ~4095) - (adrp_pc & ~4095)) >> 12
    if not -(1 << 20) <= pages < (1 << 20):
        raise ValueError('Key page out of ADRP range')
    words = [
        prefix_word,
        0xF8000000 | ((-16 & 0x1FF) << 12) | (31 << 5) | scratch,
        0xD53BD060 | 30,  # mrs x30,tpidrro_el0
        0x90000000 | ((pages & 3) << 29) | (((pages >> 2) & 0x7FFFF) << 5) | scratch,
        0xF9400000 | (((key_page_address & 4095) // 8 + key_index) << 10) | (scratch << 5) | scratch,
        0x8B000000 | (scratch << 16) | (30 << 5) | 30,
        0xF9400000 | (30 << 5) | 30,
        0xF8400000 | ((-16 & 0x1FF) << 12) | (31 << 5) | scratch,
        branch(patch_address + 32, call_address),
    ]
    return struct.pack('<' + 'I' * len(words), *words)
