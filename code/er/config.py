from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "数据"


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    query_source: str
    candidate_source: str
    query_id: str
    candidate_id: str
    query_name: str
    candidate_name: str
    query_area: str
    candidate_area: str
    query_address: str = ""
    candidate_address: str = ""
    query_street: str = ""
    candidate_street: str = ""
    query_type: str = ""
    candidate_type: str = ""
    candidate_k: int = 20
    threshold: float = 0.72
    use_poi: bool = True


TASK_A = TaskConfig(
    task_id="A",
    query_source="property",
    candidate_source="transaction",
    query_id="village_id",
    candidate_id="yuyue_id",
    query_name="village_name",
    candidate_name="community_name",
    query_area="area_name",
    candidate_area="area_name",
    query_address="address",
    candidate_address="address",
    query_street="street_name",
    candidate_k=20,
)

TASK_B = TaskConfig(
    task_id="B",
    query_source="collection",
    candidate_source="auge",
    query_id="id",
    candidate_id="id",
    query_name="fwxxdz",
    candidate_name="fwxxdz",
    query_area="",
    candidate_area="",
    query_address="fwxxdz",
    candidate_address="fwxxdz",
    candidate_k=20,
    use_poi=False,
)

MAPPING_PATH = DATA / "A_mission_匹配映射_v2.csv"
A_QUERY_PATH = DATA / "A_物业处_的目标输出数据：小区基础信息数据.sql"
A_CANDIDATE_PATH = DATA / "A_房屋交易中心_合并数据.csv"
POI_PATH = DATA / "外源数据" / "asset1_poi_coord.csv"
ADMIN_PATH = DATA / "外源数据" / "asset2_admin_geo.csv"
B_WORKBOOK_PATH = DATA / "B_mission_房屋数据合并表格_修复ID.xlsx"
