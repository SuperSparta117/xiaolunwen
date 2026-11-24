from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.geo_asset import build_geo_manifest


parser = argparse.ArgumentParser(description="生成 POI 和行政区划资产审计 manifest")
parser.add_argument("--output-dir", type=Path, default=Path("code/geo_assets"))
args = parser.parse_args()
print(json.dumps(build_geo_manifest(args.output_dir), ensure_ascii=False, indent=2))
