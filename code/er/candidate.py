from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

from .normalize import normalize_address, normalize_name, tokens

CHANNELS = ("name_ngram", "address_ngram", "area")


def _add(index: dict[str, set[int]], key: str, row_no: int) -> None:
    if key:
        index.setdefault(key, set()).add(row_no)


class CandidateIndex:
    """预先建立各召回通道索引，避免每个 query 重建全量索引。"""

    def __init__(self, candidates: Sequence[Mapping[str, object]]):
        self.candidates = candidates
        self.name_index: dict[str, set[int]] = defaultdict(set)
        self.address_index: dict[str, set[int]] = defaultdict(set)
        self.area_index: dict[str, set[int]] = defaultdict(set)
        for i, row in enumerate(candidates):
            for token in tokens(normalize_name(row.get("name"))):
                _add(self.name_index, token, i)
            for token in tokens(normalize_address(row.get("address"))):
                _add(self.address_index, token, i)
            _add(self.area_index, str(row.get("area", "")), i)

    def _channel_indices(self, query: Mapping[str, object], channel: str) -> dict[int, tuple[int, set[str]]]:
        scores: dict[int, tuple[int, set[str]]] = {}
        if channel in {"name_ngram", "union"}:
            for token in tokens(normalize_name(query.get("name"))):
                for i in self.name_index.get(token, ()):
                    score, sources = scores.get(i, (0, set()))
                    scores[i] = (score + 1, sources | {"name_ngram"})
        if channel in {"address_ngram", "union"}:
            for token in tokens(normalize_address(query.get("address"))):
                for i in self.address_index.get(token, ()):
                    score, sources = scores.get(i, (0, set()))
                    scores[i] = (score + 1, sources | {"address_ngram"})
        if channel in {"area", "union"}:
            for i in self.area_index.get(str(query.get("area", "")), ()):
                score, sources = scores.get(i, (0, set()))
                scores[i] = (score + 1, sources | {"area"})
        return scores

    def generate(self, query: Mapping[str, object], k: int = 20, channel: str = "union") -> list[dict[str, object]]:
        if channel not in (*CHANNELS, "union"):
            raise ValueError(f"unknown candidate channel: {channel}")
        scores = self._channel_indices(query, channel)
        ranked = sorted(scores, key=lambda i: (-scores[i][0], i))[:k]
        return [
            {
                **self.candidates[i],
                "_candidate_index": i,
                "_recall_sources": sorted(scores[i][1]),
                "_recall_score": scores[i][0],
            }
            for i in ranked
        ]


def generate_candidates(
    query: Mapping[str, object], candidates: Sequence[Mapping[str, object]], k: int = 20, channel: str = "union"
) -> list[dict[str, object]]:
    return CandidateIndex(candidates).generate(query, k=k, channel=channel)
