from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.mask_sweep import run_mask_sweep


parser = argparse.ArgumentParser(description="运行 A 任务名称遮蔽率实验")
parser.add_argument("--output-dir", type=Path, default=Path("code/mask_sweep"))
parser.add_argument("--protocol", choices=("fixed_pool", "end_to_end"), default="end_to_end")
parser.add_argument("--query-limit", type=int, default=None)
parser.add_argument("--candidate-limit", type=int, default=None)
parser.add_argument("--mapping-limit", type=int, default=None)
parser.add_argument("--k", type=int, default=20)
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()

manifest = run_mask_sweep(
    args.output_dir,
    protocol=args.protocol,
    query_limit=args.query_limit,
    candidate_limit=args.candidate_limit,
    mapping_limit=args.mapping_limit,
    k=args.k,
    seed=args.seed,
)
print(json.dumps(manifest["summary_file"], ensure_ascii=False, indent=2))
