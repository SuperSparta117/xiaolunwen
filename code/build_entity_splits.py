from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.split import build_split_manifest


parser = argparse.ArgumentParser(description="按 gold 二部图 connected component 生成 A 任务 split manifest")
parser.add_argument("--output-dir", type=Path, default=Path("code/split_manifest"))
parser.add_argument("--mapping-limit", type=int, default=None)
parser.add_argument("--version", default="split-v1")
args = parser.parse_args()

manifest = build_split_manifest(args.output_dir, mapping_limit=args.mapping_limit, version=args.version)
print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))
print(f"划分目录: {args.output_dir}")
