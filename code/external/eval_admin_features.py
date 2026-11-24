# -*- coding: utf-8 -*-
"""用 v2 行政区划属性评估 street_match / poi_district_match 的恢复情况（只读，不写资产）。"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from er.config import A_QUERY_PATH  # noqa: E402
from er.geo_asset import _area_equivalent  # noqa: E402
from er.io import read_sql_sample, standardize_property  # noqa: E402

V2 = ROOT / "数据" / "外源数据" / "asset1_poi_coord.csv"
SUFFIXES = ("街道办事处", "街道", "镇", "乡")
ALIASES = {
    "石柱县": {"石柱土家族自治县"},
    "两江新区": {"渝北区", "江北区", "北碚区"},
    "渝北区": {"两江新区"},
    "江北区": {"两江新区"},
    "北碚区": {"两江新区"},
    "高新区": {"九龙坡区", "沙坪坝区"},
    "经开区": {"南岸区"},
    "万盛区": {"綦江区"},
    "万盛经开区": {"綦江区"},
    "双桥经开区": {"大足区"},
}


def norm(v) -> str:
    return "".join(ch for ch in str(v or "").strip().lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def base(name: str) -> str:
    n = str(name or "").strip()
    for s in SUFFIXES:
        if n.endswith(s):
            return n[: -len(s)]
    return n


def equiv(a, b) -> bool:
    if not norm(a) or not norm(b):
        return False
    return _area_equivalent(a, b)


def main() -> None:
    rows = list(csv.DictReader(V2.open("r", encoding="utf-8-sig", newline="")))
    by_key = {(r["表"], r["记录ID"]): r for r in rows}
    queries = {}
    for q in (standardize_property(r) for r in read_sql_sample(A_QUERY_PATH, 10_000_000)):
        v1 = by_key.get(("物业处", str(q["id"])), {})
        queries[str(q["id"])] = {
            "street": q.get("street", ""),
            "area": q.get("area", ""),
            "poi_district": v1.get("高德区县", ""),
        }
    cands = {r["记录ID"]: r for r in rows if r["表"] == "房交"}

    print(f"房交行: {len(cands)}  township 非空: {sum(1 for c in cands.values() if c['乡镇街道'].strip())}")
    print(f"物业处 poi_district 非空: {sum(1 for q in queries.values() if q['poi_district'])}/{len(queries)}")
    print(f"房交 高德区县 非空: {sum(1 for c in cands.values() if c['高德区县'].strip())}")

    stats = defaultdict(lambda: defaultdict(Counter))
    for split in ("train", "validation", "test"):
        p = ROOT / "code" / "training_assets_full_v4" / f"pairs_{split}.csv"
        for row in csv.DictReader(p.open("r", encoding="utf-8", newline="")):
            q = queries.get(row["query_id"])
            b = cands.get(row["candidate_id"])
            if not q or not b:
                continue
            lab = "pos" if row["label"] == "1" else "neg"
            town = b["乡镇街道"]
            vals = {
                "street_old": int(row["street_match"]),
                "street_norm": int(bool(q["street"]) and bool(town) and base(q["street"]) == base(town)),
                "street_norm_and_district": int(
                    bool(q["street"]) and bool(town) and base(q["street"]) == base(town)
                    and equiv(q["area"], b["高德区县"])
                ),
                "district_old": int(row["poi_district_match"]),
                "district_alias": int(equiv(q["poi_district"], b["高德区县"])),
                "township_known": int(bool(town)),
            }
            for k, v in vals.items():
                stats[k][split][f"{lab}:{v}"] += 1

    order = ["street_old", "street_norm", "street_norm_and_district", "district_old", "district_alias", "township_known"]
    print("\n=== 同一批 pair 上的命中率 ===")
    for k in order:
        line = [f"{k:<26}"]
        for split in ("train", "validation", "test"):
            c = stats[k][split]
            P = c.get("pos:0", 0) + c.get("pos:1", 0)
            N = c.get("neg:0", 0) + c.get("neg:1", 0)
            p = c.get("pos:1", 0) / P if P else 0
            n = c.get("neg:1", 0) / N if N else 0
            line.append(f"{split[:3]}: pos {p:.1%} / neg {n:.1%} (Δ{p - n:+.1%})")
        print("  " + "  ".join(line))

    # 冲突分析
    conflict = Counter()
    for b in cands.values():
        if not b["高德区县"].strip():
            continue
        q_area = b["区县"]
        conflict["一致" if equiv(q_area, b["高德区县"]) else f"冲突:{q_area}->{b['高德区县']}"] += 1
    print("\n=== 房交 高德区县 vs 业务区县 ===")
    print(f"  等价一致: {conflict['一致']}/{sum(conflict.values())} = {conflict['一致'] / sum(conflict.values()):.1%}")
    print("  主要冲突:", [(k, v) for k, v in conflict.most_common(12) if k != "一致"])


if __name__ == "__main__":
    main()
