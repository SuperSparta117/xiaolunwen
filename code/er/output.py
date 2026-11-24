from __future__ import annotations

from typing import Iterable, Mapping


def predict_set(scored: Iterable[Mapping[str, object]], threshold: float) -> list[dict[str, object]]:
    return [dict(row) for row in scored if float(row["probability"]) >= threshold]
