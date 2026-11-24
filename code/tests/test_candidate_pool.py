import csv
import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.candidate_pool import build_candidate_pool


class TestCandidatePool(unittest.TestCase):
    def test_bounded_pool_reports_recall_without_unknown_negatives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = build_candidate_pool(
                Path(temp_dir), query_limit=12, candidate_limit=48, mapping_limit=20, k=10
            )
            self.assertEqual(manifest["counts"]["query_rows"], 12)
            self.assertGreater(manifest["counts"]["pool_rows"], 0)
            self.assertEqual(
                manifest["counts"]["gold_queries_in_sample"],
                manifest["counts"]["gold_queries_recalled"] + manifest["counts"]["gold_queries_not_recalled"],
            )
            self.assertFalse(manifest["policy"]["unknown_is_negative"])
            with (Path(temp_dir) / "candidate_pool.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertIn("recall_sources", rows[0])
            self.assertIn(rows[0]["gold_in_pool"], {"true", "false"})
            saved = json.loads((Path(temp_dir) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["k"], 10)
            recall_rows = list(csv.DictReader((Path(temp_dir) / "candidate_recall_at_k.csv").open(encoding="utf-8", newline="")))
            self.assertTrue(recall_rows)
            self.assertIn("query_recall", recall_rows[0])
            self.assertIn("pair_recall", recall_rows[0])
            self.assertEqual({row["provenance"] for row in recall_rows}, {"all", "original_annotation", "external_derived"})
            channel_rows = list(csv.DictReader((Path(temp_dir) / "candidate_recall_by_channel.csv").open(encoding="utf-8", newline="")))
            self.assertEqual({row["channel"] for row in channel_rows}, {"name_ngram", "address_ngram", "area", "union"})


if __name__ == "__main__":
    unittest.main()
