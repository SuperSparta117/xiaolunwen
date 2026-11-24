from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.training_data import build_pair_feature_assets


parser = argparse.ArgumentParser(description="生成带 POI 特征的 A 任务成对训练/评测数据")
parser.add_argument("--output-dir", type=Path, default=Path("code/training_assets"))
parser.add_argument("--query-limit", type=int, default=None)
parser.add_argument("--candidate-limit", type=int, default=None)
parser.add_argument("--mapping-limit", type=int, default=None)
parser.add_argument("--split-seed", type=int, default=13)
parser.add_argument("--split-manifest", type=Path, default=Path("code/split_manifest_full/split_manifest.json"))
parser.add_argument("--candidate-source", choices=("text_only", "poi", "admin", "full"), default="full")
parser.add_argument("--negative-ratio", type=int, default=3)
args = parser.parse_args()

manifest = build_pair_feature_assets(
    args.output_dir,
    split_manifest_path=args.split_manifest,
    query_limit=args.query_limit,
    candidate_limit=args.candidate_limit,
    mapping_limit=args.mapping_limit,
    split_seed=args.split_seed,
    negative_ratio=args.negative_ratio,
    candidate_source=args.candidate_source,
)
print(json.dumps({"positive_pairs": manifest["positive_pairs"], "negative_pairs_by_split": manifest["negative_pairs_by_split"]}, ensure_ascii=False, indent=2))
