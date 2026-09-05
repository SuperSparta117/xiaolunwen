"""
外部知识增强模块：对长尾节点进行POI知识补全并注入异构图

核心思路：
    1. 识别长尾节点（小区名/地址出现次数≤1的孤立节点）
    2. 对长尾节点调用百度地图POI API查询，获取标准名称、坐标、行政区划
    3. 将POI候选构造为knowledge节点，通过带置信度权重的completed_by边连接到原节点
    4. GNN聚合时，长尾节点可以从knowledge邻居获取额外语义信号

支持两种POI查询模式：
    - 真实模式：调用百度地图地点搜索API（需联网+AK配置）
    - 模拟模式：基于编辑距离的离线模拟（无需联网，用于离线实验）
模式通过 system.yaml 中 knowledge_enhance.poi_mode 配置切换。
"""

import numpy as np
import torch
import requests
import time

from src.f2s2g import 异构图


# ======================================================================
# 百度地图API配置
# ======================================================================
百度AK = "S1KV7D8DzYRc40Psey6aD50jGFEW0tYJ"
百度地点搜索URL = "https://api.map.baidu.com/place/v2/search"


def 注入外部知识(图, 源B记录列表, 特征矩阵, 向量化器, 降维器, 任务配置, 知识增强配置):
    """
    外部知识注入主函数：对长尾节点执行知识补全，返回扩展后的知识增强图G'

    整体流程：
        原图G → 识别长尾节点 → POI查询获取候选 → 编码为knowledge节点 →
        通过completed_by边(带置信度权重)连入图 → 输出知识增强图G'

    Args:
        图 (异构图): Stage 3输出的原始异构图G
        源B记录列表 (list[dict]): 源B（item侧）的原始记录列表
        特征矩阵 (np.ndarray): Stage 2输出的N×d稠密特征矩阵
        向量化器 (TfidfVectorizer): Stage 2拟合好的TF-IDF向量化器（复用编码器）
        降维器 (TruncatedSVD): Stage 2拟合好的SVD降维器（复用编码器）
        任务配置 (dict): 当前任务的字段映射配置
        知识增强配置 (dict): 知识增强相关配置参数

    Returns:
        异构图: 知识增强后的异构图G'
    """
    # 从配置中读取参数
    候选数量 = 知识增强配置.get("top_k", 3)
    置信度阈值 = 知识增强配置.get("tau_conf", 0.5)
    长尾阈值 = 知识增强配置.get("long_tail_threshold", 1)
    查询模式 = 知识增强配置.get("poi_mode", "simulate")

    # 第一步：识别所有长尾节点的索引
    长尾节点列表 = _识别长尾节点(源B记录列表, 任务配置, 长尾阈值)
    if not 长尾节点列表:
        return 图

    # 构建全量名称库
    名称字段 = _获取名称字段(任务配置)
    全部名称 = [str(r.get(名称字段, "")) for r in 源B记录列表]

    # 获取区县字段（用于百度API的region参数）
    区县字段 = _获取区县字段(任务配置)

    # 第二步：对每个长尾节点执行POI查询，收集补全信息
    知识文本列表 = []           # 知识节点的序列化文本
    补全边源端 = []             # 补全边的源端（item节点索引）
    补全边目标端 = []           # 补全边的目标端（knowledge节点索引）
    补全边权重 = []             # 补全边的置信度权重

    for 节点索引 in 长尾节点列表:
        查询名称 = 全部名称[节点索引]
        if not 查询名称 or 查询名称 in ("<MISSING>", "nan", "None"):
            continue

        # 获取当前节点的区县信息
        当前记录 = 源B记录列表[节点索引]
        区县 = str(当前记录.get(区县字段, "重庆市")) if 区县字段 else "重庆市"

        # 根据模式选择查询方式
        if 查询模式 == "baidu":
            候选列表 = _百度POI查询(
                查询名称, 区县, 候选数量, 知识增强配置.get("baidu_ak", 百度AK)
            )
        else:
            候选列表 = _模拟POI查询(查询名称, 全部名称, 节点索引, 候选数量)

        for 知识文本, 置信度 in 候选列表:
            if 置信度 < 置信度阈值:
                continue
            知识文本列表.append(知识文本)
            补全边源端.append(节点索引)
            补全边目标端.append(len(知识文本列表) - 1)
            补全边权重.append(置信度)

    if not 知识文本列表:
        return 图

    # 第三步：用同一个TF-IDF+SVD编码器编码知识节点的特征
    知识稀疏矩阵 = 向量化器.transform(知识文本列表)
    知识特征 = 降维器.transform(知识稀疏矩阵).astype(np.float32)

    # 第四步：构建扩展图G'
    知识节点数 = len(知识文本列表)
    增强图 = 异构图(图.user节点数, 图.item节点数, 知识节点数=知识节点数)

    # 复制原图的所有边
    for 边类型, (源, 目标) in 图.边集.items():
        增强图.添加边(边类型, 源, 目标, 图.边权重.get(边类型))

    # 添加补全边
    权重张量 = torch.tensor(补全边权重, dtype=torch.float32)
    增强图.添加边(
        "completed_by",
        torch.tensor(补全边源端, dtype=torch.int64),
        torch.tensor(补全边目标端, dtype=torch.int64),
        权重张量,
    )
    增强图.添加边(
        "completes",
        torch.tensor(补全边目标端, dtype=torch.int64),
        torch.tensor(补全边源端, dtype=torch.int64),
        权重张量,
    )

    # 挂载节点特征
    增强图.节点特征["user"] = 图.节点特征["user"]
    增强图.节点特征["item"] = 图.节点特征["item"]
    增强图.节点特征["knowledge"] = torch.tensor(知识特征, dtype=torch.float32)

    return 增强图


