from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.gold import build_evaluation_assets


parser = argparse.ArgumentParser(description="生成 A 任务金标准与评测资产")
parser.add_argument("--output-dir", type=Path, default=Path("code/evaluation_assets"))
parser.add_argument("--query-limit", type=int, default=None, help="只读取前 N 条 query，用于冒烟测试")
parser.add_argument("--candidate-limit", type=int, default=None, help="只读取前 N 条候选记录，用于冒烟测试")
parser.add_argument("--mapping-limit", type=int, default=None, help="只读取前 N 条 mapping，用于冒烟测试")
parser.add_argument("--version", default="gold-v1")
args = parser.parse_args()

manifest = build_evaluation_assets(
    args.output_dir,
    query_limit=args.query_limit,
    candidate_limit=args.candidate_limit,
    mapping_limit=args.mapping_limit,
    version=args.version,
)
print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))
print(f"资产目录: {args.output_dir}")
