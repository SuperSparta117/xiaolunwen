import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.geo_asset import (
    _area_equivalent,
    _trusted,
    load_admin_asset,
    load_poi_asset,
    reset_admin_center_cache,
    resolve_admin_center,
)
from er.poi_candidate import GeoCandidateIndex


class TestGeoAsset(unittest.TestCase):
    def test_trust_requires_level_district_and_bbox(self):
        base = {"经度": "106.5", "纬度": "29.5", "level": "住宅区", "区县": "江北区", "高德区县": "江北区"}
        self.assertEqual(_trusted(base), (True, ""))
        self.assertEqual(_trusted({**base, "高德区县": "沙坪坝区"})[1], "district_mismatch")
        self.assertEqual(_trusted({**base, "经度": "121.5"})[1], "outside_chongqing_bbox")
        self.assertEqual(_trusted({**base, "level": "道路"})[1], "untrusted_level")
        self.assertTrue(_area_equivalent("江北区", "两江新区"))
        # 自治县简称：缺这条会把正确配对误判为区县冲突（实测 66 条）
        self.assertTrue(_area_equivalent("酉阳县", "酉阳土家族苗族自治县"))
        self.assertTrue(_area_equivalent("秀山县", "秀山土家族苗族自治县"))
        self.assertTrue(_area_equivalent("彭水县", "彭水苗族土家族自治县"))
        # 功能区代管
        self.assertTrue(_area_equivalent("北碚区", "两江新区"))
        self.assertTrue(_area_equivalent("高新区", "沙坪坝区"))
        self.assertTrue(_area_equivalent("经开区", "南岸区"))
        self.assertFalse(_area_equivalent("渝北区", "沙坪坝区"))

    def test_admin_center_resolution(self):
        reset_admin_center_cache()
        # 精确原名优先：南坪街道与南坪镇是两个不同的行政单元
        street = resolve_admin_center("南岸区", "南坪街道")
        town = resolve_admin_center("南岸区", "南坪镇")
        self.assertEqual(street["method"], "exact")
        self.assertEqual(town["method"], "exact")
        self.assertNotEqual(street["unit_id"], town["unit_id"])
        # 等价区县族内同名重复行归为同一单元（双桥经开区 ≡ 大足区）
        left = resolve_admin_center("双桥经开区", "通桥街道")
        right = resolve_admin_center("大足区", "通桥街道")
        self.assertEqual(left["unit_id"], right["unit_id"])
        self.assertEqual(left["center"], right["center"])
        # 区县等价兜底：江北区没有大石坝街道，走两江新区
        dabashi = resolve_admin_center("江北区", "大石坝街道")
        self.assertIsNotNone(dabashi["center"])
        self.assertEqual(dabashi["unit_id"][1], "大石坝街道")
        # 全局唯一回退
        self.assertEqual(resolve_admin_center("渝中区", "大石坝街道")["method"], "global_unique")
        # 脏字段：区县是脏值，不能解析
        self.assertIsNone(resolve_admin_center("二期", "潼南区")["center"])

    def test_assets_and_trusted_poi_grid(self):
        poi, poi_report = load_poi_asset()
        admin, admin_report = load_admin_asset()
        self.assertEqual(poi_report["all_records"], 12042)
        self.assertEqual(poi_report["duplicate_keys"], 0)
        self.assertEqual(admin_report["indexed_records"], 1094)
        self.assertGreater(len(admin), 0)
        trusted_rows = [
            {"id": "a", "lng": 106.5, "lat": 29.5, "coords_trust": True},
            {"id": "b", "lng": 106.501, "lat": 29.501, "coords_trust": True},
            {"id": "c", "lng": 121.5, "lat": 31.2, "coords_trust": False},
        ]
        index = GeoCandidateIndex(trusted_rows)
        result = index.poi_candidates(trusted_rows[0], k=10)
        self.assertEqual({row["id"] for row in result}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
