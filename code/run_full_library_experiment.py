from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.full_library import run_full_library


parser = argparse.ArgumentParser(description="运行 A 任务完整候选库集合评估")
parser.add_argument("--data-dir", type=Path, default=Path("code/training_assets_full_v4"))
parser.add_argument("--output-dir", type=Path, default=Path("code/full_library_results"))
parser.add_argument("--mask-ratios", default="0,0.3,0.6,1.0")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--cache-dir", type=Path, default=Path(".audit_work/full_candidate_cache"))
parser.add_argument("--split-seed", type=int, default=13)
args = parser.parse_args()
ratios = tuple(float(value) for value in args.mask_ratios.split(",") if value.strip())
report = run_full_library(
    args.data_dir,
    args.cache_dir,
    args.output_dir,
    ratios=ratios,
    seed=args.seed,
    split_seed=args.split_seed,
)
print(json.dumps(report, ensure_ascii=False, indent=2))
