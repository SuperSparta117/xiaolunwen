from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from .geo import haversine_m
from .normalize import normalize_address, normalize_name, tokens


GRID_SIZE_DEGREES = 0.02


def _grid(point: tuple[float, float], size: float = GRID_SIZE_DEGREES) -> tuple[int, int]:
    lng, lat = point
    return math.floor(lng / size), math.floor(lat / size)


def _point(row: Mapping[str, object]) -> tuple[float, float] | None:
    if not row.get("coords_trust"):
        return None
    try:
        return float(row["lng"]), float(row["lat"])
    except (KeyError, TypeError, ValueError):
        return None


class GeoCandidateIndex:
    def __init__(self, candidates: Sequence[Mapping[str, object]], grid_size: float = GRID_SIZE_DEGREES):
        self.candidates = candidates
        self.grid_size = grid_size
        self.grid_index: dict[tuple[int, int], set[int]] = defaultdict(set)
        self.name_index: dict[str, set[int]] = defaultdict(set)
        self.address_index: dict[str, set[int]] = defaultdict(set)
        for index, row in enumerate(candidates):
            point = _point(row)
            if point:
                self.grid_index[_grid(point, grid_size)].add(index)
            for token in tokens(normalize_name(row.get("name"))):
                self.name_index[token].add(index)
            for token in tokens(normalize_address(row.get("address"))):
                self.address_index[token].add(index)

    def poi_candidates(self, query: Mapping[str, object], k: int = 20) -> list[dict[str, object]]:
        point = _point(query)
        if point is None:
            return []
        gx, gy = _grid(point, self.grid_size)
        indices = {
            index
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for index in self.grid_index.get((gx + dx, gy + dy), set())
        }
        ranked = sorted(
            indices,
            key=lambda index: haversine_m(point, _point(self.candidates[index])) or float("inf"),
        )[:k]
        return [
            {
                **self.candidates[index],
                "_candidate_index": index,
                "_recall_sources": ["poi_grid"],
                "_recall_score": 1.0 / (1.0 + (haversine_m(point, _point(self.candidates[index])) or 0.0)),
            }
            for index in ranked
        ]

    def union_candidates(self, query: Mapping[str, object], k: int = 20) -> list[dict[str, object]]:
        candidates: dict[int, dict[str, object]] = {}
        for row in self.poi_candidates(query, k=k):
            candidates[int(row["_candidate_index"])] = row
        return list(candidates.values())


def write_geo_candidate_report(path: Path, rows: list[dict[str, object]]) -> None:
    fields = ["query_id", "candidate_id", "recall_source", "rank", "distance_m", "gold_in_pool"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
