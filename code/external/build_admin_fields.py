# -*- coding: utf-8 -*-
"""房交侧行政区划补全（按《模块规格_外源数据接入.md》§3.6/§3.7 实现）。

- 坐标零改动：使用 asset1_poi_coord.csv 中已冻结的 GCJ-02 面坐标质心；
- 只新增行政区划属性：高德区县 / adcode / 乡镇街道 / 规范地址 / 行政区划来源 / 定位方式；
- 异常面坐标（包围盒对角线 ≥1000m，113 行）额外用「最大面面积加权质心 → wgs2gcj」求一次区划，
  仅当其结果区县与登记区县一致时优先采用，且不回写坐标；
- 复用 raw_cache.zip/regeo_check.json 中 878 条既有响应；JSONL 断点续跑；
- 输出 v2 CSV + manifest（含 SHA-256、调用次数、方法、时间）。
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import http.client
import json
import math
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "数据"
sys.path.insert(0, str(ROOT / "code"))
from er.geo_asset import _area_equivalent  # noqa: E402  区县别名/代管等价唯一来源
ASSET = DATA / "外源数据" / "asset1_poi_coord.csv"
RAW_CACHE = DATA / "外源数据" / "raw_cache.zip"
TRANSACTION = DATA / "A_房屋交易中心_合并数据.csv"
KEY = os.environ.get("AMAP_KEY", "").strip()
REGEO = "/v3/geocode/regeo"
csv.field_size_limit(2**31 - 1)

TRANSIENT = {"10003", "10021", "10019", "10020", "10022", "10029", "30000", "30001"}
ABORT = {"10001", "10002", "10004", "10044"}

# 重庆 bbox（与 code/er/geo.py 一致）
BBOX = (105.05, 110.45, 27.95, 32.55)


# ---------- 几何 ----------
def wgs2gcj(lng: float, lat: float) -> tuple[float, float]:
    a, ee = 6378245.0, 0.00669342162296594323

    def tl(x, y):
        r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return r

    def tg(x, y):
        r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return r

    dlat, dlng = tl(lng - 105.0, lat - 35.0), tg(lng - 105.0, lat - 35.0)
    rl = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rl) ** 2
    sm = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sm) * math.pi)
    dlng = (dlng * 180.0) / (a / sm * math.cos(rl) * math.pi)
    return lng + dlng, lat + dlat


def rings_of(geom):
    out = []

    def is_pt(o):
        return isinstance(o, (list, tuple)) and len(o) == 2 and all(isinstance(x, (int, float)) for x in o)

    def walk(o):
        if isinstance(o, (list, tuple)) and o:
            if is_pt(o):
                return
            if all(is_pt(p) for p in o):
                out.append([tuple(map(float, p)) for p in o])
                return
            for x in o:
                walk(x)

    walk(geom)
    return out


def ring_area(r):
    s = 0.0
    for i in range(len(r)):
        x1, y1 = r[i]
        x2, y2 = r[(i + 1) % len(r)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def ring_centroid(r):
    a = cx = cy = 0.0
    for i in range(len(r)):
        x1, y1 = r[i]
        x2, y2 = r[(i + 1) % len(r)]
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    a /= 2
    if abs(a) < 1e-12:
        return sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r)
    return cx / (6 * a), cy / (6 * a)


def bbox_diagonal_m(geom) -> float:
    rings = rings_of(geom)
    pts = [p for ring in rings for p in ring]
    if not pts:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = (max(xs) - min(xs)) * 111_320 * math.cos(math.radians(sum(ys) / len(ys)))
    h = (max(ys) - min(ys)) * 110_570
    return math.hypot(w, h)


# ---------- 统计与可比 ----------
def in_bbox(lng, lat) -> bool:
    return BBOX[0] <= lng <= BBOX[1] and BBOX[2] <= lat <= BBOX[3]


def text(v) -> str:
    return "" if v is None else str(v).strip()


def norm(v) -> str:
    return "".join(ch for ch in text(v).lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def area_equivalent(a, b) -> bool:
    """区县等价：委托 code/er/geo_asset.py 的别名/代管表，避免两处口径漂移。"""
    if not text(a) or not text(b):
        return False
    return _area_equivalent(a, b)


def clean_admin(value, *, allow_dash: bool = True) -> str:
    """清洗高德返回的占位值：'[]' / 'None' 等一律视为空。"""
    v = text(value)
    if v in {"[]", "[ ]", "[  ]", "None", "none", "null", "NULL"} or (allow_dash and v == "-"):
        return ""
    return v


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


class Amap:
    def __init__(self, interval: float = 0.30):
        self.conn = http.client.HTTPSConnection("restapi.amap.com", timeout=20)
        self.interval = interval
        self.calls = 0

    def regeo(self, location: str) -> dict:
        q = urllib.parse.urlencode(
            {"key": KEY, "location": location, "output": "json", "extensions": "base", "radius": 1000}
        )
        for attempt in range(4):
            try:
                self.conn.request("GET", f"{REGEO}?{q}")
                data = json.loads(self.conn.getresponse().read().decode("utf-8"))
                self.calls += 1
                code = str(data.get("infocode", ""))
                if code == "10000":
                    time.sleep(self.interval)
                    return data
                if code in ABORT:
                    raise SystemExit(f"ABORT infocode={code} info={data.get('info')}（配额/key 问题，已保留缓存）")
                time.sleep(1.5 * (attempt + 1) if code in TRANSIENT else 1.0 * (attempt + 1))
            except SystemExit:
                raise
            except Exception:
                self.conn.close()
                self.conn = http.client.HTTPSConnection("restapi.amap.com", timeout=20)
                time.sleep(1.2 * (attempt + 1))
        return {}

    def close(self):
        self.conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, default=DATA / "外源数据" / "v2")
    ap.add_argument("--interval", type=float, default=0.30)
    ap.add_argument("--max-calls", type=int, default=0, help="0 = 不限")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not KEY:
        raise SystemExit("AMAP_KEY 未设置")
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "regeo_fangjiao.jsonl"

    # 1) 既有 878 条（键统一为 6 位小数）
    seeded: dict[str, dict] = {}
    with zipfile.ZipFile(RAW_CACHE) as z:
        for k, v in json.loads(z.read("regeo_check.json")).items():
            lng, lat = [float(x) for x in k.split("|", 1)[1].split(",")]
            seeded[f"{lng:.6f},{lat:.6f}"] = v

    # 2) 断点续跑
    done: dict[str, dict] = {}
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    done[rec["location"]] = rec["response"]
    print(f"seed={len(seeded)} 已缓存={len(done)}", flush=True)

    # 3) 目标记录
    asset_rows = list(csv.DictReader(ASSET.open("r", encoding="utf-8-sig", newline="")))
    polygons = {}
    for r in csv.DictReader(TRANSACTION.open("r", encoding="utf-8-sig", newline="")):
        polygons[r["愉悦安"]] = r["面坐标"]
    targets = []
    for r in asset_rows:
        if r["表"] != "房交":
            continue
        try:
            loc = f"{float(r['经度']):.6f},{float(r['纬度']):.6f}"
        except (TypeError, ValueError):
            continue
        targets.append((r, loc))
    if args.limit:
        targets = targets[: args.limit]
    print(f"房交 {len(targets)} 条", flush=True)

    api = Amap(args.interval)
    t0 = time.time()
    new_calls = 0
    buf = []

    def flush():
        nonlocal buf
        if not buf:
            return
        with cache_path.open("a", encoding="utf-8") as fh:
            for item in buf:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        buf = []

    def fetch(loc: str, rid: str) -> dict | None:
        nonlocal new_calls
        if loc in done:
            return done[loc]
        if loc in seeded:
            done[loc] = seeded[loc]
            buf.append({"location": loc, "record_id": rid, "response": seeded[loc], "source": "seed"})
            return seeded[loc]
        if args.max_calls and new_calls >= args.max_calls:
            return None
        resp = api.regeo(loc)
        new_calls += 1
        if resp:
            done[loc] = resp
            buf.append({"location": loc, "record_id": rid, "response": resp, "source": "api"})
        return resp or None

    # 4) 常规：业务质心 → regeo
    for i, (r, loc) in enumerate(targets, 1):
        fetch(loc, r["记录ID"])
        if i % 25 == 0:
            flush()
        if i % 200 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(targets)} 新增 {new_calls}，{el:.0f}s（{new_calls / max(el, 1e-9):.2f}/s）", flush=True)
    flush()
    print(f"常规轮完成：新增调用 {new_calls}，耗时 {time.time() - t0:.0f}s", flush=True)

    # 5) 异常面坐标：最大面面积加权质心 → wgs2gcj → regeo（只补区划，不改坐标）
    repaired: dict[str, dict] = {}
    anomalous = []
    for r, loc in targets:
        raw = polygons.get(r["记录ID"], "")
        if not raw:
            continue
        try:
            geom = ast.literal_eval(raw.strip())
        except Exception:
            continue
        if bbox_diagonal_m(geom) < 1000:
            continue
        rings = rings_of(geom)
        if not rings:
            continue
        big = max(rings, key=ring_area)
        cx, cy = ring_centroid(big)
        gx, gy = wgs2gcj(cx, cy)
        anomalous.append((r, f"{gx:.6f},{gy:.6f}"))
    print(f"异常面坐标（对角线 ≥1000m）{len(anomalous)} 条，开始补算", flush=True)
    for i, (r, loc) in enumerate(anomalous, 1):
        resp = fetch(loc, r["记录ID"])
        if resp:
            repaired[r["记录ID"]] = {"location": loc, "resp": resp}
        if i % 25 == 0:
            flush()
    flush()
    print(f"异常轮完成：累计新增调用 {new_calls}", flush=True)

    # 6) 组装 v2
    out_rows = []
    filled = filled_primary = filled_repaired = 0
    conflict = 0
    for r in asset_rows:
        row = dict(r)
        row["乡镇街道"] = ""
        row["行政区划来源"] = ""
        row["定位方式"] = ""
        if r["表"] == "房交":
            row["定位方式"] = "面坐标质心"
            try:
                loc = f"{float(r['经度']):.6f},{float(r['纬度']):.6f}"
            except (TypeError, ValueError):
                row["行政区划来源"] = "未解析"
                out_rows.append(row)
                continue
            base = done.get(loc)
            alt = repaired.get(r["记录ID"])
            chosen, src = None, ""
            if base and base.get("regeocode"):
                chosen, src = base, "逆地理编码(质心)"
            if alt and alt["resp"].get("regeocode"):
                ac_alt = alt["resp"]["regeocode"].get("addressComponent") or {}
                if area_equivalent(ac_alt.get("district"), r["区县"]):
                    ac_base = (base or {}).get("regeocode", {}).get("addressComponent") or {}
                    if not area_equivalent(ac_base.get("district"), r["区县"]):
                        chosen, src = alt["resp"], "逆地理编码(最大面质心)"
                        filled_repaired += 1
            if chosen:
                ac = chosen["regeocode"].get("addressComponent") or {}
                row["乡镇街道"] = clean_admin(ac.get("township"))
                row["高德区县"] = clean_admin(ac.get("district"))
                row["adcode"] = clean_admin(ac.get("adcode"))
                row["规范地址"] = clean_admin(chosen["regeocode"].get("formatted_address"))
                row["行政区划来源"] = src
                filled += 1
                filled_primary += 1
                if not area_equivalent(ac.get("district"), r["区县"]):
                    conflict += 1
            else:
                row["行政区划来源"] = "未解析"
            # 房交侧可信判据（规格 §4）：bbox + 面坐标对角线 + 区县等价；level 不适用
            reasons = []
            try:
                lng, lat = float(r["经度"]), float(r["纬度"])
                if not in_bbox(lng, lat):
                    reasons.append("outside_chongqing_bbox")
            except (TypeError, ValueError):
                reasons.append("missing_coordinate")
            raw_poly = polygons.get(r["记录ID"], "")
            diag = 0.0
            if raw_poly:
                try:
                    diag = bbox_diagonal_m(ast.literal_eval(raw_poly.strip()))
                except Exception:
                    diag = 0.0
            if diag >= 1000:
                reasons.append("polygon_bbox_ge_1000m")
            if row["高德区县"] and not area_equivalent(row["高德区县"], r["区县"]):
                reasons.append(
                    f"district_mismatch({row['高德区县']})"
                    if text(r["区县"])
                    else f"district_missing_in_source({row['高德区县']})"
                )
            if not row["高德区县"]:
                reasons.append("district_unresolved")
            row["可信_v2"] = int(not reasons)
            row["不可信原因_v2"] = ";".join(reasons)
        else:
            row["乡镇街道"] = text(r.get("街道或地址"))
            row["行政区划来源"] = "业务字段+地理编码"
            row["定位方式"] = "高德地理编码"
            row["可信_v2"] = 1 if r.get("可信") == "True" else 0
            row["不可信原因_v2"] = r.get("不可信原因", "")
        out_rows.append(row)

    fields = list(asset_rows[0].keys()) + ["乡镇街道", "行政区划来源", "定位方式", "可信_v2", "不可信原因_v2"]
    out_csv = out_dir / "asset1_poi_coord_v2.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    fangjiao = [r for r in out_rows if r["表"] == "房交"]
    township_ok = sum(1 for r in fangjiao if r["乡镇街道"])
    cached_api = 0
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and json.loads(line).get("source") == "api":
                    cached_api += 1
    manifest = {
        "source_asset": str(ASSET.relative_to(ROOT)), "source_sha256": sha256(ASSET),
        "raw_cache": str(RAW_CACHE.relative_to(ROOT)), "raw_cache_sha256": sha256(RAW_CACHE),
        "output": str(out_csv.relative_to(ROOT)), "output_sha256": sha256(out_csv),
        "rows_total": len(out_rows), "fangjiao_rows": len(fangjiao),
        "fangjiao_filled": filled, "fangjiao_township_nonempty": township_ok,
        "township_nonempty_rate": round(township_ok / max(1, len(fangjiao)), 4),
        "district_equivalence_conflicts": conflict,
        "fangjiao_trusted_v2": sum(1 for r in fangjiao if r["可信_v2"] == 1),
        "property_trusted_v2": sum(1 for r in out_rows if r["表"] == "物业处" and r["可信_v2"] == 1),
        "repaired_polygon_rows": len(anomalous), "repaired_adopted": filled_repaired,
        "api_calls_this_run": new_calls, "api_calls_in_cache": cached_api,
        "seed_reused": len(seeded),
        "method": "regeo(GCJ-02 面坐标质心) -> addressComponent.district/township/adcode",
        "coord_unchanged": True,
        "external_used_for_label": True,
        "external_used_for_label_note": "878 条 regeo 曾用于坐标系判定与金标准复核，且 878/878 均为 gold candidate",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (out_dir / "asset_v2_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
