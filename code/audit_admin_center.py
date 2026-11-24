"""只读审计：行政中心解析覆盖率、歧义、区县冲突与重复行。

输出 code/geo_assets/admin_center_audit.json。
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
csv.field_size_limit(2 ** 31 - 1)

from er.config import A_CANDIDATE_PATH, A_QUERY_PATH, POI_PATH  # noqa: E402
from er.geo_asset import (  # noqa: E402
    _area_equivalent,
    _text,
    admin_center_index,
    attach_geo,
    load_poi_asset,
)
from er.io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction  # noqa: E402


def _summarize(records: list[dict[str, object]]) -> dict[str, object]:
    methods = Counter(str(record.get("admin_resolution_method") or "") for record in records)
    resolved = [record for record in records if record.get("admin_resolved")]
    centers = [(float(record["admin_lng"]), float(record["admin_lat"])) for record in resolved]
    unresolved_samples = [
        {"id": record.get("id"), "area": record.get("area"), "street": record.get("street")}
        for record in records
        if not record.get("admin_resolved")
    ][:20]
    return {
        "total": len(records),
        "resolved": len(resolved),
        "resolved_rate": round(len(resolved) / len(records), 4) if records else 0.0,
        "methods": dict(methods),
        "ambiguous": int(methods.get("exact_ambiguous", 0) + methods.get("suffix_ambiguous", 0)),
        "unresolved_samples": unresolved_samples,
        "center_lng_range": [round(min(c[0] for c in centers), 6), round(max(c[0] for c in centers), 6)] if centers else None,
        "center_lat_range": [round(min(c[1] for c in centers), 6), round(max(c[1] for c in centers), 6)] if centers else None,
    }


def main() -> None:
    poi_index, _ = load_poi_asset(POI_PATH)
    queries = [
        attach_geo(standardize_property(row), "property", poi_index)
        for row in read_sql_sample(A_QUERY_PATH, 10_000_000)
    ]
    candidates = [
        attach_geo(standardize_transaction(row), "transaction", poi_index)
        for row in read_csv_sample(A_CANDIDATE_PATH, 10_000_000)
    ]
    _, admin_manifest = admin_center_index()

    district_conflicts = [
        {"id": candidate.get("id"), "area": candidate.get("area"), "poi_district": candidate.get("poi_district")}
        for candidate in candidates
        if _text(candidate.get("area")) and not _area_equivalent(candidate.get("area"), candidate.get("poi_district"))
    ]
    district_missing = [candidate.get("id") for candidate in candidates if not _text(candidate.get("area"))]

    report = {
        "asset": admin_manifest,
        "query_side": _summarize(queries),
        "candidate_side": _summarize(candidates),
        "query_center_unresolved_examples": [
            {"id": record.get("id"), "area": record.get("area"), "street": record.get("street")}
            for record in queries
            if not record.get("admin_resolved")
        ][:20],
        "candidate_district_conflicts": {
            "count": len(district_conflicts),
            "samples": district_conflicts[:20],
        },
        "candidate_district_missing": {"count": len(district_missing), "samples": district_missing[:20]},
    }
    output = ROOT / "code" / "geo_assets"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "admin_center_audit.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("query:", report["query_side"]["resolved"], "/", report["query_side"]["total"], report["query_side"]["methods"])
    print("candidate:", report["candidate_side"]["resolved"], "/", report["candidate_side"]["total"], report["candidate_side"]["methods"])
    print("district conflicts:", len(district_conflicts), " missing:", len(district_missing))
    print("duplicate unit rows:", len(admin_manifest["duplicate_unit_rows"]))
    print("written:", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
