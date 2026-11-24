import csv
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.mask_sweep import run_mask_sweep


class TestMaskSweep(unittest.TestCase):
    def test_bounded_sweep_has_all_ratios(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = run_mask_sweep(
                Path(temp_dir), ratios=(0.0, 1.0), query_limit=12, candidate_limit=48, mapping_limit=20, k=10
            )
            self.assertEqual(manifest["ratios"], [0.0, 1.0])
            with (Path(temp_dir) / "mask_recall_summary_end_to_end.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["rho"] for row in rows}, {"0.0", "1.0"})
            self.assertEqual({row["provenance"] for row in rows}, {"all", "original_annotation", "external_derived"})


if __name__ == "__main__":
    unittest.main()
