from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .config import MAPPING_PATH
from .gold import sha256_file


SPLITS = ("train", "validation", "test")


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def add(self, node: str) -> None:
        if node not in self.parent:
            self.parent[node] = node
            self.rank[node] = 0

    def find(self, node: str) -> str:
        self.add(node)
        if self.parent[node] != node:
            self.parent[node] = self.find(self.parent[node])
        return self.parent[node]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        if self.rank[root_left] < self.rank[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        if self.rank[root_left] == self.rank[root_right]:
            self.rank[root_left] += 1


def _read_mapping(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _stable_order(values: Iterable[str], seed: int) -> list[str]:
    def key(value: str) -> str:
        return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()

    return sorted(values, key=key)


def _allocate_components(components: list[str], seed: int, ratios: tuple[float, float, float]) -> dict[str, str]:
    if abs(sum(ratios) - 1.0) > 1e-9:
        raise ValueError("split ratios must sum to 1")
    ordered = _stable_order(components, seed)
    n = len(ordered)
    train_end = round(n * ratios[0])
    validation_end = train_end + round(n * ratios[1])
    if n >= 3:
        train_end = max(1, min(train_end, n - 2))
        validation_end = max(train_end + 1, min(validation_end, n - 1))
    assignment: dict[str, str] = {}
    for index, component in enumerate(ordered):
        assignment[component] = "train" if index < train_end else ("validation" if index < validation_end else "test")
    return assignment


def build_split_manifest(
    output_dir: Path,
    *,
    mapping_path: Path = MAPPING_PATH,
    mapping_limit: int | None = None,
    seeds: Iterable[int] = (13, 29, 47, 71, 101),
    ratios: tuple[float, float, float] = (0.7, 0.15, 0.15),
    version: str = "split-v1",
) -> dict[str, object]:
    """按 gold 二部图 connected component 生成固定 split manifest。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    mappings = _read_mapping(mapping_path, mapping_limit)
    uf = UnionFind()
    pair_rows: list[tuple[str, str]] = []
    for row in mappings:
        query_id = str(row.get("sql_village_id", "")).strip()
        candidate_id = str(row.get("csv_yuyue_id", "")).strip()
        if not query_id or not candidate_id:
            continue
        query_node = f"q:{query_id}"
        candidate_node = f"c:{candidate_id}"
        uf.union(query_node, candidate_node)
        pair_rows.append((query_id, candidate_id))

    component_nodes: dict[str, set[str]] = defaultdict(set)
    for node in uf.parent:
        component_nodes[uf.find(node)].add(node)
    component_ids = {
        root: f"component-{index:06d}"
        for index, root in enumerate(sorted(component_nodes), start=1)
    }
    query_component = {
        node[2:]: component_ids[uf.find(node)]
        for node in uf.parent
        if node.startswith("q:")
    }
    candidate_component = {
        node[2:]: component_ids[uf.find(node)]
        for node in uf.parent
        if node.startswith("c:")
    }

    seed_values = tuple(seeds)
    if not seed_values:
        raise ValueError("at least one split seed is required")
    seed_manifests: dict[str, object] = {}
    split_rows: list[dict[str, object]] = []
    for seed in seed_values:
        assignment = _allocate_components(list(component_ids.values()), seed, ratios)
        query_splits = {query_id: assignment[component] for query_id, component in query_component.items()}
        candidate_splits = {candidate_id: assignment[component] for candidate_id, component in candidate_component.items()}
        pair_splits = {
            f"{query_id}\t{candidate_id}": assignment[query_component[query_id]]
            for query_id, candidate_id in pair_rows
        }
        component_counts = Counter(assignment.values())
        seed_manifests[str(seed)] = {
            "component_counts": dict(component_counts),
            "query_counts": dict(Counter(query_splits.values())),
            "candidate_counts": dict(Counter(candidate_splits.values())),
            "query_splits": query_splits,
            "candidate_splits": candidate_splits,
        }
        if seed == seed_values[0]:
            split_rows = [
                {
                    "entity_type": "query",
                    "entity_id": entity_id,
                    "component_id": component,
                    "split": query_splits[entity_id],
                    "seed": seed,
                }
                for entity_id, component in sorted(query_component.items())
            ] + [
                {
                    "entity_type": "candidate",
                    "entity_id": entity_id,
                    "component_id": component,
                    "split": candidate_splits[entity_id],
                    "seed": seed,
                }
                for entity_id, component in sorted(candidate_component.items())
            ]

    split_path = output_dir / "split_entities.csv"
    with split_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["entity_type", "entity_id", "component_id", "split", "seed"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(split_rows)

    manifest = {
        "split_version": version,
        "task_id": "A",
        "mapping_file": str(mapping_path),
        "mapping_sha256": sha256_file(mapping_path),
        "mapping_limit": mapping_limit,
        "seeds": list(seeds),
        "ratios": {"train": ratios[0], "validation": ratios[1], "test": ratios[2]},
        "counts": {
            "mapping_rows_read": len(mappings),
            "gold_pair_rows": len(pair_rows),
            "connected_components": len(component_nodes),
            "query_entities": len(query_component),
            "candidate_entities": len(candidate_component),
        },
        "seed_manifests": seed_manifests,
        "leakage_policy": {
            "split_unit": "connected_component_of_gold_bipartite_graph",
            "query_candidate_component_must_stay_together": True,
            "random_pair_split_is_primary": False,
            "unknown_queries_assigned": False,
        },
        "output_file": {"path": str(split_path), "rows": len(split_rows), "sha256": sha256_file(split_path)},
    }
    (output_dir / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
