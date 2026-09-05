"""
数据加载模块：解析SQL/CSV/Excel为统一DataFrame格式

本模块负责从不同格式的原始数据文件中加载数据，并统一转换为
list[dict] 格式的记录列表，供后续F2S2G流水线使用。

支持的数据源格式：
    - SQL INSERT语句文件（物业处数据）
    - CSV文件（房屋交易中心数据、匹配映射）
    - Excel文件（征收处+奥格科技合并数据）
"""

import re
import os
import json
from pathlib import Path

import pandas as pd
import numpy as np
import yaml


def 解析路径(配置, 键路径):
    """
    根据点分隔的配置路径键，解析为绝对路径

    所有数据路径在system.yaml中以相对路径存储，本函数将其转换为
    基于system.yaml所在目录的绝对路径，使项目可在任意目录运行。

    Args:
        配置 (dict): 系统配置字典（必须包含_config_dir键）
        键路径 (str): 点分隔的配置键路径，如 "data.task_a.source_a"

    Returns:
        str: 解析后的绝对路径
    """
    键列表 = 键路径.split(".")
    值 = 配置
    for 键 in 键列表:
        值 = 值[键]
    if not os.path.isabs(值):
        值 = os.path.join(配置["_config_dir"], 值)
    return 值


def 解析SQL文件(SQL路径):
    """
    解析SQL INSERT语句文件为pandas DataFrame

    物业处的原始数据以SQL INSERT格式存储，每行一条INSERT语句。
    本函数逐行解析，提取列名和值，构建DataFrame。

    SQL格式示例:
        INSERT INTO "out_community_information"("id", "village_id", ...) VALUES (148905, 170442..., '山水家园', ...);

    Args:
        SQL路径 (str): SQL文件的绝对路径

    Returns:
        pd.DataFrame: 解析后的数据表，列名来自SQL语句中的字段定义
    """
    # 正则匹配INSERT语句的列名部分和VALUES部分
    正则模式 = re.compile(
        r"INSERT INTO [^(]+\(([^)]+)\)\s*VALUES\s*\((.+)\);", re.IGNORECASE
    )
    列名列表 = None
    行列表 = []

    with open(SQL路径, "r", encoding="utf-8") as f:
        for 行 in f:
            行 = 行.strip()
            if not 行.startswith("INSERT"):
                continue
            匹配结果 = 正则模式.match(行)
            if not 匹配结果:
                continue
            # 第一行确定列名
            if 列名列表 is None:
                列名列表 = [
                    c.strip().strip('"').strip("'") for c in 匹配结果.group(1).split(",")
                ]
            # 解析VALUES中的值
            值字符串 = 匹配结果.group(2)
            值列表 = _解析值列表(值字符串)
            行列表.append(值列表)

    数据表 = pd.DataFrame(行列表, columns=列名列表)
    return 数据表


def _解析值列表(值字符串):
    """
    解析SQL VALUES括号内的值列表，正确处理单引号转义和NULL

    需要处理的情况：
        - 字符串值：用单引号包裹，如 '山水家园'
        - 含转义单引号的字符串：如 'it''s' → "it's"
        - NULL值：转为Python None
        - 数值：自动转为int或float
        - 逗号分隔

    Args:
        值字符串 (str): VALUES括号内的原始字符串

    Returns:
        list: 解析后的值列表，与列名一一对应
    """
    值列表 = []
    i = 0
    n = len(值字符串)
    while i < n:
        # 跳过空格
        if 值字符串[i] == " ":
            i += 1
            continue
        # 跳过逗号分隔符
        if 值字符串[i] == ",":
            i += 1
            continue
        # 字符串值：以单引号开头
        if 值字符串[i] == "'":
            j = i + 1
            片段列表 = []
            while j < n:
                # 处理转义单引号 '' → '
                if 值字符串[j] == "'" and j + 1 < n and 值字符串[j + 1] == "'":
                    片段列表.append(值字符串[i + 1 : j + 1])
                    i = j + 1
                    j = i + 1
                # 正常结束的单引号
                elif 值字符串[j] == "'":
                    片段列表.append(值字符串[i + 1 : j])
                    break
                else:
                    j += 1
            值 = "".join(片段列表)
            值列表.append(值)
            i = j + 1
        # NULL值
        elif 值字符串[i : i + 4].upper() == "NULL":
            值列表.append(None)
            i += 4
        # 数值或其他
        else:
            j = i
            while j < n and 值字符串[j] not in (",", ")"):
                j += 1
            值 = 值字符串[i:j].strip()
            # 尝试转换为数值类型
            try:
                if "." in 值:
                    值 = float(值)
                else:
                    值 = int(值)
            except ValueError:
                pass
            值列表.append(值)
            i = j
    return 值列表


