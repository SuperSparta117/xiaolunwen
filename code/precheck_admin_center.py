"""阶段零：行政中心特征独立性预检（只读，复用正式解析器）。

输出 code/geo_assets/admin_center_precheck.json，不修改 v4 资产。
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
csv.field_size_limit(2 ** 31 - 1)

from er.config import A_CANDIDATE_PATH, A_QUERY_PATH, POI_PATH  # noqa: E402
from er.features import _admin_point  # noqa: E402
from er.geo import haversine_m  # noqa: E402
from er.geo_asset import attach_geo, load_poi_asset  # noqa: E402
from er.io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction  # noqa: E402


def _auc(pairs: list[tuple[float, int]]) -> float | None:
    """rank-based AUC，同分取平均秩。pairs 为 (score, label)。"""
    if not pairs:
        return None
    positives = sum(label for _, label in pairs)
    negatives = len(pairs) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(pairs)
    ranks: dict[float, list[float]] = defaultdict(list)
    position = 1
    for score, _ in ordered:
        ranks[score].append(position)
        position += 1
    score_rank = {score: sum(values) / len(values) for score, values in ranks.items()}
    positive_rank_sum = sum(score_rank[score] for score, label in ordered if label == 1)
    return (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _ks(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    positives = sorted(score for score, label in pairs if label == 1)
    negatives = sorted(score for score, label in pairs if label == 0)
    if not positives or not negatives:
        return None
    values = sorted({score for score, _ in pairs})
    best = 0.0
    for value in values:
        p = sum(1 for score in positives if score <= value) / len(positives)
        n = sum(1 for score in negatives if score <= value) / len(negatives)
        best = max(best, abs(p - n))
    return best


def main() -> None:
    poi_index, _ = load_poi_asset(POI_PATH)
    queries = {
        str(row["id"]): row
        for row in (
            attach_geo(standardize_property(item), "property", poi_index)
            for item in read_sql_sample(A_QUERY_PATH, 10_000_000)
        )
    }
    candidates = {
        str(row["id"]): row
        for row in (
            attach_geo(standardize_transaction(item), "transaction", poi_index)
            for item in read_csv_sample(A_CANDIDATE_PATH, 10_000_000)
        )
    }

    report: dict[str, object] = {"source": "training_assets_full_v4", "stratified": {}, "overall": {}}
    strata: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    same_strata: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    all_pairs: list[tuple[float, int]] = []
    coverage = {"pairs": 0, "both_resolved": 0}

    for split in ("train", "validation", "test"):
        with (ROOT / "code" / "training_assets_full_v4" / f"pairs_{split}.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            coverage["pairs"] += 1
            query = queries.get(str(row["query_id"]))
            candidate = candidates.get(str(row["candidate_id"]))
            if not query or not candidate:
                continue
            q_point, c_point = _admin_point(query), _admin_point(candidate)
            if q_point is None or c_point is None:
                continue
            coverage["both_resolved"] += 1
            distance = haversine_m(q_point, c_point)
            key = (row["area_match"], row["street_match"])
            label = int(row["label"])
            strata[key].append((distance, label))
            same = 1.0 if query.get("admin_unit_id") and query.get("admin_unit_id") == candidate.get("admin_unit_id") else 0.0
            same_strata[key].append((same, label))
            all_pairs.append((distance, label))

    report["coverage"] = {
        "pairs": coverage["pairs"],
        "both_resolved": coverage["both_resolved"],
        "both_resolved_rate": round(coverage["both_resolved"] / coverage["pairs"], 4) if coverage["pairs"] else 0.0,
    }
    report["overall"] = {"distance_auc": _auc(all_pairs), "distance_ks": _ks(all_pairs)}
    for key in sorted(strata):
        pairs = strata[key]
        positives = [score for score, label in pairs if label == 1]
        negatives = [score for score, label in pairs if label == 0]
        same_pairs = same_strata[key]
        report["stratified"][f"area={key[0]},street={key[1]}"] = {
            "pairs": len(pairs),
            "positive": len(positives),
            "negative": len(negatives),
            "distance_auc": _auc(pairs),
            "distance_ks": _ks(pairs),
            "distance_median_positive": sorted(positives)[len(positives) // 2] if positives else None,
            "distance_median_negative": sorted(negatives)[len(negatives) // 2] if negatives else None,
            "same_ratio_positive": sum(score for score, label in same_pairs if label == 1) / len(positives) if positives else None,
            "same_ratio_negative": sum(score for score, label in same_pairs if label == 0) / len(negatives) if negatives else None,
        }

    output = ROOT / "code" / "geo_assets"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "admin_center_precheck.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("coverage:", report["coverage"])
    print("overall:", report["overall"])
    for name, values in report["stratified"].items():
        print(name, values)
    print("written:", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
