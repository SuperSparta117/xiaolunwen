from __future__ import annotations

import math
from typing import Mapping

CHONGQING_BBOX = (105.05, 110.45, 27.95, 32.55)


def as_point(row: Mapping[str, object]) -> tuple[float, float] | None:
    try:
        lng, lat = float(row.get("lng", "")), float(row.get("lat", ""))
    except (TypeError, ValueError):
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return lng, lat


def in_chongqing(point: tuple[float, float] | None) -> bool:
    if point is None:
        return False
    lng, lat = point
    return CHONGQING_BBOX[0] <= lng <= CHONGQING_BBOX[1] and CHONGQING_BBOX[2] <= lat <= CHONGQING_BBOX[3]


def haversine_m(left: tuple[float, float] | None, right: tuple[float, float] | None) -> float | None:
    if left is None or right is None:
        return None
    lng1, lat1, lng2, lat2 = map(math.radians, (*left, *right))
    d_lng, d_lat = lng2 - lng1, lat2 - lat1
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))
