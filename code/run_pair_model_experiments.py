from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.experiments import run_experiments


parser = argparse.ArgumentParser(description="运行 A 任务可执行成对模型基线和消融实验")
parser.add_argument("--data-dir", type=Path, default=Path("code/training_assets_full"))
parser.add_argument("--mask-ratio", type=float, default=0.6)
parser.add_argument("--mask-seed", type=int, default=42)
parser.add_argument("--output-dir", type=Path, default=Path("code/experiment_results"))
args = parser.parse_args()
report = run_experiments(args.data_dir, args.output_dir, mask_ratio=args.mask_ratio, mask_seed=args.mask_seed)
print(json.dumps({"train_rows": report["train_rows"], "validation_rows": report["validation_rows"], "test_rows": report["test_rows"]}, ensure_ascii=False, indent=2))
print(f"实验结果目录: {args.output_dir}")
