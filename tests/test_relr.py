"""Compressed relocation regression tests; all bytes and addresses are synthetic."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'games/totk/third_party/d2r'))
from relr import decode_relr


class RelrTests(unittest.TestCase):
    def fixture(self, entries):
        image = bytearray(0x1000)
        for address in range(0x200, 0x800, 8): struct.pack_into('<Q', image, address, address + 8)
        struct.pack_into('<' + 'Q' * len(entries), image, 0x100, *entries)
        return image, {35: len(entries) * 8, 36: 0x100, 37: 8}

    def test_addresses_and_consecutive_bitmaps(self):
        image, tags = self.fixture([0x200, 0b1011, 0b11, 0x700])
        self.assertEqual(decode_relr(image, tags, 0x200, len(image)),
                         [(0x200,0x208),(0x208,0x210),(0x218,0x220),(0x400,0x408),(0x700,0x708)])

    def test_missing_tags_and_wrong_stride(self):
        image, tags = self.fixture([0x200])
        for broken in ({35:8,36:0x100}, dict(tags, **{})):
            if 37 in broken: broken[37] = 4
            with self.assertRaises(ValueError): decode_relr(image, broken, 0x200, len(image))

    def test_bitmap_requires_a_base_and_rejects_duplicate(self):
        for entries in ([3], [0x200,0x200]):
            image, tags = self.fixture(entries)
            with self.assertRaises(ValueError): decode_relr(image, tags, 0x200, len(image))

    def test_rejects_bounds_alignment_and_bad_addend(self):
        for entries in ([0x1f8], [0x1000], [0x202]):
            image, tags = self.fixture(entries)
            with self.assertRaises(ValueError): decode_relr(image, tags, 0x200, len(image))
        image, tags = self.fixture([0x200]); struct.pack_into('<Q', image, 0x200, len(image))
        with self.assertRaises(ValueError): decode_relr(image, tags, 0x200, len(image))

    def test_absent_table_preserves_old_modules(self):
        self.assertEqual(decode_relr(bytes(64), {}, 0, 64), [])


if __name__ == '__main__': unittest.main()
