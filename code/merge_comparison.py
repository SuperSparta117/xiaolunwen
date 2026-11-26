"""合并全库 LightGBM 结果与新增基线结果，输出统一的 comparison CSV。

输入：
- code/full_library_results_disk_v6/full_candidate_comparison.csv（主字段精确匹配、Full Model、E1/E2/E4b）
- code/baseline_results_full/baseline_comparison.csv（Fellegi-Sunter、BM25F、BGE-M3、Ditto）
输出：code/full_library_results_disk_v6/full_candidate_comparison_all.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "code/full_library_results_disk_v6/full_candidate_comparison.csv"
BASELINES = ROOT / "code/baseline_results_full/baseline_comparison.csv"
OUTPUT = ROOT / "code/full_library_results_disk_v6/full_candidate_comparison_all.csv"

ORDER = [
    "Full Model",
    "主字段精确匹配",
    "Fellegi-Sunter",
    "BM25F",
    "BGE-M3",
    "Ditto (Chinese RoBERTa)",
    "E1 remove admin center",
    "E2 remove POI",
    "E4b 全特征关闭",
]


def load(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = load(MAIN) + load(BASELINES)
    fields = list(rows[0].keys())
    order_index = {name: index for index, name in enumerate(ORDER)}
    rows.sort(key=lambda row: (float(row["rho"]), order_index.get(row["method"], 99)))
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print("rows:", len(rows), "->", OUTPUT)
    for row in rows:
        print(f"{float(row['rho']):g}\t{row['method']:<26}\tF1={float(row['f1']) * 100:.2f}\t"
              f"P={float(row['precision']) * 100:.2f}\tR={float(row['recall']) * 100:.2f}\t"
              f"tau={float(row['threshold_validation']):.3f}\tFR={float(row['positive_false_reject_rate']) * 100:.1f}%")


if __name__ == "__main__":
    main()
