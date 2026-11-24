from __future__ import annotations

import csv
import itertools
import re
from pathlib import Path
from typing import Iterable

try:
    csv.field_size_limit(2**31 - 1)
except OverflowError:
    csv.field_size_limit(2**30)


def read_csv_sample(path: Path, limit: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(itertools.islice(csv.DictReader(handle), limit))


def read_sql_sample(path: Path, limit: int) -> list[dict[str, str]]:
    pattern = re.compile(r"INSERT INTO.*?\((.*?)\)\s*VALUES\s*\((.*)\);", re.I)
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            match = pattern.search(line)
            if not match:
                continue
            columns = [column.strip().strip('"') for column in match.group(1).split(",")]
            values = next(csv.reader([match.group(2)], skipinitialspace=True))
            row = {
                key: value.strip().strip("'")
                for key, value in zip(columns, values)
                if value.strip().upper() != "NULL"
            }
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def load_poi_sample(path: Path, limit: int) -> list[dict[str, str]]:
    return read_csv_sample(path, limit)


def standardize_property(row: dict[str, str], poi: dict[str, str] | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "id": row.get("village_id", row.get("id", "")),
        "name": row.get("village_name", ""),
        "area": row.get("area_name", ""),
        "street": row.get("street_name", ""),
        "address": row.get("address", ""),
        "type": row.get("property_type", ""),
    }
    if poi:
        try:
            result["lng"], result["lat"] = float(poi.get("经度", "")), float(poi.get("纬度", ""))
        except ValueError:
            pass
    return result


def standardize_transaction(row: dict[str, str], poi: dict[str, str] | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "id": row.get("愉悦安", ""),
        "name": row.get("小区名", ""),
        "area": row.get("区县", ""),
        "street": row.get("街道", ""),
        "address": row.get("地址", ""),
        "type": row.get("物业类型", ""),
    }
    if poi:
        try:
            result["lng"], result["lat"] = float(poi.get("经度", "")), float(poi.get("纬度", ""))
        except ValueError:
            pass
    return result


def index_poi(rows: Iterable[dict[str, str]], source: str) -> dict[str, dict[str, str]]:
    return {str(row.get("记录ID", "")): row for row in rows if row.get("表") == source}
