"""全库协议的共享数据加载：查询、候选、split、金标准。

供 full_library 与新增基线复用，保证两种入口使用完全相同的记录、ID 与划分。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH, POI_PATH
from .geo_asset import attach_geo, load_poi_asset
from .io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction


def load_full_library_data(data_dir: Path, split_seed: int = 13) -> dict[str, object]:
    query_rows = read_sql_sample(A_QUERY_PATH, 10_000_000)
    candidate_rows = read_csv_sample(A_CANDIDATE_PATH, 10_000_000)
    poi_index, poi_manifest = load_poi_asset(POI_PATH)
    queries = {
        str(row["village_id"]): attach_geo(standardize_property(row), "property", poi_index)
        for row in query_rows
    }
    candidates = [attach_geo(standardize_transaction(row), "transaction", poi_index) for row in candidate_rows]

    with MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        mapping = list(csv.DictReader(handle))
    gold_by_query: dict[str, set[str]] = defaultdict(set)
    for row in mapping:
        query_id = str(row.get("sql_village_id", "")).strip()
        candidate_id = str(row.get("csv_yuyue_id", "")).strip()
        if query_id in queries and candidate_id:
            gold_by_query[query_id].add(candidate_id)

    split_path = data_dir.parent / "split_manifest_full" / "split_manifest.json"
    split_manifest = json.loads(split_path.read_text(encoding="utf-8"))
    split = split_manifest["seed_manifests"][str(split_seed)]["query_splits"]
    validation_ids = sorted(
        query_id for query_id, part in split.items() if part == "validation" and query_id in gold_by_query
    )
    test_ids = sorted(
        query_id for query_id, part in split.items() if part == "test" and query_id in gold_by_query
    )
    return {
        "queries": queries,
        "candidates": candidates,
        "gold_by_query": dict(gold_by_query),
        "validation_ids": validation_ids,
        "test_ids": test_ids,
        "poi_manifest": poi_manifest,
        "split_seed": split_seed,
    }
