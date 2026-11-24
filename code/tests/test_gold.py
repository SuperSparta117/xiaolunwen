import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.gold import build_evaluation_assets


class TestGoldAssets(unittest.TestCase):
    def test_bounded_assets_keep_unknown_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = build_evaluation_assets(
                Path(temp_dir), query_limit=12, candidate_limit=48, mapping_limit=20
            )
            self.assertEqual(manifest["counts"]["query_rows"], 12)
            self.assertEqual(manifest["counts"]["gold_pair_rows"], 20)
            self.assertEqual(manifest["counts"]["confirmed_empty_query_rows"], 0)
            self.assertGreater(manifest["counts"]["unknown_query_rows"], 0)
            self.assertEqual(manifest["provenance_counts"]["original_annotation"], 20)
            self.assertEqual(manifest["provenance_counts"]["external_derived"], 0)
            self.assertEqual(manifest["mapping_integrity"]["multi_pair_query_count"], 0)
            self.assertIn("match_type_counts", manifest)
            self.assertFalse(manifest["label_policy"]["unknown_is_confirmed_empty"])

            query_rows = (Path(temp_dir) / "evaluation_queries.csv").read_text(encoding="utf-8")
            self.assertIn("unknown", query_rows)
            gold_sets = (Path(temp_dir) / "gold_sets.csv").read_text(encoding="utf-8")
            self.assertIn("complete_positive_set", gold_sets)
            saved_manifest = json.loads((Path(temp_dir) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["asset_version"], "gold-v1")


if __name__ == "__main__":
    unittest.main()