# ======================================================================
# 真实百度地图POI查询
# ======================================================================


def _百度POI查询(查询名称, 区域, 候选数量, ak):
    """
    调用百度地图地点搜索API，查询与查询名称匹配的POI信息

    Args:
        查询名称 (str): 查询关键词（长尾节点的小区名/地址）
        区域 (str): 搜索区域限定（如"渝中区"、"重庆市"）
        候选数量 (int): 最多返回几个候选
        ak (str): 百度地图服务端AK密钥

    Returns:
        list[tuple[str, float]]: [(序列化文本, 置信度), ...]
    """
    参数 = {
        "query": 查询名称,
        "region": 区域,
        "city_limit": "true",
        "output": "json",
        "ak": ak,
        "page_size": 候选数量,
        "page_num": 0,
    }

    try:
        响应 = requests.get(百度地点搜索URL, params=参数, timeout=5)
        数据 = 响应.json()
    except (requests.RequestException, ValueError) as e:
        print(f"    [POI] 请求失败: {查询名称} -> {e}")
        return []

    if 数据.get("status") != 0:
        print(f"    [POI] API错误: {查询名称} -> status={数据.get('status')}, msg={数据.get('message', '')}")
        return []

    结果列表 = []
    for poi in 数据.get("results", [])[:候选数量]:
        poi名称 = poi.get("name", "")
        poi地址 = poi.get("address", "")
        poi区县 = poi.get("area", "")
        坐标 = poi.get("location", {})
        poi经度 = 坐标.get("lng", 0)
        poi纬度 = 坐标.get("lat", 0)

        # 计算置信度
        置信度 = _计算名称相似度(查询名称, poi名称)

        # 序列化为F2S2G格式文本
        部分 = [f"[TABLE=POI]"]
        if poi名称:
            部分.append(f"[名称]{poi名称}")
        if poi地址:
            部分.append(f"[地址]{poi地址}")
        if poi区县:
            部分.append(f"[区县]{poi区县}")
        if poi经度 and poi纬度:
            部分.append(f"[经度]{poi经度:.6f}")
            部分.append(f"[纬度]{poi纬度:.6f}")

        知识文本 = " ".join(部分)
        结果列表.append((知识文本, 置信度))

    # 控制API调用频率
    time.sleep(0.1)

    return 结果列表


def _计算名称相似度(查询名称, poi名称):
    """
    计算查询名称与POI返回名称之间的相似度，作为置信度

    综合考虑编辑距离相似度和包含关系加分

    Args:
        查询名称 (str): 原始查询名称
        poi名称 (str): POI返回的标准名称

    Returns:
        float: 置信度，范围[0, 1]
    """
    if not 查询名称 or not poi名称:
        return 0.0

    # 编辑距离归一化相似度
    距离 = _计算编辑距离(查询名称, poi名称)
    最大长度 = max(len(查询名称), len(poi名称), 1)
    编辑相似度 = 1.0 - 距离 / 最大长度

    # 包含关系加分
    包含加分 = 0.0
    if 查询名称 in poi名称 or poi名称 in 查询名称:
        包含加分 = 0.15

    置信度 = min(1.0, 编辑相似度 + 包含加分)
    return 置信度


