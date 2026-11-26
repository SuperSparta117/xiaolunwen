"""经典基线：Fellegi-Sunter 概率记录链接 与 BM25F 字段加权检索。

两者都只使用名称 / 地址 / 区县 / 街道 / 类型字段，不使用 POI 外部资产。
名称按实体级遮蔽标记替换为 [MASK]。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterable, Mapping

import numpy as np

from .normalize import normalize_address, normalize_name, similarity, street_key

MASK_TOKEN = "[mask]"
_MISSING = "[missing]"

NAME_LEVELS = ("exact", "high", "mid", "low", "diff", "masked", "missing")
SIM_LEVELS = ("high", "mid", "low", "diff", "missing", "masked")
BINARY_LEVELS = ("match", "diff", "missing", "masked")


def _name_level(name_a: str, name_b: str, masked: bool) -> str:
    if masked:
        return "masked"
    if not name_a or not name_b:
        return "missing"
    if name_a == name_b:
        return "exact"
    value = similarity(name_a, name_b)
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "mid"
    if value >= 0.4:
        return "low"
    return "diff"


def _sim_level(text_a: str, text_b: str, masked: bool) -> str:
    if masked:
        return "masked"
    if not text_a or not text_b:
        return "missing"
    value = similarity(text_a, text_b)
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "mid"
    if value >= 0.4:
        return "low"
    return "diff"


def _binary_level(flag: bool, available: bool, masked: bool) -> str:
    if masked:
        return "masked"
    if not available:
        return "missing"
    return "match" if flag else "diff"


class FellegiSunterScorer:
    """监督式 Fellegi-Sunter：用训练集估计每个比较级在匹配/非匹配下的概率。"""

    name = "Fellegi-Sunter"
    use_external_geo = False

    def __init__(self) -> None:
        self.weights: dict[str, dict[str, float]] = {}
        self.prior_log_odds = 0.0

    def fit(self, pairs: list[dict[str, str]], queries: Mapping[str, dict], candidates: list[Mapping[str, dict]], *, masked_queries: Mapping[str, bool], masked_candidates: list[bool]) -> None:
        candidate_by_id = {str(candidate["id"]): candidate for candidate in candidates}
        candidate_mask_by_id = {str(candidate["id"]): masked_candidates[index] for index, candidate in enumerate(candidates)}
        counts: dict[str, dict[str, Counter]] = {
            "match": defaultdict(Counter), "nonmatch": defaultdict(Counter)
        }
        n_match = n_nonmatch = 0
        for pair in pairs:
            query = queries.get(str(pair["query_id"]))
            candidate = candidate_by_id.get(str(pair["candidate_id"]))
            if query is None or candidate is None:
                continue
            label = "match" if int(float(pair["label"])) == 1 else "nonmatch"
            if label == "match":
                n_match += 1
            else:
                n_nonmatch += 1
            masked = masked_queries.get(str(pair["query_id"]), False) or candidate_mask_by_id.get(str(pair["candidate_id"]), False)
            vector = self._vector(query, candidate, masked)
            for field, level in vector.items():
                counts[label][field][level] += 1
        if not n_match or not n_nonmatch:
            raise ValueError("Fellegi-Sunter 需要同时包含正负例的训练集")
        self.prior_log_odds = math.log(n_match / n_nonmatch)
        fields = ("name", "address", "area", "street", "type")
        for field in fields:
            match_total = sum(counts["match"][field].values()) or 1
            nonmatch_total = sum(counts["nonmatch"][field].values()) or 1
            levels = set(counts["match"][field]) | set(counts["nonmatch"][field])
            table: dict[str, float] = {}
            for level in levels:
                p_match = (counts["match"][field][level] + 0.5) / (match_total + 0.5 * len(levels))
                p_nonmatch = (counts["nonmatch"][field][level] + 0.5) / (nonmatch_total + 0.5 * len(levels))
                table[level] = math.log(p_match / p_nonmatch)
            self.weights[field] = table

    def _vector(self, query: Mapping[str, object], candidate: Mapping[str, object], masked: bool) -> dict[str, str]:
        q_name = normalize_name(query.get("name"))
        c_name = normalize_name(candidate.get("name"))
        q_addr = normalize_address(query.get("address"))
        c_addr = normalize_address(candidate.get("address"))
        q_street = street_key(query.get("street"))
        c_street = street_key(candidate.get("street"))
        return {
            "name": _name_level(q_name, c_name, masked),
            "address": _sim_level(q_addr, c_addr, masked),
            "area": _binary_level(normalize_name(query.get("area")) == normalize_name(candidate.get("area")) and bool(query.get("area")), bool(query.get("area")) and bool(candidate.get("area")), masked),
            "street": _binary_level(bool(q_street) and q_street == c_street, bool(q_street) and bool(c_street), masked),
            "type": _binary_level(bool(query.get("type")) and query.get("type") == candidate.get("type"), bool(query.get("type")) and bool(candidate.get("type")), masked),
        }

    def score_query(self, query: Mapping[str, object], candidates: list[Mapping[str, object]], masked_query: bool, masked_candidates: list[bool]) -> np.ndarray:
        scores = np.empty(len(candidates), dtype=np.float64)
        for index, candidate in enumerate(candidates):
            masked = masked_query or masked_candidates[index]
            vector = self._vector(query, candidate, masked)
            value = self.prior_log_odds
            for field, level in vector.items():
                value += self.weights.get(field, {}).get(level, 0.0)
            scores[index] = value
        return scores


def _char_bigrams(text: str) -> list[str]:
    text = normalize_name(text)
    if not text:
        return []
    if len(text) == 1:
        return [text]
    return [text[i:i + 2] for i in range(len(text) - 1)]


class BM25FScorer:
    """字段加权 BM25F；字段 boost 在 validation 上做小网格选择。"""

    name = "BM25F"
    use_external_geo = False
    FIELDS = ("name", "address", "street", "area", "type")

    def __init__(self, field_boosts: Mapping[str, float] | None = None, k1: float = 1.2, b: float = 0.75) -> None:
        self.field_boosts = dict(field_boosts or {"name": 2.0, "address": 1.0, "street": 1.0, "area": 1.0, "type": 0.5})
        self.k1 = k1
        self.b = b
        self.idf: dict[str, float] = {}
        self.avg_len_per_field: dict[str, float] = {}
        self.candidate_terms: list[dict[str, Counter]] = []

    @staticmethod
    def _fields(record: Mapping[str, object], masked: bool) -> dict[str, str]:
        return {
            # 名称被遮蔽时置空，避免所有遮蔽记录共享同一个占位词造成虚假匹配
            "name": "" if masked else (normalize_name(record.get("name")) or ""),
            "address": normalize_address(record.get("address")) or "",
            "street": street_key(record.get("street")) or "",
            "area": normalize_name(record.get("area")) or "",
            "type": normalize_name(record.get("type")) or "",
        }

    def fit(self, candidates: list[Mapping[str, object]], masked_candidates: list[bool]) -> None:
        df: Counter[str] = Counter()
        self.candidate_terms = []
        for index, candidate in enumerate(candidates):
            fields = self._fields(candidate, masked_candidates[index])
            terms = {field: Counter(_char_bigrams(text)) for field, text in fields.items()}
            self.candidate_terms.append(terms)
            vocabulary = set()
            for counter in terms.values():
                vocabulary.update(counter.keys())
            df.update(vocabulary)
        total = max(1, len(candidates))
        self.idf = {term: math.log(1 + (total - count + 0.5) / (count + 0.5)) for term, count in df.items()}
        for field in self.FIELDS:
            values = [sum(self.candidate_terms[i].get(field, Counter()).values()) for i in range(len(candidates))]
            self.avg_len_per_field[field] = max(1.0, sum(values) / len(values)) if values else 1.0

    def score_query(self, query: Mapping[str, object], candidates: list[Mapping[str, object]], masked_query: bool, masked_candidates: list[bool]) -> np.ndarray:
        query_terms = {field: Counter(_char_bigrams(text)) for field, text in self._fields(query, masked_query).items()}
        scores = np.zeros(len(candidates), dtype=np.float64)
        for index in range(len(candidates)):
            total = 0.0
            for field, terms in query_terms.items():
                if not terms:
                    continue
                length = sum(self.candidate_terms[index].get(field, Counter()).values()) or 1
                norm = self.k1 * (1 - self.b + self.b * length / self.avg_len_per_field[field])
                weighted_tf = 0.0
                for term, query_tf in terms.items():
                    tf = self.candidate_terms[index].get(field, Counter()).get(term, 0)
                    if tf:
                        weighted_tf += query_tf * (tf / norm)
                total += self.field_boosts.get(field, 1.0) * weighted_tf
            scores[index] = total
        return scores
