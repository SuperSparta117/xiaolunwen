from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH, POI_PATH
from .features import pair_features
from .geo_asset import attach_geo, load_poi_asset
from .io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction
from .poi_candidate import GeoCandidateIndex


FEATURE_FIELDS = [
    "query_id", "candidate_id", "label", "split", "provenance", "match_type", "confidence",
    "name_exact", "name_similarity", "address_similarity", "area_match", "street_match",
    "coords_available", "coords_trust_both", "poi_distance_m", "poi_distance_lt_100m",
    "poi_distance_100_300m", "poi_distance_300_1000m", "poi_distance_gt_1000m",
    "poi_district_match", "type_match",
]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rows(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
            count += 1
    return count


def build_pair_feature_assets(
    output_dir: Path,
    *,
    split_manifest_path: Path,
    query_limit: int | None = None,
    candidate_limit: int | None = None,
    mapping_limit: int | None = None,
    split_seed: int = 13,
    negative_ratio: int = 3,
    seed: int = 42,
    candidate_source: str = "text_only",
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    query_raw = read_sql_sample(A_QUERY_PATH, query_limit or 10_000_000)
    candidate_raw = read_csv_sample(A_CANDIDATE_PATH, candidate_limit or 10_000_000)
    with MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        mappings = list(csv.DictReader(handle))[:mapping_limit]
    with split_manifest_path.open("r", encoding="utf-8") as handle:
        split_manifest = json.load(handle)
    split_data = split_manifest["seed_manifests"][str(split_seed)]
    query_splits = split_data["query_splits"]
    candidate_splits = split_data["candidate_splits"]

    poi_index, poi_manifest = load_poi_asset(POI_PATH)
    queries = [attach_geo(standardize_property(row), "property", poi_index) for row in query_raw]
    candidates = [attach_geo(standardize_transaction(row), "transaction", poi_index) for row in candidate_raw]
    query_by_id = {str(row.get("id", "")): row for row in queries}
    candidate_by_id = {str(row.get("id", "")): row for row in candidates}

    positives: list[dict[str, object]] = []
    gold_by_query: dict[str, set[str]] = defaultdict(set)
    for row in mappings:
        query_id = str(row.get("sql_village_id", "")).strip()
        candidate_id = str(row.get("csv_yuyue_id", "")).strip()
        if not query_id or not candidate_id or query_id not in query_by_id or candidate_id not in candidate_by_id:
            continue
        provenance = "original_annotation" if row.get("source") == "原始标注" else "external_derived"
        gold_by_query[query_id].add(candidate_id)
        positives.append({
            "query_id": query_id, "candidate_id": candidate_id, "label": 1,
            "provenance": provenance, "match_type": row.get("match_type", ""),
            "confidence": row.get("confidence", ""),
        })

    geo_index = GeoCandidateIndex(candidates)
    feature_rows: list[dict[str, object]] = []
    negative_counts: Counter[str] = Counter()
    positive_by_query: dict[str, list[dict[str, object]]] = defaultdict(list)
    for pair in positives:
        positive_by_query[str(pair["query_id"])].append(pair)

    for query_id, gold_candidates in gold_by_query.items():
        query = query_by_id[query_id]
        split = query_splits.get(query_id)
        if not split:
            continue
        for pair in positive_by_query[query_id]:
            candidate = candidate_by_id[str(pair["candidate_id"])]
            feature_rows.append({**pair, "split": split, **pair_features(query, candidate)})

        split_candidates = [
            candidate for candidate in candidates
            if candidate_splits.get(str(candidate.get("id", ""))) == split
        ]
        negative_ids: list[str] = []
        if candidate_source in {"poi", "full"}:
            for item in geo_index.poi_candidates(query, k=max(negative_ratio * 10, 30)):
                candidate_id = str(item["id"])
                if candidate_id not in gold_candidates and candidate_splits.get(candidate_id) == split:
                    negative_ids.append(candidate_id)
        if candidate_source in {"text_only", "full"}:
            # Name-near candidates create challenging negatives for measuring name shortcut reliance.
            from .normalize import similarity
            ranked = sorted(
                split_candidates,
                key=lambda candidate: similarity(query.get("name"), candidate.get("name")),
                reverse=True,
            )
            negative_ids.extend(
                str(candidate["id"]) for candidate in ranked
                if str(candidate["id"]) not in gold_candidates and similarity(query.get("name"), candidate.get("name")) > 0
            )
        if candidate_source in {"admin", "full"}:
            negative_ids.extend(
                str(candidate["id"]) for candidate in split_candidates
                if candidate.get("area") and candidate.get("area") == query.get("area") and str(candidate["id"]) not in gold_candidates
            )
        selected = list(dict.fromkeys(negative_ids))[:negative_ratio * max(1, len(gold_candidates))]
        for candidate_id in selected:
            candidate = candidate_by_id[candidate_id]
            feature_rows.append({
                "query_id": query_id, "candidate_id": candidate_id, "label": 0,
                "split": split, "provenance": "constructed_negative",
                "match_type": f"{candidate_source}_hard_negative", "confidence": "protocol_constructed",
                **pair_features(query, candidate),
            })
            negative_counts[split] += 1

    output_files = {}
    for split in ("train", "validation", "test"):
        rows = [row for row in feature_rows if row.get("split") == split]
        path = output_dir / f"pairs_{split}.csv"
        count = _write_rows(path, FEATURE_FIELDS, rows)
        output_files[path.name] = {"rows": count, "sha256": _hash(path)}

    manifest = {
        "task_id": "A", "split_seed": split_seed, "negative_ratio": negative_ratio,
        "candidate_source": candidate_source,
        "source_hashes": {str(path): _hash(path) for path in (A_QUERY_PATH, A_CANDIDATE_PATH, MAPPING_PATH, POI_PATH, split_manifest_path)},
        "poi": poi_manifest, "positive_pairs": len(positives),
        "negative_pairs_by_split": dict(negative_counts), "split_files": output_files,
        "feature_fields": FEATURE_FIELDS,
        "feature_policy": {
            "POI_distance_only_when_both_coordinates_trusted": True,
            "unknown_queries_used_as_negatives": False,
            "negative_candidates_restricted_to_same_split": True,
            "candidate_source": candidate_source,
            "area_match_uses_alias_equivalence": True,
            "poi_district_match_uses_alias_equivalence": True,
            "street_match_uses_administrative_street": True,
            "street_source": {
                "property": "业务字段 street_name",
                "transaction": "POI 资产 乡镇街道（逆地理编码 township）",
            },
            "address_similarity_structurally_zero": "query 侧源表无地址列，恒 0；无合法对称替代",
        },
    }
    (output_dir / "feature_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