# ======================================================================
# 离线模拟POI查询（备用方案）
# ======================================================================


def _模拟POI查询(查询名称, 全部名称, 排除索引, 候选数量):
    """
    [备用] 模拟POI查询：用编辑距离在名称库中查找最相似的Top-K候选

    当无法访问百度地图API时使用此函数作为降级方案。

    Args:
        查询名称 (str): 待查询的名称
        全部名称 (list[str]): 全量名称库
        排除索引 (int): 排除自身的索引
        候选数量 (int): 返回候选数量上限

    Returns:
        list[tuple[str, float]]: [(序列化文本, 置信度), ...]
    """
    结果列表 = []
    for i, 名称 in enumerate(全部名称):
        if i == 排除索引 or not 名称 or 名称 in ("nan", "None", "<MISSING>"):
            continue
        距离 = _计算编辑距离(查询名称, 名称)
        最大长度 = max(len(查询名称), len(名称), 1)
        相似度 = 1.0 - 距离 / 最大长度
        if 相似度 > 0.3:
            知识文本 = f"[TABLE=POI] [名称]{名称}"
            结果列表.append((知识文本, 相似度))

    结果列表.sort(key=lambda x: -x[1])
    return 结果列表[:候选数量]


# ======================================================================
# 工具函数
# ======================================================================


def _识别长尾节点(源B记录列表, 任务配置, 阈值):
    """
    识别长尾节点：统计关键字段的出现频次，≤阈值的视为长尾

    Args:
        源B记录列表 (list[dict]): 源B记录列表
        任务配置 (dict): 任务配置
        阈值 (int): 频次阈值

    Returns:
        list[int]: 长尾节点的索引列表
    """
    名称字段 = _获取名称字段(任务配置)

    名称计数 = {}
    for i, r in enumerate(源B记录列表):
        名称 = str(r.get(名称字段, ""))
        名称计数.setdefault(名称, []).append(i)

    长尾节点 = []
    for 名称, 索引列表 in 名称计数.items():
        if len(索引列表) <= 阈值:
            长尾节点.extend(索引列表)
    return 长尾节点


def _获取名称字段(任务配置):
    """
    从任务配置中自动检测关键匹配字段名（源B侧）

    优先级：小区名 > 地址 > 第一个非空字段

    Args:
        任务配置 (dict): 任务配置

    Returns:
        str: 源B中对应的原始列名
    """
    字段映射 = 任务配置["source_b"]["field_map"]
    for 候选 in ("小区名", "地址"):
        if 候选 in 字段映射 and 字段映射[候选] is not None:
            return 字段映射[候选]
    第一个值 = next(v for v in 字段映射.values() if v is not None)
    return 第一个值


def _获取区县字段(任务配置):
    """
    从任务配置中获取区县字段名

    Args:
        任务配置 (dict): 任务配置

    Returns:
        str or None: 源B中区县字段的原始列名
    """
    字段映射 = 任务配置["source_b"]["field_map"]
    if "区县" in 字段映射 and 字段映射["区县"] is not None:
        return 字段映射["区县"]
    return None


def _计算编辑距离(字符串1, 字符串2):
    """
    计算两个字符串的编辑距离（Levenshtein Distance）

    编辑距离 = 将字符串1变为字符串2所需的最少操作数（插入/删除/替换各算1次）

    Args:
        字符串1 (str): 字符串1
        字符串2 (str): 字符串2

    Returns:
        int: 编辑距离值
    """
    m, n = len(字符串1), len(字符串2)
    if m > n:
        字符串1, 字符串2, m, n = 字符串2, 字符串1, n, m

    上一行 = list(range(n + 1))
    for i in range(1, m + 1):
        当前行 = [i] + [0] * n
        for j in range(1, n + 1):
            代价 = 0 if 字符串1[i - 1] == 字符串2[j - 1] else 1
            当前行[j] = min(
                当前行[j - 1] + 1,    # 插入
                上一行[j] + 1,         # 删除
                上一行[j - 1] + 代价   # 替换
            )
        上一行 = 当前行
    return 上一行[n]
