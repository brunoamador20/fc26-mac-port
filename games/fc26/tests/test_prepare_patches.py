"""scripts/prepare_patches.py names main by its build ID: an IPSwitch file may give the first 20 bytes or all 32."""
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'scripts'))
import prepare_patches  # noqa: E402

BUILD_ID = '0123456789ABCDEF0123456789ABCDEF01234567'   # a synthetic 20-byte ID


class BuildId(unittest.TestCase):
    def test_short_and_padded_forms_match(self):
        self.assertTrue(prepare_patches.same_build_id(BUILD_ID, BUILD_ID))
        self.assertTrue(prepare_patches.same_build_id(BUILD_ID.lower() + '0' * 24, BUILD_ID))

    def test_another_build_does_not(self):
        self.assertFalse(prepare_patches.same_build_id('AB' + BUILD_ID[2:], BUILD_ID))


if __name__ == '__main__':
    unittest.main()
