from __future__ import annotations

import argparse
import json
from pathlib import Path

from er.pipeline import run_sample_pipeline


parser = argparse.ArgumentParser(description="Run the bounded entity-resolution smoke test")
parser.add_argument("--sample-size", type=int, default=12)
args = parser.parse_args()
report = run_sample_pipeline(args.sample_size, Path(__file__).parent / "sample_output")
print(json.dumps({k: report[k] for k in ("task", "sample_size", "candidate_rows", "pair_rows", "warning")}, ensure_ascii=False, indent=2))
