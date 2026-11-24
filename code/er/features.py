from __future__ import annotations

from typing import Mapping

from .geo import as_point, haversine_m
from .geo_asset import _area_equivalent
from .normalize import normalize_address, normalize_name, similarity, street_key


def pair_features(query: Mapping[str, object], candidate: Mapping[str, object]) -> dict[str, float | int | None]:
    q_name, b_name = normalize_name(query.get("name")), normalize_name(candidate.get("name"))
    q_addr, b_addr = normalize_address(query.get("address")), normalize_address(candidate.get("address"))
    q_street, b_street = street_key(query.get("street")), street_key(candidate.get("street"))
    q_point = as_point(query) if query.get("coords_trust") else None
    b_point = as_point(candidate) if candidate.get("coords_trust") else None
    distance = haversine_m(q_point, b_point)
    q_poi = q_point
    b_poi = b_point
    return {
        "name_exact": int(bool(q_name and q_name == b_name)),
        "name_similarity": similarity(q_name, b_name),
        "address_similarity": similarity(q_addr, b_addr),
        # 行政层：区县/街道都按行政区划口径比，不按文本相似度
        "area_match": int(_area_equivalent(query.get("area"), candidate.get("area"))),
        "street_match": int(bool(q_street and b_street and q_street == b_street)),
        "coords_available": int(distance is not None),
        "coords_trust_both": int(bool(query.get("coords_trust") and candidate.get("coords_trust"))),
        "poi_distance_m": distance,
        "poi_distance_lt_100m": int(distance is not None and distance < 100),
        "poi_distance_100_300m": int(distance is not None and 100 <= distance < 300),
        "poi_distance_300_1000m": int(distance is not None and 300 <= distance < 1000),
        "poi_distance_gt_1000m": int(distance is not None and distance >= 1000),
        "poi_district_match": int(_area_equivalent(query.get("poi_district"), candidate.get("poi_district"))),
        "type_match": int(bool(query.get("type") and query.get("type") == candidate.get("type"))),
    }
