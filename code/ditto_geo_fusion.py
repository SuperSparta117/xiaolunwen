# -*- coding: utf-8 -*-
"""独立实验：Ditto（深度文本）+ Full Model（POI/行政地理）分数融合。

不写入 README。使用现有全库 validation/test 分数矩阵：
- Full Model: .audit_work/full_candidate_cache_v6 下的 score CSV
- Ditto: .audit_work/baseline_cache/ditto_rho_X_scores.npz（min-max 归一化后）
融合方式：fused = w * full_prob + (1 - w) * ditto_prob，w 在 validation 上网格搜索
（目标为 validation 最大 F1 阈值下的 F1），test 只汇报。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from er.disk_cache import prepare_run  # noqa: E402
from er.full_data import load_full_library_data  # noqa: E402
from er.full_library import HISTOGRAM_BINS, threshold_from_histogram  # noqa: E402

csv.field_size_limit(2 ** 31 - 1)
RATIOS = (0.0, 0.3, 0.6, 1.0)


def read_full_matrix(path: Path, expected_queries: list[str], expected_candidates: list[str]) -> np.ndarray:
    rows: list[list[float]] = []
    current = None
    order: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            query_id = row["query_id"]
            if query_id != current:
                rows.append([])
                order.append(query_id)
                current = query_id
            rows[-1].append(float(row["probability"]))
    assert order == expected_queries, f"query order mismatch {len(order)} vs {len(expected_queries)}"
    matrix = np.asarray(rows, dtype=np.float32)
    assert matrix.shape == (len(expected_queries), len(expected_candidates)), matrix.shape
    return matrix


def metrics(predicted, gold_mask):
    tp = int((predicted & gold_mask).sum())
    fp = int((predicted & ~gold_mask).sum())
    fn = int((~predicted & gold_mask).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    covered = int(predicted.any(axis=1).sum())
    return precision, recall, f1, covered / len(predicted)


def threshold_for(matrix: np.ndarray, labels: np.ndarray) -> tuple[float, float, float, float]:
    """按 validation 最大 F1 选阈值，返回 (tau, precision, recall, f1)。"""
    positive = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
    negative = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
    bins = np.minimum(HISTOGRAM_BINS - 1, (matrix * HISTOGRAM_BINS).astype(np.int64))
    positive += np.bincount(bins[labels], minlength=HISTOGRAM_BINS)
    negative += np.bincount(bins[~labels], minlength=HISTOGRAM_BINS)
    tau = threshold_from_histogram(positive, negative)
    precision, recall, f1, _ = metrics(matrix >= tau, labels)
    return tau, precision, recall, f1


def fit_logistic(validation_full: np.ndarray, validation_ditto: np.ndarray, labels: np.ndarray,
                 iterations: int = 8) -> np.ndarray:
    """在 validation 全体 pair 上拟合 3 参数逻辑回归 [1, full, ditto]。"""
    features = np.stack([np.ones(labels.size, dtype=np.float64),
                         validation_full.ravel().astype(np.float64),
                         validation_ditto.ravel().astype(np.float64)], axis=1)
    target = labels.ravel().astype(np.float64)
    weights = np.zeros(3, dtype=np.float64)
    for _ in range(iterations):
        logits = features @ weights
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        gradient = features.T @ (probabilities - target)
        hessian = features.T @ (features * (probabilities * (1 - probabilities))[:, None])
        weights -= np.linalg.solve(hessian + np.eye(3) * 1e-6, gradient)
    return weights


def apply_logistic(weights: np.ndarray, full: np.ndarray, ditto: np.ndarray) -> np.ndarray:
    logits = weights[0] + weights[1] * full + weights[2] * ditto
    return 1.0 / (1.0 + np.exp(-logits))


def main() -> None:
    data = load_full_library_data(ROOT / "code/training_assets_full_v5", split_seed=13)
    candidate_ids = [str(candidate["id"]) for candidate in data["candidates"]]
    validation_ids = data["validation_ids"]
    test_ids = data["test_ids"]
    gold = data["gold_by_query"]
    val_labels = np.asarray([[cid in gold[qid] for cid in candidate_ids] for qid in validation_ids], dtype=bool)
    test_labels = np.asarray([[cid in gold[qid] for cid in candidate_ids] for qid in test_ids], dtype=bool)

    cache = ROOT / ".audit_work/full_candidate_cache_v6"
    ditto_cache = ROOT / ".audit_work/baseline_cache"
    print("rho\tw_best\ttau\tval_F1\tFull_F1\tDitto_F1\tFusion_F1\tFusion_P\tFusion_R\tCoverage")
    summary = []
    for rho in RATIOS:
        full_dir = prepare_run(cache, rho, "Full Model", 42, 13)
        full_val = read_full_matrix(full_dir / "validation_scores.csv", validation_ids, candidate_ids)
        full_test = read_full_matrix(full_dir / "test_scores.csv", test_ids, candidate_ids)
        ditto = np.load(ditto_cache / f"ditto_rho_{rho:g}_scores.npz")
        ditto_val = ditto["validation"].astype(np.float32)
        ditto_test = ditto["test"].astype(np.float32)
        ditto_ids = np.load(ditto_cache / f"ditto_rho_{rho:g}_ids.npz")
        assert list(ditto_ids["validation_ids"]) == validation_ids
        assert list(ditto_ids["test_ids"]) == test_ids

        best = None
        for w in np.round(np.arange(0.0, 1.0001, 0.05), 2):
            fused_val = np.clip(w * full_val + (1 - w) * ditto_val, 0.0, 1.0)
            tau, _, _, val_f1 = threshold_for(fused_val, val_labels)
            if best is None or val_f1 > best[1]:
                best = (float(w), val_f1, tau)
        w, val_f1, tau = best
        full_f1 = threshold_for(full_val, val_labels)[3]
        ditto_f1 = threshold_for(ditto_val, val_labels)[3]
        fused_val = np.clip(w * full_val + (1 - w) * ditto_val, 0.0, 1.0)
        fused_test = np.clip(w * full_test + (1 - w) * ditto_test, 0.0, 1.0)
        precision, recall, test_f1, coverage = metrics(fused_test >= tau, test_labels)
        summary.append((rho, w, tau, val_f1, full_f1, ditto_f1, test_f1, precision, recall, coverage))
        print(f"{rho:g}\t{w:.2f}\t{tau:.4f}\t{val_f1 * 100:.2f}\t{full_f1 * 100:.2f}\t{ditto_f1 * 100:.2f}\t"
              f"{test_f1 * 100:.2f}\t{precision * 100:.2f}\t{recall * 100:.2f}\t{coverage * 100:.1f}%")

        # 逻辑回归堆叠（非线性组合）
        weights = fit_logistic(full_val, ditto_val, val_labels)
        stack_val = apply_logistic(weights, full_val, ditto_val).astype(np.float32)
        stack_test = apply_logistic(weights, full_test, ditto_test).astype(np.float32)
        stack_tau, _, _, stack_val_f1 = threshold_for(stack_val, val_labels)
        stack_p, stack_r, stack_test_f1, stack_cov = metrics(stack_test >= stack_tau, test_labels)
        print(f"  logistic stack: w={np.round(weights, 3)} val_F1={stack_val_f1 * 100:.2f} "
              f"test_F1={stack_test_f1 * 100:.2f} P={stack_p * 100:.2f} R={stack_r * 100:.2f} "
              f"cov={stack_cov * 100:.1f}%")

    out = ROOT / "code/fusion_experiment" / "full_ditto_fusion.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rho", "w_full", "threshold", "val_f1", "full_val_f1", "ditto_val_f1", "test_f1", "test_precision", "test_recall", "coverage"])
        writer.writerows(summary)
    print("written:", out)


if __name__ == "__main__":
    main()
