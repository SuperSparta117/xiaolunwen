import csv
import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.split import build_split_manifest


class TestSplit(unittest.TestCase):
    def test_components_never_cross_splits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping = Path(temp_dir) / "mapping.csv"
            mapping.write_text(
                "sql_village_id,csv_yuyue_id\nq1,c1\nq1,c2\nq2,c3\nq3,c4\nq4,c5\n",
                encoding="utf-8",
            )
            output = Path(temp_dir) / "out"
            manifest = build_split_manifest(
                output,
                mapping_path=mapping,
                seeds=(7,),
                ratios=(0.6, 0.2, 0.2),
            )
            with (output / "split_entities.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            by_component = {}
            for row in rows:
                by_component.setdefault(row["component_id"], set()).add(row["split"])
            self.assertTrue(all(len(splits) == 1 for splits in by_component.values()))
            self.assertEqual(manifest["counts"]["connected_components"], 4)
            seed = manifest["seed_manifests"]["7"]
            self.assertEqual(seed["query_splits"]["q1"], seed["candidate_splits"]["c1"])
            self.assertEqual(seed["query_splits"]["q1"], seed["candidate_splits"]["c2"])

    def test_fixed_seeds_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping = Path(temp_dir) / "mapping.csv"
            mapping.write_text("sql_village_id,csv_yuyue_id\nq1,c1\nq2,c2\nq3,c3\nq4,c4\n", encoding="utf-8")
            one = build_split_manifest(Path(temp_dir) / "one", mapping_path=mapping, seeds=(13,))
            two = build_split_manifest(Path(temp_dir) / "two", mapping_path=mapping, seeds=(13,))
            self.assertEqual(one["seed_manifests"]["13"]["query_splits"], two["seed_manifests"]["13"]["query_splits"])


if __name__ == "__main__":
    unittest.main()
