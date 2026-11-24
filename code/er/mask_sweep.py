from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .candidate_pool import build_candidate_pool
from .mask import MASK_RATIOS


def run_mask_sweep(
    output_dir: Path,
    *,
    ratios: Iterable[float] = MASK_RATIOS,
    query_limit: int | None = None,
    candidate_limit: int | None = None,
    mapping_limit: int | None = None,
    k: int = 20,
    seed: int = 42,
    protocol: str = "end_to_end",
) -> dict[str, object]:
    """按固定 seed 运行多档名称遮蔽，并汇总 Recall@K。"""
    if protocol not in {"fixed_pool", "end_to_end"}:
        raise ValueError("mask sweep protocol must be fixed_pool or end_to_end")
    ratios = tuple(ratios)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, object]] = []
    mask_manifest_rows: list[dict[str, object]] = []
    for ratio in ratios:
        ratio_label = f"rho_{ratio:g}".replace(".", "_")
        run_dir = output_dir / f"{protocol}_{ratio_label}"
        manifest = build_candidate_pool(
            run_dir,
            query_limit=query_limit,
            candidate_limit=candidate_limit,
            mapping_limit=mapping_limit,
            k=k,
            version=f"candidate-mask-{protocol}-{ratio:g}",
            protocol=protocol,
            mask_ratio=ratio,
            mask_seed=seed,
        )
        mask_manifest_rows.append({"rho": ratio, "output_dir": str(run_dir), "counts": manifest["counts"]})
        recall_path = run_dir / "candidate_recall_at_k.csv"
        with recall_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                all_rows.append({"protocol": protocol, "rho": ratio, "mask_seed": seed, **row})

    summary_fields = [
        "protocol", "rho", "mask_seed", "k", "provenance", "query_recall", "pair_recall",
        "gold_query_count", "gold_pair_count", "recalled_query_count", "recalled_pair_count", "unknown_query_count",
    ]
    summary_path = output_dir / f"mask_recall_summary_{protocol}.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(all_rows)

    manifest = {
        "task_id": "A",
        "protocol": protocol,
        "mask_seed": seed,
        "ratios": list(ratios),
        "summary_file": {"path": str(summary_path), "rows": len(all_rows)},
        "runs": mask_manifest_rows,
        "policy": {
            "end_to_end": "mask before candidate generation and regenerate the candidate pool",
            "fixed_pool": "keep the natural candidate pool fixed; use only for ranking diagnostics",
            "unknown_is_negative": False,
        },
    }
    (output_dir / f"mask_sweep_manifest_{protocol}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
