from __future__ import annotations

import random
from typing import Mapping


MASK_RATIOS = (0.0, 0.3, 0.6, 1.0)


def mask_primary_fields(row: Mapping[str, object], ratio: float, seed: int) -> dict[str, object]:
    """按固定 seed 遮蔽名称及其直接派生字段，保留原记录副本之外的输入视图。"""
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("mask ratio must be between 0 and 1")
    result = dict(row)
    if ratio == 0.0:
        result["_mask_applied"] = False
        return result
    rng = random.Random(f"{seed}:{row.get('id', '')}")
    if rng.random() > ratio:
        result["_mask_applied"] = False
        return result
    for field in ("name", "name_normalized", "project_name", "phase_name", "group_name"):
        if field in result:
            result[field] = ""
    result["_mask_applied"] = True
    result["_mask_ratio"] = ratio
    result["_mask_seed"] = seed
    return result
