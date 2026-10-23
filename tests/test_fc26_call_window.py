#!/usr/bin/env python3
"""Tests for call_window: size variants, registered exceptions, and rejection rules."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'games/fc26/third_party/d2r'))
from call_window import (
    BLR_X18,
    BLR_X30,
    CALL_PREFIX_MNEMONICS,
    SIGNED_CALL_PREFIXES,
    branch,
    movable_store,
    prepare_call,
)

FC26_BUILD_ID = '863e52bfec7ab17b92fb347967f0619d'
PATCH_ADDR = 0x2000
KEY_PAGE = 0x4000


class CallWindowSizeVariantsTest(unittest.TestCase):
    """Test acceptance of all 14 size-variant mnemonics with SP / FP stack access."""

    def test_sp_positive_offset_variants(self):
        # All positive-displacement SP accesses for size variants must pass
        variants = [
            ('strb', 0x390013e0),   # strb w0, [sp, #4]
            ('strh', 0x790013e0),   # strh w0, [sp, #8]
            ('ldrb', 0x394013e0),   # ldrb w0, [sp, #4]
            ('ldrh', 0x794013e0),   # ldrh w0, [sp, #8]
            ('ldrsb_w', 0x39c013e0),  # ldrsb w0, [sp, #4]
            ('ldrsb_x', 0x398013e0),  # ldrsb x0, [sp, #4]
            ('ldrsh_w', 0x79c013e0),  # ldrsh w0, [sp, #8]
            ('ldrsh_x', 0x798013e0),  # ldrsh x0, [sp, #8]
            ('ldrsw', 0xb98007e0),  # ldrsw x0, [sp, #4]
        ]
        for name, word in variants:
            with self.subTest(name=name, word=hex(word)):
                movable_store(word, 0x1000)
                block = prepare_call(word, 0x1000, 0x1004, PATCH_ADDR, KEY_PAGE, 0)
                self.assertEqual(len(block), 36)
                self.assertEqual(struct.unpack_from('<I', block, 0)[0], word)

    def test_fp_negative_offset_variants(self):
        # All unscaled negative-displacement FP (x29) accesses must pass
        variants = [
            ('sturb', 0x381fc3a0),   # sturb w0, [x29, #-4]
            ('sturh', 0x781fc3a0),   # sturh w0, [x29, #-4]
            ('ldurb', 0x385fc3a0),   # ldurb w0, [x29, #-4]
            ('ldurh', 0x785fc3a0),   # ldurh w0, [x29, #-4]
            ('ldursb_w', 0x38dfc3a0),  # ldursb w0, [x29, #-4]
            ('ldursb_x', 0x389fc3a0),  # ldursb x0, [x29, #-4]
            ('ldursh_w', 0x78dfc3a0),  # ldursh w0, [x29, #-4]
            ('ldursh_x', 0x789fc3a0),  # ldursh x0, [x29, #-4]
            ('ldursw', 0xb89fc3a0),  # ldursw x0, [x29, #-4]
        ]
        for name, word in variants:
            with self.subTest(name=name, word=hex(word)):
                movable_store(word, 0x1000)
                block = prepare_call(word, 0x1000, 0x1004, PATCH_ADDR, KEY_PAGE, 0)
                self.assertEqual(len(block), 36)
                self.assertEqual(struct.unpack_from('<I', block, 0)[0], word)

    def test_classic_mnemonics_still_accepted(self):
        classic = [
            ('str', 0xb90007f0),   # str w16, [sp, #4]
            ('stp', 0xa901bfe0),   # stp x0, x1, [sp, #24]
            ('stur', 0xf81f83a0),  # stur x0, [x29, #-8]
            ('ldr', 0xb94007f0),   # ldr w16, [sp, #4]
            ('ldp', 0xa941bfe0),   # ldp x0, x1, [sp, #24]
            ('ldur', 0xf85f83a0),  # ldur x0, [x29, #-8]
        ]
        for name, word in classic:
            with self.subTest(name=name, word=hex(word)):
                movable_store(word, 0x1000)
                block = prepare_call(word, 0x1000, 0x1004, PATCH_ADDR, KEY_PAGE, 0)
                self.assertEqual(len(block), 36)


class CallWindowRejectionRulesTest(unittest.TestCase):
    """Test strict rejection of unsafe prefixes: writeback, negative SP, x18, non-SP/FP bases."""

    def test_reject_writeback(self):
        # Pre-index and post-index writebacks must be rejected
        writeback_words = [
            0x381fffe0,  # strb w0, [sp, #-1]!
            0x38401fe0,  # ldrb w0, [sp, #1]!
            0xa9bf7bfd,  # stp x29, x30, [sp, #-16]!
        ]
        for word in writeback_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000)

    def test_reject_negative_sp_access(self):
        # Access below SP (even unscaled) must be rejected because red zone uses [sp, #-16]
        negative_sp_words = [
            0x381ff3e0,  # sturb w0, [sp, #-1]
            0xb89fc3e0,  # ldursw x0, [sp, #-4]
            0xf81f03e0,  # stur x0, [sp, #-16]
        ]
        for word in negative_sp_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000)

    def test_reject_virtual_x18_usage(self):
        # Any prefix touching x18 or w18 must be rejected
        x18_words = [
            0x390013f2,  # strb w18, [sp, #4]
            0x394013f2,  # ldrb w18, [sp, #4]
            0xb98007f2,  # ldrsw x18, [sp, #4]
            0xf9000ff2,  # str x18, [sp, #0x18]
        ]
        for word in x18_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000)

    def test_reject_base_outside_sp_fp(self):
        # Base registers other than sp/fp must be rejected without registered exception
        non_stack_words = [
            0x39001280,  # strb w0, [x20, #4]
            0x39401020,  # ldrb w0, [x1, #4]
            0xb98006a0,  # ldrsw x0, [x21, #4]
            0xad090aa1,  # stp q1, q2, [x21, #0x120] (the FC26 word at unregistered address)
        ]
        for word in non_stack_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000)
                # Even passing FC26_BUILD_ID to an unregistered address must be rejected
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000, build_id=FC26_BUILD_ID)

    def test_reject_non_store_instructions(self):
        # Non-memory-access instructions must be rejected
        invalid_words = [
            0xd503201f,  # nop
            0x8b010000,  # add x0, x0, x1
            0x14000004,  # b +16
            0xd65f03c0,  # ret
        ]
        for word in invalid_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, 0x1000)


class CallWindowRegisteredExceptionTest(unittest.TestCase):
    """Test build-id keyed registered exceptions: acceptance of exact word and rejection of mismatches."""

    def test_registered_exception_accepted(self):
        call_addr = 0x814c01c
        prefix_addr = 0x814c018
        expected_word = 0xad090aa1  # stp q1, q2, [x21, #0x120]

        # 1. movable_store with prefix address and build_id
        movable_store(expected_word, prefix_addr, build_id=FC26_BUILD_ID)

        # 2. movable_store with call address directly and build_id
        movable_store(expected_word, call_addr, build_id=FC26_BUILD_ID)

        # 3. movable_store with both prefix and call_address explicitly
        movable_store(expected_word, prefix_addr, build_id=FC26_BUILD_ID, call_address=call_addr)

        # 4. prepare_call with build_id
        patch_addr = prefix_addr + 0x1000
        key_page = patch_addr + 0x2000
        block = prepare_call(
            expected_word, prefix_addr, call_addr, patch_addr, key_page, 0,
            build_id=FC26_BUILD_ID,
        )
        self.assertEqual(len(block), 36)
        self.assertEqual(struct.unpack_from('<I', block, 0)[0], expected_word)

    def test_registered_exception_rejected_on_wrong_word(self):
        call_addr = 0x814c01c
        prefix_addr = 0x814c018

        wrong_words = [
            0xdeadbeef,  # Arbitrary invalid word
            0xd503201f,  # nop
            0xad0902a1,  # stp q1, q2, [x21, #0x100] (different displacement)
            0xad090aa2,  # stp q2, q2, [x21, #0x120] (different register)
            0xb90007f0,  # str w16, [sp, #4] (SP store, but wrong word for this registered site)
        ]
        for word in wrong_words:
            with self.subTest(word=hex(word)):
                with self.assertRaises(ValueError):
                    movable_store(word, prefix_addr, build_id=FC26_BUILD_ID)
                with self.assertRaises(ValueError):
                    movable_store(word, call_addr, build_id=FC26_BUILD_ID)
                with self.assertRaises(ValueError):
                    prepare_call(
                        word, prefix_addr, call_addr, PATCH_ADDR, KEY_PAGE, 0,
                        build_id=FC26_BUILD_ID,
                    )

    def test_registered_exception_rejected_without_matching_build_id(self):
        call_addr = 0x814c01c
        prefix_addr = 0x814c018
        expected_word = 0xad090aa1

        # No build_id provided
        with self.assertRaises(ValueError):
            movable_store(expected_word, prefix_addr)
        with self.assertRaises(ValueError):
            prepare_call(expected_word, prefix_addr, call_addr, PATCH_ADDR, KEY_PAGE, 0)

        # Wrong / unknown build_id
        with self.assertRaises(ValueError):
            movable_store(expected_word, prefix_addr, build_id='00' * 16)
        with self.assertRaises(ValueError):
            prepare_call(expected_word, prefix_addr, call_addr, PATCH_ADDR, KEY_PAGE, 0, build_id='00' * 16)


class CallWindowMainCallsRegressionTest(unittest.TestCase):
    """Test all 9 real calls from the FC 26 main executable."""

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

    def test_all_9_main_calls_pass_with_fc26_build_id(self):
        for call_addr, prefix_addr, word, desc in self.MAIN_CALLS:
            with self.subTest(call=hex(call_addr), desc=desc):
                movable_store(word, prefix_addr, build_id=FC26_BUILD_ID)
                patch_addr = prefix_addr + 0x1000
                key_page = patch_addr + 0x2000
                block = prepare_call(
                    word, prefix_addr, call_addr, patch_addr, key_page, 0,
                    build_id=FC26_BUILD_ID,
                )
                self.assertEqual(len(block), 36)
                self.assertEqual(struct.unpack_from('<I', block, 0)[0], word)

    def test_only_registered_x21_fails_without_build_id(self):
        # 8 calls pass on generic rules; exactly the x21 call at 0x814c01c requires the registered exception
        for call_addr, prefix_addr, word, desc in self.MAIN_CALLS:
            with self.subTest(call=hex(call_addr), desc=desc):
                if call_addr == 0x814c01c:
                    with self.assertRaises(ValueError):
                        movable_store(word, prefix_addr)
                else:
                    movable_store(word, prefix_addr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
