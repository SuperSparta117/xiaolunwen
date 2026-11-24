from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH, POI_PATH
from .io import load_poi_sample, read_csv_sample, read_sql_sample


PAIR_FIELDS = [
    "query_id",
    "candidate_id",
    "gold_status",
    "relation_granularity",
    "provenance",
    "evidence_source_id",
    "source_label",
    "match_type",
    "confidence",
    "distance_m",
    "name_sim",
    "note",
    "annotator_or_script_version",
    "verified_at",
    "split",
]
QUERY_FIELDS = [
    "query_id",
    "query_label_state",
    "label_completeness",
    "negative_evidence_status",
    "review_status",
    "coordinate_status",
    "gold_candidate_count",
    "gold_provenance",
]
SET_FIELDS = ["query_id", "gold_candidate_ids", "gold_count", "query_label_state", "provenance"]


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, object]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _text(row.get(field, "")) for field in fieldnames})
            count += 1
    return count


def _read_mapping(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _source_provenance(value: str) -> str:
    # 只转换当前数据中已经出现的来源；未知来源不静默归类。
    if value == "原始标注":
        return "original_annotation"
    if value in {"外源数据补全", "外源坐标补全"}:
        return "external_derived"
    return "unknown_provenance"


def _relation_granularity(match_type: str) -> str:
    if match_type == "整体名称+期次覆盖(多对一)":
        return "project_contains_phase"
    if match_type == "同名+空间重合" or match_type == "同名+近距":
        return "physical_place_match"
    if match_type == "名称变体+空间重合":
        return "physical_place_match_name_variant"
    if match_type == "精确匹配":
        return "exact_or_business_pair"
    return "unclassified"


def _coordinate_status(query_id: str, poi_by_id: Mapping[str, Mapping[str, str]]) -> str:
    row = poi_by_id.get(query_id)
    if not row:
        return "unavailable"
    trusted = _text(row.get("可信")).lower() == "true"
    if trusted:
        return "trusted"
    if _text(row.get("经度")) and _text(row.get("纬度")):
        return "untrusted"
    return "unavailable"


def _query_rows(limit: int | None) -> list[dict[str, str]]:
    # SQL reader 已按 limit 停止；None 时用文件中的实际记录数。
    if limit is not None:
        return read_sql_sample(A_QUERY_PATH, limit)
    return read_sql_sample(A_QUERY_PATH, 10_000_000)


def _candidate_rows(limit: int | None) -> list[dict[str, str]]:
    if limit is None:
        return read_csv_sample(A_CANDIDATE_PATH, 10_000_000)
    return read_csv_sample(A_CANDIDATE_PATH, limit)


def build_evaluation_assets(
    output_dir: Path,
    *,
    query_limit: int | None = None,
    candidate_limit: int | None = None,
    mapping_limit: int | None = None,
    version: str = "gold-v1",
) -> dict[str, object]:
    """生成 A 任务的可审计金标准和评测资产。

    这是资产生成阶段，不执行候选召回，也不构造确认空集。mapping 未覆盖的
    query 统一写成 unknown，直到有独立排除证据才能升级为 confirmed_empty。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mappings = _read_mapping(MAPPING_PATH, mapping_limit)
    query_rows = _query_rows(query_limit)
    candidate_rows = _candidate_rows(candidate_limit)
    poi_rows = load_poi_sample(POI_PATH, 10_000_000)
    poi_by_id = {str(row.get("记录ID", "")): row for row in poi_rows if row.get("表") == "物业处"}

    pair_by_query: dict[str, list[dict[str, str]]] = defaultdict(list)
    pair_rows: list[dict[str, str]] = []
    for mapping in mappings:
        query_id = _text(mapping.get("sql_village_id"))
        candidate_id = _text(mapping.get("csv_yuyue_id"))
        if not query_id or not candidate_id:
            continue
        provenance = _source_provenance(_text(mapping.get("source")))
        pair = {
            "query_id": query_id,
            "candidate_id": candidate_id,
            "gold_status": "positive",
            "relation_granularity": _relation_granularity(_text(mapping.get("match_type"))),
            "provenance": provenance,
            "evidence_source_id": _text(mapping.get("source")),
            "source_label": _text(mapping.get("source")),
            "match_type": _text(mapping.get("match_type")),
            "confidence": _text(mapping.get("confidence")),
            "distance_m": _text(mapping.get("distance_m")),
            "name_sim": _text(mapping.get("name_sim")),
            "note": _text(mapping.get("note")),
            "annotator_or_script_version": _text(mapping.get("confidence")) or version,
            "verified_at": "",
            "split": "unassigned",
        }
        pair_rows.append(pair)
        pair_by_query[query_id].append(pair)

    # 同一 query 的重复 pair 不能重复进入 gold_set；pair 资产保留原始行以便审计。
    set_rows: list[dict[str, object]] = []
    eval_rows: list[dict[str, object]] = []
    for query in query_rows:
        query_id = _text(query.get("village_id"))
        pairs = pair_by_query.get(query_id, [])
        candidate_ids = list(dict.fromkeys(pair["candidate_id"] for pair in pairs))
        provenances = list(dict.fromkeys(pair["provenance"] for pair in pairs))
        state = "complete_positive_set" if candidate_ids else "unknown"
        set_rows.append({
            "query_id": query_id,
            "gold_candidate_ids": json.dumps(candidate_ids, ensure_ascii=False),
            "gold_count": len(candidate_ids),
            "query_label_state": state,
            "provenance": json.dumps(provenances, ensure_ascii=False),
        })
        eval_rows.append({
            "query_id": query_id,
            "query_label_state": state,
            "label_completeness": "complete" if candidate_ids else "not_verified",
            "negative_evidence_status": "not_applicable" if candidate_ids else "not_available",
            "review_status": "mapping_present" if candidate_ids else "needs_independent_review",
            "coordinate_status": _coordinate_status(query_id, poi_by_id),
            "gold_candidate_count": len(candidate_ids),
            "gold_provenance": json.dumps(provenances, ensure_ascii=False),
        })

    assets = {
        "gold_pairs.csv": _write_csv(output_dir / "gold_pairs.csv", PAIR_FIELDS, pair_rows),
        "gold_sets.csv": _write_csv(output_dir / "gold_sets.csv", SET_FIELDS, set_rows),
        "evaluation_queries.csv": _write_csv(output_dir / "evaluation_queries.csv", QUERY_FIELDS, eval_rows),
    }
    input_paths = [MAPPING_PATH, A_QUERY_PATH, A_CANDIDATE_PATH, POI_PATH]
    query_pair_counts = Counter(pair["query_id"] for pair in pair_rows)
    pair_keys = [(pair["query_id"], pair["candidate_id"]) for pair in pair_rows]
    pair_key_counts = Counter(pair_keys)
    mapping_integrity = {
        "mapping_rows_read": len(mappings),
        "distinct_query_ids_in_mapping": len(query_pair_counts),
        "distinct_candidate_ids_in_mapping": len({pair["candidate_id"] for pair in pair_rows}),
        "duplicate_query_id_rows": sum(max(count - 1, 0) for count in query_pair_counts.values()),
        "duplicate_pair_rows": sum(max(count - 1, 0) for count in pair_key_counts.values()),
        "multi_pair_query_count": sum(count > 1 for count in query_pair_counts.values()),
        "max_pairs_per_query": max(query_pair_counts.values(), default=0),
    }
    manifest = {
        "asset_version": version,
        "task_id": "A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_limits": {"query": query_limit, "candidate": candidate_limit, "mapping": mapping_limit},
        "input_files": {str(path): sha256_file(path) for path in input_paths},
        "mapping_integrity": mapping_integrity,
        "output_files": {name: {"rows": count, "sha256": sha256_file(output_dir / name)} for name, count in assets.items()},
        "counts": {
            "query_rows": len(query_rows),
            "candidate_rows": len(candidate_rows),
            "gold_pair_rows": len(pair_rows),
            "positive_query_rows": sum(bool(pair_by_query.get(_text(row.get("village_id")))) for row in query_rows),
            "unknown_query_rows": sum(not bool(pair_by_query.get(_text(row.get("village_id")))) for row in query_rows),
            "confirmed_empty_query_rows": 0,
        },
        "provenance_counts": {
            "original_annotation": sum(pair["provenance"] == "original_annotation" for pair in pair_rows),
            "external_derived": sum(pair["provenance"] == "external_derived" for pair in pair_rows),
            "unknown_provenance": sum(pair["provenance"] == "unknown_provenance" for pair in pair_rows),
        },
        "match_type_counts": dict(Counter(pair["match_type"] for pair in pair_rows)),
        "confidence_counts": dict(Counter(pair["confidence"] for pair in pair_rows)),
        "label_policy": {
            "unknown_is_confirmed_empty": False,
            "confirmed_empty_requires": "independent_exclusion_evidence",
            "test_labels_used_for_calibration": False,
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
