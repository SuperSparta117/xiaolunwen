import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.mask import mask_primary_fields


class TestMask(unittest.TestCase):
    def test_fixed_seed_is_reproducible(self):
        row = {"id": "q1", "name": "龙湖花园一期", "address": "龙湖花园", "name_normalized": "龙湖花园一期"}
        self.assertEqual(mask_primary_fields(row, 1.0, 42), mask_primary_fields(row, 1.0, 42))
        masked = mask_primary_fields(row, 1.0, 42)
        self.assertEqual(masked["name"], "")
        self.assertEqual(masked["name_normalized"], "")
        self.assertEqual(masked["address"], "龙湖花园")
        self.assertTrue(masked["_mask_applied"])

    def test_zero_ratio_preserves_input(self):
        row = {"id": "q1", "name": "龙湖花园一期"}
        masked = mask_primary_fields(row, 0.0, 42)
        self.assertEqual(masked["name"], row["name"])
        self.assertFalse(masked["_mask_applied"])


if __name__ == "__main__":
    unittest.main()
