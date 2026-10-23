"""Tests for structck call prefix verification aligned with call_window."""
from pathlib import Path
import struct
import sys
import unittest
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'third_party/d2r'))
from structck import is_call_prefix_safe, CALL_PREFIX_MNEMONICS, SIGNED_CALL_PREFIXES, RX18

FC26_BUILD_ID = '863e52bfec7ab17b92fb347967f0619d'


def safe_old(first):
    """The old rule in structck prior to alignment."""
    if not (first and first.mnemonic in ('str', 'stp', 'stur', 'ldr', 'ldp', 'ldur') and not first.writeback):
        return False
    if not first.operands or not hasattr(first.operands[-1], 'mem'):
        return False
    base = first.reg_name(first.operands[-1].mem.base)
    return (
        base in ('sp', 'fp')
        and not first.operands[-1].mem.index
        and (base != 'sp' or first.operands[-1].mem.disp >= 0)
        and not RX18.search(first.op_str)
    )


class StructckCallPrefixAlignmentTest(unittest.TestCase):
    """Test structck call prefix validation: size variants, registered exceptions, and rejection rules."""

    @classmethod
    def setUpClass(cls):
        cls.md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        cls.md.detail = True

    def _disasm(self, word, addr):
        return next(self.md.disasm(struct.pack('<I', word), addr), None)

    MAIN_CALLS = [
        # (call_address, prefix_address, word, description)
        (0x78bdfd8, 0x78bdfd4, 0xb90007f0, 'str w16, [sp, #4]'),
        (0x78be918, 0x78be914, 0xb90007f0, 'str w16, [sp, #4]'),
        (0x78e3e20, 0x78e3e1c, 0xb90003f0, 'str w16, [sp]'),
        (0x78e7598, 0x78e7594, 0xf9000faa, 'str x10, [x29, #0x18]'),
        (0x7f0ce24, 0x7f0ce20, 0x381b83a8, 'sturb w8, [x29, #-0x48]'),
        (0x7f17614, 0x7f17610, 0x381b83a8, 'sturb w8, [x29, #-0x48]'),
        (0x814c01c, 0x814c018, 0xad090aa1, 'stp q1, q2, [x21, #0x120]'),
        (0x8409864, 0x8409860, 0x3d800be4, 'str q4, [sp, #0x20]'),
        (0x84098c0, 0x84098bc, 0x381983a8, 'sturb w8, [x29, #-0x68]'),
    ]

    FOUR_PROBLEM_CALLS = [
        (0x7f0ce24, 0x7f0ce20, 0x381b83a8, 'sturb w8, [x29, #-0x48]'),
        (0x7f17614, 0x7f17610, 0x381b83a8, 'sturb w8, [x29, #-0x48]'),
        (0x814c01c, 0x814c018, 0xad090aa1, 'stp q1, q2, [x21, #0x120]'),
        (0x84098c0, 0x84098bc, 0x381983a8, 'sturb w8, [x29, #-0x68]'),
    ]

    def test_four_previously_failing_calls_pass_now_and_fail_under_old_rule(self):
        """The 4 windows in FC 26 main that failed in structck must fail under safe_old and pass under new safe."""
        for call_addr, prefix_addr, word, desc in self.FOUR_PROBLEM_CALLS:
            with self.subTest(call=hex(call_addr), desc=desc):
                ins = self._disasm(word, prefix_addr)
                self.assertIsNotNone(ins)
                # Must fail under the old rule:
                self.assertFalse(safe_old(ins), f'Expected {desc} to fail under old structck rule')
                # Must pass under the aligned rule:
                self.assertTrue(
                    is_call_prefix_safe(ins, word, prefix_addr, call_addr, FC26_BUILD_ID),
                    f'Expected {desc} to pass under aligned structck rule',
                )

    def test_all_9_main_calls_pass_in_structck(self):
        """All 9 real call prefixes from FC 26 main pass with the matching build id."""
        for call_addr, prefix_addr, word, desc in self.MAIN_CALLS:
            with self.subTest(call=hex(call_addr), desc=desc):
                ins = self._disasm(word, prefix_addr)
                self.assertIsNotNone(ins)
                self.assertTrue(
                    is_call_prefix_safe(ins, word, prefix_addr, call_addr, FC26_BUILD_ID),
                    f'Call prefix at {prefix_addr:#x} ({desc}) should pass',
                )

    def test_registered_exception_strictly_enforced(self):
        """Registered call prefix at 0x814c01c requires matching build id, call address, and exact word."""
        call_addr = 0x814c01c
        prefix_addr = 0x814c018
        correct_word = 0xad090aa1
        ins = self._disasm(correct_word, prefix_addr)

        # 1. Matches build id, call addr, and exact word -> PASS
        self.assertTrue(is_call_prefix_safe(ins, correct_word, prefix_addr, call_addr, FC26_BUILD_ID))

        # 2. Wrong build id -> FAIL (x21 is not SP/FP)
        self.assertFalse(is_call_prefix_safe(ins, correct_word, prefix_addr, call_addr, '00' * 16))
        self.assertFalse(is_call_prefix_safe(ins, correct_word, prefix_addr, call_addr, None))

        # 3. Wrong call address -> FAIL (not registered for other calls)
        self.assertFalse(is_call_prefix_safe(ins, correct_word, prefix_addr, 0x814c020, FC26_BUILD_ID))

        # 4. Wrong word at registered call address -> FAIL
        wrong_words = [
            0xad0902a1,  # stp q1, q2, [x21, #0x100] (different displacement)
            0xad090aa2,  # stp q2, q2, [x21, #0x120] (different register)
            0xb90007f0,  # str w16, [sp, #4] (SP store, but mismatch for registered site)
        ]
        for wrong_w in wrong_words:
            with self.subTest(wrong_w=hex(wrong_w)):
                ins_wrong = self._disasm(wrong_w, prefix_addr)
                self.assertFalse(is_call_prefix_safe(ins_wrong, wrong_w, prefix_addr, call_addr, FC26_BUILD_ID))

    def test_no_other_base_outside_sp_fp_passes(self):
        """No base register other than SP and FP is permitted unless registered."""
        # Non-SP/FP instructions at unregistered addresses must be rejected
        unregistered_stores = [
            (0xad090aa1, 0x7800000, 0x7800004),  # stp q1, q2, [x21, #0x120] at non-registered call
            (0xb9000001, 0x1000, 0x1004),        # str w1, [x0]
            (0xf9000108, 0x1000, 0x1004),        # str x8, [x8, #8]
            (0x39000280, 0x1000, 0x1004),        # strb w0, [x20]
        ]
        for word, p_addr, c_addr in unregistered_stores:
            with self.subTest(word=hex(word), addr=hex(p_addr)):
                ins = self._disasm(word, p_addr)
                self.assertFalse(is_call_prefix_safe(ins, word, p_addr, c_addr, FC26_BUILD_ID))

    def test_generic_size_variants_accepted_with_sp_and_fp(self):
        """Size variants from CALL_PREFIX_MNEMONICS pass with valid SP/FP addressing."""
        variants = [
            (0x390013e0, 'strb w0, [sp, #4]'),
            (0x790013e0, 'strh w0, [sp, #8]'),
            (0x394013e0, 'ldrb w0, [sp, #4]'),
            (0x794013e0, 'ldrh w0, [sp, #8]'),
            (0x39c013e0, 'ldrsb w0, [sp, #4]'),
            (0x79c013e0, 'ldrsh w0, [sp, #8]'),
            (0xb98007e0, 'ldrsw x0, [sp, #4]'),
            (0x381fc3a0, 'sturb w0, [x29, #-4]'),
            (0x781fc3a0, 'sturh w0, [x29, #-4]'),
            (0x385fc3a0, 'ldurb w0, [x29, #-4]'),
            (0x785fc3a0, 'ldurh w0, [x29, #-4]'),
        ]
        for word, desc in variants:
            with self.subTest(desc=desc):
                ins = self._disasm(word, 0x1000)
                # Passes under aligned rule
                self.assertTrue(is_call_prefix_safe(ins, word, 0x1000, 0x1004, FC26_BUILD_ID))
                # Fails under old rule because mnemonic was not in the 6-item set
                self.assertFalse(safe_old(ins))

    def test_rejections_for_disallowed_patterns(self):
        """Reject writeback, x18/w18 usage, negative SP displacement, and register index."""
        bad_cases = [
            (0xb80047e0, 'str w0, [sp], #4 (post-index writeback)'),
            (0xb81fc7e0, 'str w0, [sp, #-4]! (pre-index writeback)'),
            (0xb9000252, 'str w18, [sp] (virtual x18 operand)'),
            (0xb81fc3e0, 'stur w0, [sp, #-4] (negative SP displacement)'),
            (0xb8216be0, 'ldr w0, [sp, x1] (indexed addressing)'),
            (0xd503201f, 'nop (not memory access)'),
        ]
        for word, desc in bad_cases:
            with self.subTest(desc=desc):
                ins = self._disasm(word, 0x1000)
                self.assertFalse(is_call_prefix_safe(ins, word, 0x1000, 0x1004, FC26_BUILD_ID))


if __name__ == '__main__':
    unittest.main()
