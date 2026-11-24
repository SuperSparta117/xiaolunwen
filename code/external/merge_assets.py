# -*- coding: utf-8 -*-
"""合并外源资产版本：把 v2 内容直接落为唯一资产，删除 v1 与 v2 目录。

- asset1：保留原 17 列 + 乡镇街道/行政区划来源/定位方式；房交侧 可信/不可信原因 用区划校验后口径；
- asset2：保留规范名/是否标准行政名；
- 原始响应与复核清单上移；
- 生成单一 manifest（含前身 SHA-256，供追溯）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "数据" / "外源数据"
V2 = EXT / "v2"
NEW_COLS = ["乡镇街道", "行政区划来源", "定位方式"]

REASON_MAP = {
    "outside_chongqing_bbox": "坐标在重庆辖区外",
    "missing_coordinate": "无坐标",
    "polygon_bbox_ge_1000m": "面坐标包围盒异常",
}


def sha256(p: Path) -> str:
    d = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def translate(reason: str) -> str:
    out = []
    for part in [x for x in reason.split(";") if x]:
        if part in REASON_MAP:
            out.append(REASON_MAP[part])
        elif part.startswith("district_mismatch(") and part.endswith(")"):
            out.append(f"区县不符(高德={part[len('district_mismatch('):-1]})")
        elif part.startswith("district_missing_in_source(") and part.endswith(")"):
            out.append(f"登记区县缺失(高德={part[len('district_missing_in_source('):-1]})")
        else:
            out.append(part)
    return ";".join(out)


def main() -> None:
    asset1 = EXT / "asset1_poi_coord.csv"
    asset2 = EXT / "asset2_admin_geo.csv"
    old_sha1, old_sha2 = sha256(asset1), sha256(asset2)

    rows = list(csv.DictReader((V2 / "asset1_poi_coord_v2.csv").open("r", encoding="utf-8-sig", newline="")))
    base_fields = [f for f in rows[0].keys() if f not in NEW_COLS + ["可信_v2", "不可信原因_v2"]]
    fields = base_fields + NEW_COLS

    out = []
    stats = Counter()
    for r in rows:
        row = {k: r[k] for k in base_fields}
        row["乡镇街道"] = r["乡镇街道"]
        row["行政区划来源"] = r["行政区划来源"]
        row["定位方式"] = r["定位方式"]
        if r["表"] == "房交":
            row["可信"] = "True" if r["可信_v2"] == "1" else "False"
            row["不可信原因"] = translate(r["不可信原因_v2"])
        stats[(r["表"], row["可信"])] += 1
        out.append(row)

    with asset1.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    shutil.copyfile(V2 / "asset2_admin_geo_v2.csv", asset2)
    shutil.copyfile(V2 / "regeo_fangjiao.jsonl", EXT / "regeo_fangjiao.jsonl")
    shutil.copyfile(V2 / "review_needed.csv", EXT / "review_needed.csv")

    review = list(csv.DictReader((EXT / "review_needed.csv").open("r", encoding="utf-8-sig", newline="")))
    reasons = Counter()
    for r in out:
        if r["表"] == "房交" and r["可信"] == "False":
            reasons[r["不可信原因"]] += 1

    manifest = {
        "directory": str(EXT.relative_to(ROOT)),
        "assets": {
            "asset1": {
                "file": "asset1_poi_coord.csv", "sha256": sha256(asset1),
                "rows": len(out), "columns": fields,
                "rows_by_table": dict(Counter(r["表"] for r in out)),
                "trusted_by_table": {f"{t}": n for (t, ok), n in stats.items() if ok == "True"},
            },
            "asset2": {
                "file": "asset2_admin_geo.csv", "sha256": sha256(asset2),
                "rows": 1094,
            },
        },
        "predecessor_sha256": {
            "asset1": old_sha1, "asset2": old_sha2,
            "note": "合并前 v1 资产的 SHA-256；v3 训练资产的 feature_manifest 引用的是该前身，合并后不再逐字节可复现",
        },
        "fangjiao_admin": {
            "township_nonempty": sum(1 for r in out if r["表"] == "房交" and r["乡镇街道"]),
            "district_nonempty": sum(1 for r in out if r["表"] == "房交" and r["高德区县"]),
            "untrusted_reasons": dict(reasons),
            "review_rows": len(review),
        },
        "raw_responses": {
            "file": "regeo_fangjiao.jsonl", "sha256": sha256(EXT / "regeo_fangjiao.jsonl"),
            "api_responses": sum(1 for line in (EXT / "regeo_fangjiao.jsonl").open("r", encoding="utf-8") if '"source": "api"' in line),
        },
        "method": "房交: regeo(GCJ-02 面坐标质心) -> district/township/adcode；坐标未改动",
        "external_used_for_label": True,
        "external_used_for_label_note": "878 条 regeo 曾用于坐标系判定与金标准复核，且均为 gold candidate",
        "fetched_at": "2026-11-24",
    }
    (EXT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    shutil.rmtree(V2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
