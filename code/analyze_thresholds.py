"""阈值选择分析：表 3a（各 rho 选定阈值与工作点）与表 3b（rho=0.6 明细）。

只读现有分数缓存，不重训模型。阈值选择规则与 full_library 一致：
validation 上按 20,000 桶直方图最大 F1 选阈值，test 只做汇报。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from er.full_library import HISTOGRAM_BINS, entity_is_masked, threshold_from_histogram  # noqa: E402
from er.full_data import load_full_library_data  # noqa: E402

csv.field_size_limit(2 ** 31 - 1)


def read_scores(path: Path):
    rows: list[list[float]] = []
    current = None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            query_id = row["query_id"]
            if query_id != current:
                rows.append([])
                current = query_id
            rows[-1].append(float(row["probability"]))
    return rows


def metrics(score_rows, ids, gold, candidates, threshold):
    tp = fp = fn = covered = 0
    macro = 0.0
    for row, query_id in enumerate(ids):
        scores = np.asarray(score_rows[row])
        predicted = scores >= threshold
        query_gold = gold.get(query_id, set())
        gold_mask = np.array([1 if candidate_id in query_gold else 0 for candidate_id in candidates], dtype=bool)
        local_tp = int((predicted & gold_mask).sum())
        local_fp = int((predicted & ~gold_mask).sum())
        local_fn = int((~predicted & gold_mask).sum())
        tp += local_tp
        fp += local_fp
        fn += local_fn
        covered += int(predicted.any())
        precision = local_tp / predicted.sum() if predicted.sum() else 0.0
        recall = local_tp / gold_mask.sum() if gold_mask.sum() else 0.0
        macro += 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = len(ids)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "macro_f1": macro / total if total else 0.0,
        "coverage": covered / total if total else 0.0,
        "false_reject": 1 - covered / total if total else 0.0,
        "tp": tp, "fp": fp, "fn": fn,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=Path("code/full_library_results_disk_v6/full_candidate_comparison.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".audit_work/full_candidate_cache_v6"))
    parser.add_argument("--method", default="Full Model")
    parser.add_argument("--thresholds", default="0.7,0.8,0.85,0.88,0.9,0.905,0.908,0.91,0.912,0.92,0.95")
    args = parser.parse_args()

    data = load_full_library_data(Path("code/training_assets_full_v5"))
    validation_ids = data["validation_ids"]
    test_ids = data["test_ids"]
    gold = data["gold_by_query"]
    candidates = [str(candidate["id"]) for candidate in data["candidates"]]

    with args.comparison.open("r", encoding="utf-8-sig", newline="") as handle:
        comparison = list(csv.DictReader(handle))
    rows = [row for row in comparison if row["method"] == args.method]
    rows.sort(key=lambda row: float(row["rho"]))
    print("表 3a（各 rho 选定阈值与工作点）")
    print("| rho | 选定 tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 | 误拒率 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    table_a = []
    from er.disk_cache import prepare_run

    for row in rows:
        rho = float(row["rho"])
        threshold = float(row["threshold_validation"])
        run_dir = prepare_run(args.cache_dir, rho, args.method, 42, 13)
        validation_rows = read_scores(run_dir / "validation_scores.csv")
        validation = metrics(validation_rows, validation_ids, gold, candidates, threshold)
        row_payload = {key: row[key] for key in row}
        row_payload["validation_f1"] = f"{validation['f1']}"
        table_a.append(row_payload)
        print(f"| {rho:g} | {threshold:.3f} | {validation['f1'] * 100:.2f} | {float(row['precision']) * 100:.2f} | "
              f"{float(row['recall']) * 100:.2f} | {float(row['f1']) * 100:.2f} | "
              f"{(1 - float(row['positive_false_reject_rate'])) * 100:.1f}% | "
              f"{float(row['positive_false_reject_rate']) * 100:.1f}% |")

    # 表 3b：rho=0.6 明细（validation 与 test 同时算）
    rho = 0.6
    run_dir = prepare_run(args.cache_dir, rho, args.method, 42, 13)
    validation_rows = read_scores(run_dir / "validation_scores.csv")
    test_rows = read_scores(run_dir / "test_scores.csv")
    selected = next(float(row["threshold_validation"]) for row in rows if abs(float(row["rho"]) - rho) < 1e-9)
    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    if selected not in thresholds:
        thresholds.append(selected)
    thresholds = sorted(set(thresholds))
    print("\n表 3b（Full Model，rho=0.6 阈值明细）")
    print("| tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 |")
    print("|---:|---:|---:|---:|---:|---:|")
    table_b = []
    for threshold in thresholds:
        validation = metrics(validation_rows, validation_ids, gold, candidates, threshold)
        test = metrics(test_rows, test_ids, gold, candidates, threshold)
        mark = "（验证集选定）" if abs(threshold - selected) < 1e-9 else ""
        table_b.append({
            "threshold": threshold, "validation": validation, "test": test,
            "selected": abs(threshold - selected) < 1e-9,
        })
        print(f"| {threshold:g}{mark} | {validation['f1'] * 100:.2f} | {test['precision'] * 100:.2f} | "
              f"{test['recall'] * 100:.2f} | {test['f1'] * 100:.2f} | {test['coverage'] * 100:.1f}% |")

    output = args.comparison.parent / "threshold_tables.json"
    output.write_text(json.dumps({"table_a": table_a, "table_b": table_b}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwritten:", output)


if __name__ == "__main__":
    main()
