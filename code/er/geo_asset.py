from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .config import ADMIN_PATH, POI_PATH
from .geo import CHONGQING_BBOX, as_point, haversine_m
from .normalize import clean, normalize_name

TRUSTED_LEVELS = {"住宅区", "兴趣点", "门址", "门牌号", "单元", "商务大厦"}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _bool(value: object) -> bool:
    return _text(value).lower() in {"true", "1", "yes", "是"}


def _area_equivalent(left: str, right: str) -> bool:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    aliases = {
        "石柱县": {"石柱土家族自治县"},
        "酉阳县": {"酉阳土家族苗族自治县"},
        "秀山县": {"秀山土家族苗族自治县"},
        "彭水县": {"彭水苗族土家族自治县"},
        "两江新区": {"渝北区", "江北区", "北碚区"},
        "渝北区": {"两江新区"},
        "江北区": {"两江新区"},
        "北碚区": {"两江新区"},
        "高新区": {"九龙坡区", "沙坪坝区"},
        "经开区": {"南岸区"},
        "万盛区": {"綦江区"},
        "万盛经开区": {"綦江区"},
        "双桥经开区": {"大足区"},
    }
    return b in {normalize_name(x) for x in aliases.get(a, set())} or a in {normalize_name(x) for x in aliases.get(b, set())}


def _in_bbox(lng: float, lat: float) -> bool:
    return CHONGQING_BBOX[0] <= lng <= CHONGQING_BBOX[1] and CHONGQING_BBOX[2] <= lat <= CHONGQING_BBOX[3]


def normalize_source(value: str) -> str:
    return "property" if value in {"物业处", "property"} else ("transaction" if value in {"房交", "transaction"} else value)


def _trusted(row: Mapping[str, str]) -> tuple[bool, str]:
    """复用冻结资产中的可信标记，同时保留本地规则的独立校验接口。"""
    if _text(row.get("可信")):
        return _bool(row.get("可信")), _text(row.get("不可信原因"))
    try:
        lng, lat = float(row.get("经度", "")), float(row.get("纬度", ""))
    except (TypeError, ValueError):
        return False, "missing_coordinate"
    if not _in_bbox(lng, lat):
        return False, "outside_chongqing_bbox"
    if _text(row.get("level")) not in TRUSTED_LEVELS:
        return False, "untrusted_level"
    if not _area_equivalent(_text(row.get("区县")), _text(row.get("高德区县"))):
        return False, "district_mismatch"
    return True, ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_poi_asset(path: Path = POI_PATH) -> tuple[dict[tuple[str, str], dict[str, object]], dict[str, object]]:
    rows = _read_csv(path)
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    trust_counts: defaultdict[str, int] = defaultdict(int)
    duplicates = 0
    for row in rows:
        source, record_id = normalize_source(_text(row.get("表"))), _text(row.get("记录ID"))
        if not source or not record_id:
            continue
        key = (source, record_id)
        if key in indexed:
            duplicates += 1
        trusted, reason = _trusted(row)
        indexed[key] = {
            "lng": float(row["经度"]) if _text(row.get("经度")) else None,
            "lat": float(row["纬度"]) if _text(row.get("纬度")) else None,
            "coords_trust": trusted,
            "coords_reason": reason,
            "poi_level": _text(row.get("level")),
            "poi_district": _text(row.get("高德区县")),
            "township": _text(row.get("乡镇街道")),
            "coord_source": _text(row.get("坐标来源")),
            "coord_system": _text(row.get("坐标系")),
            "formatted_address": _text(row.get("规范地址")),
            "raw": row,
        }
        trust_counts["trusted" if trusted else reason] += 1
    return indexed, {
        "asset": str(path),
        "sha256": _sha256(path),
        "all_records": len(rows),
        "indexed_records": len(indexed),
        "source_counts": dict(Counter(_text(row.get("表")) for row in rows)),
        "duplicate_keys": duplicates,
        "trust_counts": dict(trust_counts),
    }


def load_admin_asset(path: Path = ADMIN_PATH) -> tuple[dict[tuple[str, str], tuple[float, float]], dict[str, object]]:
    rows = _read_csv(path)
    indexed: dict[tuple[str, str], tuple[float, float]] = {}
    for row in rows:
        try:
            point = (float(row["中心经度"]), float(row["中心纬度"]))
        except (KeyError, ValueError):
            continue
        indexed[(normalize_name(row.get("区县")), normalize_name(row.get("行政区划")))] = point
    return indexed, {"asset": str(path), "sha256": _sha256(path), "rows": len(rows), "indexed_records": len(indexed)}


def attach_geo(row: Mapping[str, object], source: str, poi_index: Mapping[tuple[str, str], Mapping[str, object]]) -> dict[str, object]:
    result = dict(row)
    record_id = _text(row.get("id"))
    poi = poi_index.get((source, record_id))
    if poi:
        result.update({key: value for key, value in poi.items() if key != "raw"})
        # 统一记录视图的 street 取权威行政街道：房交 CSV 没有街道列，由逆地理编码的 township 补；
        # 物业处已有业务 street_name 时不覆盖。
        if not _text(result.get("street")) and poi.get("township"):
            result["street"] = poi["township"]
    else:
        result.update({"lng": None, "lat": None, "coords_trust": False, "coords_reason": "poi_not_found"})
    return result


def build_geo_manifest(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    poi_index, poi_manifest = load_poi_asset()
    admin_index, admin_manifest = load_admin_asset()
    report = {"poi": poi_manifest, "admin": admin_manifest, "admin_index_keys": len(admin_index)}
    (output_dir / "geo_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
