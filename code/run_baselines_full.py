"""在全库候选协议上运行新增基线（Fellegi-Sunter / BM25F / BGE-M3 / Ditto）。

与全库 LightGBM 实验共享：同一批查询/候选、同一 split、同一遮蔽标记、同一 validation
阈值选择与 test 集合指标。输出 comparison CSV 与每个方法×rho 的分数矩阵（npz）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from er.baselines_classic import BM25FScorer, FellegiSunterScorer  # noqa: E402
from er.full_data import load_full_library_data  # noqa: E402
from er.full_library import (  # noqa: E402
    HISTOGRAM_BINS,
    SUMMARY_FIELDS,
    _aggregate_test_scores,
    entity_is_masked,
    threshold_from_histogram,
)

RATIOS = (0.0, 0.3, 0.6, 1.0)


def _read_pairs(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _mask_flags(ids: list[str], seed: int, rho: float) -> dict[str, bool]:
    return {entity_id: entity_is_masked(entity_id, seed, rho) for entity_id in ids}


def _build_matrix(scorer, ids, queries, candidates, masked_queries, masked_candidates) -> np.ndarray:
    matrix = np.zeros((len(ids), len(candidates)), dtype=np.float32)
    for row, query_id in enumerate(ids):
        matrix[row] = scorer.score_query(
            queries[query_id], candidates, masked_queries[query_id], masked_candidates
        )
    return matrix


def _normalize(validation: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    low, high = float(validation.min()), float(validation.max())
    if high - low < 1e-9:
        return np.zeros_like(validation), np.zeros_like(test)
    scale = high - low
    validation_norm = np.clip((validation - low) / scale, 0.0, 1.0)
    test_norm = np.clip((test - low) / scale, 0.0, 1.0)
    return validation_norm, test_norm


def _threshold(validation: np.ndarray, ids, gold_by_query, candidates) -> float:
    positive = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
    negative = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
    candidate_ids = np.array([str(candidate["id"]) for candidate in candidates])
    for row, query_id in enumerate(ids):
        gold = gold_by_query.get(query_id, set())
        labels = np.isin(candidate_ids, list(gold)).astype(bool)
        bins = np.minimum(HISTOGRAM_BINS - 1, (validation[row] * HISTOGRAM_BINS).astype(np.int64))
        positive += np.bincount(bins[labels], minlength=HISTOGRAM_BINS)
        negative += np.bincount(bins[~labels], minlength=HISTOGRAM_BINS)
    return threshold_from_histogram(positive, negative)


def _write_score_csv(path: Path, matrix: np.ndarray, ids, gold_by_query, candidates) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["query_id", "candidate_id", "label", "probability"])
        writer.writeheader()
        for row, query_id in enumerate(ids):
            gold = gold_by_query.get(query_id, set())
            for column, candidate in enumerate(candidates):
                candidate_id = str(candidate["id"])
                writer.writerow({
                    "query_id": query_id,
                    "candidate_id": candidate_id,
                    "label": int(candidate_id in gold),
                    "probability": float(matrix[row, column]),
                })


def _scorers(methods: list[str]):
    registry = {}
    if "fs" in methods:
        registry["fs"] = ("Fellegi-Sunter", FellegiSunterScorer)
    if "bm25f" in methods:
        registry["bm25f"] = ("BM25F", BM25FScorer)
    if "bge" in methods:
        from er.baselines_neural import BgeM3Scorer
        registry["bge"] = ("BGE-M3", BgeM3Scorer)
    if "ditto" in methods:
        from er.baselines_neural import DittoScorer
        registry["ditto"] = ("Ditto (Chinese RoBERTa)", DittoScorer)
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="全库协议下运行新增基线")
    parser.add_argument("--data-dir", type=Path, default=Path("code/training_assets_full_v5"))
    parser.add_argument("--output-dir", type=Path, default=Path("code/baseline_results_full"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".audit_work/baseline_cache"))
    parser.add_argument("--methods", type=str, default="fs,bm25f,bge,ditto")
    parser.add_argument("--ratios", type=str, default="0,0.3,0.6,1.0")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split-seed", type=int, default=13)
    args = parser.parse_args()

    methods = [name.strip() for name in args.methods.split(",") if name.strip()]
    ratios = tuple(float(value) for value in args.ratios.split(","))
    data = load_full_library_data(args.data_dir, split_seed=args.split_seed)
    queries = data["queries"]
    candidates = data["candidates"]
    gold = data["gold_by_query"]
    validation_ids = data["validation_ids"]
    test_ids = data["test_ids"]
    candidate_ids = [str(candidate["id"]) for candidate in candidates]
    training_pairs = _read_pairs(args.data_dir / "pairs_train.csv")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = args.output_dir / "baseline_comparison.csv"
    rows: list[dict[str, object]] = []
    if comparison_path.exists():
        with comparison_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    registry = _scorers(methods)
    for rho in ratios:
        masked_queries = _mask_flags(list(queries), args.seed, rho)
        masked_candidates_map = _mask_flags(candidate_ids, args.seed, rho)
        masked_candidates = [masked_candidates_map[candidate_id] for candidate_id in candidate_ids]
        for key, (method_name, factory) in registry.items():
            existing = [row for row in rows if row["method"] == method_name and abs(float(row["rho"]) - rho) < 1e-9]
            if existing:
                print(f"skip {method_name} rho={rho}（已有结果）", flush=True)
                continue
            print(f"run {method_name} rho={rho} ...", flush=True)
            scorer = factory()
            if key == "bm25f":
                scorer.fit(candidates, masked_candidates)
            else:
                scorer.fit(training_pairs, queries, candidates,
                           masked_queries=masked_queries, masked_candidates=masked_candidates)
            validation = _build_matrix(scorer, validation_ids, queries, candidates, masked_queries, masked_candidates)
            test = _build_matrix(scorer, test_ids, queries, candidates, masked_queries, masked_candidates)
            validation_norm, test_norm = _normalize(validation, test)
            threshold = _threshold(validation_norm, validation_ids, gold, candidates)
            score_path = args.cache_dir / f"{key}_rho_{rho:g}_test_scores.csv"
            _write_score_csv(score_path, test_norm, test_ids, gold, candidates)
            query_output = args.output_dir / f"rho_{rho:g}_{method_name.replace(' ', '_').replace('/', '_')}_query_sets.csv"
            row = _aggregate_test_scores(
                score_path, threshold, query_output, rho, method_name, test_ids, gold, len(candidates)
            )
            rows.append(row)
            with comparison_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            np.savez_compressed(
                args.cache_dir / f"{key}_rho_{rho:g}_scores.npz",
                validation=validation_norm.astype(np.float16),
                test=test_norm.astype(np.float16),
            )
            np.savez_compressed(
                args.cache_dir / f"{key}_rho_{rho:g}_ids.npz",
                validation_ids=np.array(validation_ids), test_ids=np.array(test_ids),
            )
            print(f"  done {method_name} rho={rho}: F1={float(row['f1']):.4f} threshold={threshold:.4f}", flush=True)

    print("baseline comparison:", comparison_path)


if __name__ == "__main__":
    main()
