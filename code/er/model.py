from __future__ import annotations

from typing import Mapping


def baseline_score(features: Mapping[str, float | int | None]) -> float:
    """Deterministic smoke-test scorer; replace with train/validation-frozen model later."""
    score = (
        0.48 * float(features.get("name_similarity") or 0)
        + 0.22 * float(features.get("address_similarity") or 0)
        + 0.12 * float(features.get("area_match") or 0)
        + 0.08 * float(features.get("street_match") or 0)
        + 0.05 * float(features.get("type_match") or 0)
    )
    distance = features.get("poi_distance_m")
    if distance is not None:
        score += 0.05 if float(distance) <= 300 else (-0.05 if float(distance) > 2000 else 0)
    return max(0.0, min(1.0, score))
