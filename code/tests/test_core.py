import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.candidate import generate_candidates
from er.features import pair_features
from er.geo import haversine_m, in_chongqing
from er.model import baseline_score
from er.normalize import normalize_address, normalize_name, similarity
from er.output import predict_set


class TestCore(unittest.TestCase):
    def test_normalization_and_similarity(self):
        self.assertEqual(normalize_name(" 重庆市·龙湖花园一期 "), "重庆市龙湖花园一期")
        self.assertEqual(normalize_address("重庆市渝北区龙湖花园"), "渝北区龙湖花园")
        self.assertEqual(similarity("龙湖花园", "龙湖花园"), 1.0)

    def test_geo(self):
        self.assertAlmostEqual(haversine_m((106.5, 29.5), (106.5, 29.5)), 0.0)
        self.assertTrue(in_chongqing((106.5, 29.5)))
        self.assertFalse(in_chongqing((121.5, 31.2)))

    def test_candidate_channels_and_features(self):
        query = {"id": "q", "name": "龙湖花园一期", "area": "渝北区", "address": "重庆市龙湖花园", "street": "人和"}
        candidates = [
            {"id": "b1", "name": "龙湖花园", "area": "渝北区", "address": "龙湖花园", "street": "人和"},
            {"id": "b2", "name": "完全不同", "area": "江北区", "address": "其他", "street": ""},
        ]
        pool = generate_candidates(query, candidates, k=10)
        self.assertEqual(pool[0]["id"], "b1")
        self.assertIn("name_ngram", pool[0]["_recall_sources"])
        features = pair_features(query, pool[0])
        self.assertEqual(features["area_match"], 1)
        self.assertGreater(baseline_score(features), 0.5)

    def test_admin_layer_features(self):
        """行政层比对：街道去后缀、区县走别名/代管等价，地址仍按对称相似度（query 无地址时为 0）。"""
        query = {"id": "q", "name": "某小区", "area": "北碚区", "street": "蔡家岗街道",
                 "poi_district": "两江新区", "address": ""}
        cand = {"id": "b", "name": "另一个", "area": "两江新区", "street": "蔡家岗镇",
                "poi_district": "江北区", "address": "重庆市北碚区蔡家岗街道某号"}
        f = pair_features(query, cand)
        self.assertEqual(f["street_match"], 1)
        self.assertEqual(f["area_match"], 1)
        self.assertEqual(f["poi_district_match"], 1)
        self.assertEqual(f["address_similarity"], 0.0)

        different = {**cand, "street": "水土街道"}
        self.assertEqual(pair_features(query, different)["street_match"], 0)
        self.assertEqual(pair_features(query, {**cand, "street": ""})["street_match"], 0)

    def test_set_threshold(self):
        rows = [{"candidate_id": "a", "probability": 0.8}, {"candidate_id": "b", "probability": 0.2}]
        self.assertEqual([r["candidate_id"] for r in predict_set(rows, 0.72)], ["a"])


if __name__ == "__main__":
    unittest.main()
