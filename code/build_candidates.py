from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.candidate_pool import build_candidate_pool


parser = argparse.ArgumentParser(description="生成 A 任务候选池和召回审计资产")
parser.add_argument("--output-dir", type=Path, default=Path("code/candidate_pool"))
parser.add_argument("--query-limit", type=int, default=None)
parser.add_argument("--candidate-limit", type=int, default=None)
parser.add_argument("--mapping-limit", type=int, default=None)
parser.add_argument("--k", type=int, default=20)
parser.add_argument("--version", default="candidate-v1")
parser.add_argument("--protocol", choices=("natural", "fixed_pool", "end_to_end"), default="natural")
parser.add_argument("--mask-ratio", type=float, default=0.0)
parser.add_argument("--mask-seed", type=int, default=42)
args = parser.parse_args()

manifest = build_candidate_pool(
    args.output_dir,
    query_limit=args.query_limit,
    candidate_limit=args.candidate_limit,
    mapping_limit=args.mapping_limit,
    k=args.k,
    version=args.version,
    protocol=args.protocol,
    mask_ratio=args.mask_ratio,
    mask_seed=args.mask_seed,
)
print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))
print(f"候选池目录: {args.output_dir}")
