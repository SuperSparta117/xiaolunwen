# -*- coding: utf-8 -*-
"""资产二 v2：补规范名、标注非标准行政名，不改归属（按规格 §3.4.1/§7.2）。"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "数据" / "外源数据" / "asset2_admin_geo.csv"
OUT_DIR = ROOT / "数据" / "外源数据" / "v2"
SUFFIXES = ("街道办事处", "街道", "镇", "乡")


def base_name(name: str) -> str:
    for s in SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def sha256(p: Path) -> str:
    d = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(SRC.open("r", encoding="utf-8-sig", newline="")))
    out = []
    stats = Counter()
    for r in rows:
        row = dict(r)
        name = r["行政区划"].strip()
        row["规范名"] = base_name(name)
        row["是否标准行政名"] = int(name.endswith(SUFFIXES))
        stats[r["级别"]] += 1
        if not row["是否标准行政名"]:
            stats["非标准"] += 1
        out.append(row)

    fields = list(rows[0].keys()) + ["规范名", "是否标准行政名"]
    path = OUT_DIR / "asset2_admin_geo_v2.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    # 同名多区县（用于反查歧义）
    by_name = defaultdict(set)
    for r in out:
        by_name[r["规范名"]].add(r["区县"])
    dup = {k: sorted(v) for k, v in by_name.items() if len(v) > 1}

    manifest = {
        "source": str(SRC.relative_to(ROOT)), "source_sha256": sha256(SRC),
        "output": str(path.relative_to(ROOT)), "output_sha256": sha256(path),
        "rows": len(out), "level_counts": dict(stats),
        "districts": len({r["区县"] for r in out}),
        "districts_having_fallback_rows": sorted({r["区县"] for r in out if r["级别"] != "street"}),
        "districts_with_zero_street_rows": sorted({r["区县"] for r in out} - {r["区县"] for r in out if r["级别"] == "street"}),
        "non_standard_names": [r["行政区划"] for r in out if not r["是否标准行政名"]],
        "ambiguous_names_count": len(dup),
        "ambiguous_names_sample": dict(list(dup.items())[:15]),
        "note": "区县列是“查询该区县时返回的下级”，不是行政归属；归属以 regeo 的 (district, township) 为准",
    }
    (OUT_DIR / "asset2_v2_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
