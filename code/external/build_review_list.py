# -*- coding: utf-8 -*-
"""从 v2 资产生成人工复核清单（不可信行 + 区县冲突行）。"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "数据" / "外源数据" / "v2" / "asset1_poi_coord_v2.csv"
TRANSACTION = ROOT / "数据" / "A_房屋交易中心_合并数据.csv"
OUT = ROOT / "数据" / "外源数据" / "v2" / "review_needed.csv"
csv.field_size_limit(2**31 - 1)


def sha256(p: Path) -> str:
    d = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def main() -> None:
    rows = list(csv.DictReader(V2.open("r", encoding="utf-8-sig", newline="")))
    addr = {r["愉悦安"]: r["地址"] for r in csv.DictReader(TRANSACTION.open("r", encoding="utf-8-sig", newline=""))}

    review = []
    for r in rows:
        if r["表"] != "房交" or r["可信_v2"] == "1":
            continue
        reason = r["不可信原因_v2"]
        kind = []
        if "polygon_bbox_ge_1000m" in reason:
            kind.append("面坐标几何异常")
        if "district_mismatch" in reason:
            kind.append("区县冲突")
        if "district_missing_in_source" in reason:
            kind.append("登记区县缺失")
        review.append({
            "记录ID": r["记录ID"],
            "业务区县": r["区县"],
            "高德区县": r["高德区县"],
            "乡镇街道": r["乡镇街道"],
            "adcode": r["adcode"],
            "经度": r["经度"],
            "纬度": r["纬度"],
            "地址": addr.get(r["记录ID"], ""),
            "问题类型": "/".join(kind) or reason,
            "不可信原因_v2": reason,
        })

    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(review[0].keys()) if review else ["记录ID"])
        w.writeheader()
        w.writerows(review)

    kinds = Counter(r["问题类型"] for r in review)
    conflicts = [r for r in review if "区县冲突" in r["问题类型"]]
    manifest = {
        "source": str(V2.relative_to(ROOT)), "source_sha256": sha256(V2),
        "output": str(OUT.relative_to(ROOT)), "output_sha256": sha256(OUT),
        "rows": len(review), "by_kind": dict(kinds),
        "district_conflicts": len(conflicts),
        "district_conflict_pairs": Counter((r["业务区县"], r["高德区县"]) for r in conflicts).most_common(),
        "note": "房交侧 可信_v2=0 的行；几何异常只影响距离特征，区县冲突需人工确认哪一侧错",
    }
    (OUT.parent / "review_needed_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