def 解析坐标(坐标字符串):
    """
    从JSON格式的坐标字符串中解析经纬度

    房屋交易中心的"点位坐标"列存储为JSON数组格式，如：
        "[106.565, 29.642]" 或 "[[106.565, 29.642], [106.566, 29.643]]"

    Args:
        坐标字符串 (str): JSON格式的坐标字符串

    Returns:
        tuple[float|None, float|None]: (经度, 纬度)，解析失败返回(None, None)
    """
    if pd.isna(坐标字符串) or not 坐标字符串:
        return None, None
    try:
        坐标数据 = json.loads(坐标字符串)
        if isinstance(坐标数据, list) and len(坐标数据) >= 2:
            # 直接是 [lng, lat] 格式
            if isinstance(坐标数据[0], (int, float)):
                return float(坐标数据[0]), float(坐标数据[1])
            # 嵌套数组 [[lng, lat], ...] 格式，取第一个点
            elif isinstance(坐标数据[0], list):
                return float(坐标数据[0][0]), float(坐标数据[0][1])
    except (json.JSONDecodeError, TypeError, IndexError):
        pass
    return None, None


def 加载任务数据(配置, 任务):
    """
    加载指定任务的全部数据（主入口函数）

    根据task参数分发到对应的加载函数，返回统一格式的数据。

    Args:
        配置 (dict): 系统配置字典
        任务 (str): 任务标识，"A" 或 "B"

    Returns:
        tuple: (源A记录, 源B记录, 标注对列表, 任务配置)
            - 源A记录 (list[dict]): 源A的记录列表，每条记录包含_record_id字段
            - 源B记录 (list[dict]): 源B的记录列表，每条记录包含_record_id字段
            - 标注对列表 (list[tuple[str,str]]): 标注匹配对列表 [(a_id, b_id), ...]
            - 任务配置 (dict): 当前任务的字段映射配置
    """
    if 任务 == "A":
        return _加载任务A(配置)
    elif 任务 == "B":
        return _加载任务B(配置)
    else:
        raise ValueError(f"未知任务: {任务}")


