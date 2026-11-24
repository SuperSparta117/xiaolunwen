from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .candidate import CandidateIndex
from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH
from .io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction
from .mask import mask_primary_fields


POOL_FIELDS = [
    "query_id",
    "candidate_id",
    "recall_sources",
    "recall_rank",
    "recall_score",
    "candidate_pool_version",
    "gold_in_pool",
]

RECALL_FIELDS = [
    "k",
    "query_recall",
    "pair_recall",
    "gold_query_count",
    "gold_pair_count",
    "recalled_query_count",
    "recalled_pair_count",
    "unknown_query_count",
    "provenance",
]


def _read_mapping(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_recall_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECALL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _recall_rows(
    query_ids: set[str],
    gold_by_query: dict[str, set[str]],
    pool_by_query: dict[str, list[dict[str, object]]],
    ks: Iterable[int],
    provenance_by_pair: dict[tuple[str, str], str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for k in ks:
        for provenance in ["all", "original_annotation", "external_derived"]:
            eligible = {
                query_id: {
                    candidate_id
                    for candidate_id in candidate_ids
                    if provenance == "all" or provenance_by_pair.get((query_id, candidate_id)) == provenance
                }
                for query_id, candidate_ids in gold_by_query.items()
                if query_id in query_ids
            }
            eligible = {query_id: ids for query_id, ids in eligible.items() if ids}
            recalled_by_query = {
                query_id: ids & {
                    str(row["candidate_id"])
                    for row in pool_by_query.get(query_id, [])
                    if int(row["recall_rank"]) <= k
                }
                for query_id, ids in eligible.items()
            }
            gold_pair_count = sum(len(ids) for ids in eligible.values())
            recalled_pair_count = sum(len(ids) for ids in recalled_by_query.values())
            rows.append({
                "k": k,
                "query_recall": round(sum(bool(ids) for ids in recalled_by_query.values()) / len(eligible), 6) if eligible else "",
                "pair_recall": round(recalled_pair_count / gold_pair_count, 6) if gold_pair_count else "",
                "gold_query_count": len(eligible),
                "gold_pair_count": gold_pair_count,
                "recalled_query_count": sum(bool(ids) for ids in recalled_by_query.values()),
                "recalled_pair_count": recalled_pair_count,
                "unknown_query_count": len(query_ids - set(eligible)),
                "provenance": provenance,
            })
    return rows


def build_candidate_pool(
    output_dir: Path,
    *,
    query_limit: int | None = None,
    candidate_limit: int | None = None,
    mapping_limit: int | None = None,
    k: int = 20,
    version: str = "candidate-v1",
    channel: str = "union",
    mask_ratio: float = 0.0,
    mask_seed: int = 42,
    protocol: str = "natural",
) -> dict[str, object]:
    """为 A 任务生成可审计候选池；不会把 unknown 变成负例。"""
    if protocol not in {"natural", "fixed_pool", "end_to_end"}:
        raise ValueError("protocol must be natural, fixed_pool, or end_to_end")
    if not 0.0 <= mask_ratio <= 1.0:
        raise ValueError("mask_ratio must be between 0 and 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    query_raw = read_sql_sample(A_QUERY_PATH, query_limit or 10_000_000)
    candidate_raw = read_csv_sample(A_CANDIDATE_PATH, candidate_limit or 10_000_000)
    mappings = _read_mapping(MAPPING_PATH, mapping_limit)

    queries = [standardize_property(row) for row in query_raw]
    candidates = [standardize_transaction(row) for row in candidate_raw]
    if protocol == "end_to_end" and mask_ratio:
        queries = [mask_primary_fields(row, mask_ratio, mask_seed) for row in queries]
        candidates = [mask_primary_fields(row, mask_ratio, mask_seed) for row in candidates]
    candidate_index = CandidateIndex(candidates)
    gold_by_query: dict[str, set[str]] = defaultdict(set)
    provenance_by_pair: dict[tuple[str, str], str] = {}
    for row in mappings:
        query_id = str(row.get("sql_village_id", "")).strip()
        candidate_id = str(row.get("csv_yuyue_id", "")).strip()
        source = str(row.get("source", "")).strip()
        provenance = "original_annotation" if source == "原始标注" else ("external_derived" if source in {"外源数据补全", "外源坐标补全"} else "unknown_provenance")
        if query_id and candidate_id:
            gold_by_query[query_id].add(candidate_id)
            provenance_by_pair[(query_id, candidate_id)] = provenance

    pool_rows: list[dict[str, object]] = []
    pool_by_query: dict[str, list[dict[str, object]]] = defaultdict(list)
    channel_pool_rows: list[dict[str, object]] = []
    query_recall: dict[str, bool] = {}
    for query in queries:
        query_id = str(query.get("id", ""))
        pool = candidate_index.generate(query, k=k, channel="union")
        query_recall[query_id] = bool(gold_by_query.get(query_id, set()) & {str(row.get("id", "")) for row in pool})
        for channel in ("name_ngram", "address_ngram", "area", "union"):
            channel_pool = candidate_index.generate(query, k=k, channel=channel)
            for rank, row in enumerate(channel_pool, start=1):
                channel_pool_rows.append({
                    "query_id": query_id,
                    "candidate_id": str(row.get("id", "")),
                    "channel": channel,
                    "recall_rank": rank,
                    "gold_in_pool": str(str(row.get("id", "")) in gold_by_query.get(query_id, set())).lower(),
                })
        for rank, row in enumerate(pool, start=1):
            candidate_id = str(row.get("id", ""))
            pool_rows.append({
                "query_id": query_id,
                "candidate_id": candidate_id,
                "recall_sources": json.dumps(row.get("_recall_sources", []), ensure_ascii=False),
                "recall_rank": rank,
                "recall_score": row.get("_recall_score", 0),
                "candidate_pool_version": version,
                "gold_in_pool": str(candidate_id in gold_by_query.get(query_id, set())).lower(),
            })
            pool_by_query[query_id].append({"candidate_id": candidate_id, "recall_rank": rank})

    pool_path = output_dir / "candidate_pool.csv"
    with pool_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POOL_FIELDS)
        writer.writeheader()
        writer.writerows(pool_rows)

    recall_rows = _recall_rows(
        {str(query.get("id", "")) for query in queries},
        gold_by_query,
        pool_by_query,
        sorted({1, 5, 10, 20, 50, 100, k}),
        provenance_by_pair,
    )
    recall_path = output_dir / "candidate_recall_at_k.csv"
    _write_recall_csv(recall_path, recall_rows)

    channel_path = output_dir / "candidate_recall_by_channel.csv"
    channel_fields = ["channel", "k", "query_recall", "pair_recall", "gold_query_count", "gold_pair_count", "recalled_query_count", "recalled_pair_count", "unknown_query_count"]
    channel_recall_rows: list[dict[str, object]] = []
    for channel in ("name_ngram", "address_ngram", "area", "union"):
        channel_rows = [row for row in channel_pool_rows if row["channel"] == channel]
        channel_by_query: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in channel_rows:
            channel_by_query[str(row["query_id"])].append(row)
        for recall_row in _recall_rows(
            {str(query.get("id", "")) for query in queries},
            gold_by_query,
            channel_by_query,
            sorted({1, 5, 10, 20, 50, 100, k}),
            provenance_by_pair,
        ):
            channel_recall_rows.append({"channel": channel, **{key: value for key, value in recall_row.items() if key != "provenance"}})
    with channel_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=channel_fields)
        writer.writeheader()
        writer.writerows(channel_recall_rows)

    gold_queries = {query_id for query_id, ids in gold_by_query.items() if ids}
    evaluated_gold_queries = gold_queries & {str(query.get("id", "")) for query in queries}
    mask_counts = {
        "query_masked": sum(bool(query.get("_mask_applied")) for query in queries),
        "candidate_masked": sum(bool(candidate.get("_mask_applied")) for candidate in candidates),
    }
    manifest = {
        "candidate_pool_version": version,
        "task_id": "A",
        "protocol": protocol,
        "mask_counts": mask_counts,
        "k": k,
        "source_limits": {"query": query_limit, "candidate": candidate_limit, "mapping": mapping_limit},
        "input_files": {str(path): _sha256(path) for path in (A_QUERY_PATH, A_CANDIDATE_PATH, MAPPING_PATH)},
        "output_file": {"path": str(pool_path), "rows": len(pool_rows), "sha256": _sha256(pool_path)},
        "recall_file": {"path": str(recall_path), "rows": len(recall_rows), "sha256": _sha256(recall_path)},
        "channel_recall_file": {"path": str(channel_path), "rows": len(channel_recall_rows), "sha256": _sha256(channel_path)},
        "counts": {
            "query_rows": len(queries),
            "candidate_rows": len(candidates),
        "pool_rows": len(pool_rows),
        "gold_queries_in_sample": len(evaluated_gold_queries),
        "gold_queries_recalled": sum(query_recall.get(query_id, False) for query_id in evaluated_gold_queries),
        "gold_queries_not_recalled": sum(not query_recall.get(query_id, False) for query_id in evaluated_gold_queries),
        "unknown_queries_not_counted_as_negative": len(queries) - len(evaluated_gold_queries),
        },
        "policy": {
            "unknown_is_negative": False,
            "recall_failure_is_ranking_failure": False,
            "gold_set_definition": "mapping pairs available in the frozen mapping asset",
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