def _加载任务A(配置):
    """
    加载任务A数据：物业处 ↔ 房屋交易中心

    数据来源：
        - 源A（物业处）：SQL INSERT文件，8782行，含village_name/area_name/street_name等
        - 源B（房屋交易中心）：CSV文件，3260行，含小区名/区县/地址/物业公司等
        - 标注对：匹配映射CSV，2709对精确匹配（sql_village_id ↔ csv_yuyue_id）

    Returns:
        tuple: (源A记录, 源B记录, 标注对列表, 任务配置)
    """
    任务数据配置 = 配置["data"]["task_a"]
    配置目录 = 配置["_config_dir"]

    # 加载当前任务的字段映射配置
    映射路径 = os.path.join(配置目录, 任务数据配置["field_mapping"])
    with open(映射路径, "r", encoding="utf-8") as f:
        任务配置 = yaml.safe_load(f)

    # 加载物业处数据（从SQL INSERT文件解析）
    SQL路径 = os.path.join(配置目录, 任务数据配置["source_a"])
    数据表A = 解析SQL文件(SQL路径)

    # 加载房屋交易中心数据（CSV文件，UTF-8 BOM编码）
    CSV路径 = os.path.join(配置目录, 任务数据配置["source_b"])
    数据表B = pd.read_csv(CSV路径, encoding="utf-8-sig")

    # 解析房屋交易中心的"点位坐标"列为经纬度
    if "点位坐标" in 数据表B.columns:
        坐标数据 = 数据表B["点位坐标"].apply(解析坐标)
        数据表B["_lng"] = 坐标数据.apply(lambda x: x[0])
        数据表B["_lat"] = 坐标数据.apply(lambda x: x[1])

    # 加载标注匹配对
    标注路径 = os.path.join(配置目录, 任务数据配置["labels"])
    标注数据表 = pd.read_csv(标注路径, encoding="utf-8-sig")

    # 构建标注对列表：(源A的ID, 源B的ID)
    标注配置 = 任务配置["label_mapping"]
    标注对列表 = list(
        zip(
            标注数据表[标注配置["source_a_id"]].astype(str),
            标注数据表[标注配置["source_b_id"]].astype(str),
        )
    )

    # 为每条记录添加统一的_record_id字段（用于后续索引映射）
    ID字段A = 任务配置["source_a"]["id_field"]  # village_id
    ID字段B = 任务配置["source_b"]["id_field"]  # 愉悦安
    数据表A["_record_id"] = 数据表A[ID字段A].astype(str)
    数据表B["_record_id"] = 数据表B[ID字段B].astype(str)

    # 转换为list[dict]格式
    源A记录 = 数据表A.to_dict("records")
    源B记录 = 数据表B.to_dict("records")

    return 源A记录, 源B记录, 标注对列表, 任务配置


def _加载任务B(配置):
    """
    加载任务B数据：征收处 ↔ 奥格科技

    数据来源：
        - 合并Excel文件（28101行），同一行 = 已匹配的一对记录
        - 英文列头 = 奥格科技数据（如fwssqx=房屋所属区县）
        - "征收处_"前缀列 = 征收处数据

    特殊处理：
        - 将合并表按列拆分为两个独立的源
        - 同行即匹配对（行索引作为ID）

    Returns:
        tuple: (源A记录, 源B记录, 标注对列表, 任务配置)
    """
    任务数据配置 = 配置["data"]["task_b"]
    配置目录 = 配置["_config_dir"]

    # 加载字段映射配置
    映射路径 = os.path.join(配置目录, 任务数据配置["field_mapping"])
    with open(映射路径, "r", encoding="utf-8") as f:
        任务配置 = yaml.safe_load(f)

    # 加载合并Excel文件
    Excel路径 = os.path.join(配置目录, 任务数据配置["source_ab"])
    数据表 = pd.read_excel(Excel路径)

    # 根据字段映射配置，拆分为征收处侧和奥格侧
    源A映射 = 任务配置["source_a"]["field_map"]
    源B映射 = 任务配置["source_b"]["field_map"]

    # 提取征收处列（源A）
    列A = [v for v in 源A映射.values() if v is not None and v in 数据表.columns]
    数据表A = 数据表[列A].copy()
    数据表A["_record_id"] = 数据表A.index.astype(str)  # 行索引作为ID

    # 提取奥格列（源B）
    列B = [v for v in 源B映射.values() if v is not None and v in 数据表.columns]
    数据表B = 数据表[列B].copy()
    数据表B["_record_id"] = 数据表B.index.astype(str)  # 行索引作为ID

    # 标注对：同一行就是匹配对（28101对）
    标注对列表 = [
        (str(i), str(i)) for i in range(len(数据表))
    ]

    源A记录 = 数据表A.to_dict("records")
    源B记录 = 数据表B.to_dict("records")

    return 源A记录, 源B记录, 标注对列表, 任务配置
