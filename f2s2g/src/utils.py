"""
共用工具函数：评估指标计算

本模块提供模型评估所需的公共函数，包括：
    - 按长尾分组的评估（全量/头部/中部/长尾）
    - Hit@K 命中率计算
    - 名称字段自动检测
"""

import numpy as np
import torch


def 评估指标(模型, 节点表示, 测试对列表, 源A记录, 源B记录, 特征矩阵, 配置):
    """
    完整评估函数：计算全量及分组(头部/中部/长尾)的Precision/Recall/F1

    评估逻辑：
        对每个测试pair (user_a, item_b)，用user_a的embedding在所有item中
        做Top-K检索，检查真实匹配的item_b是否在Top-K结果中（Hit@K）。

    分组规则（按item侧关键字段出现频次）：
        - 头部(head): 出现≥6次的热门实体
        - 中部(mid):  出现2~5次的中频实体
        - 长尾(tail): 仅出现1次的稀有实体（占96.31%，是本文重点）

    Args:
        模型: 训练好的GNN模型（预留接口）
        节点表示 (tuple): (user表示, item表示) 张量元组
        测试对列表 (list[tuple]): 测试集匹配对 [(a_record_id, b_record_id), ...]
        源A记录 (list[dict]): 源A记录列表（用于ID→索引映射）
        源B记录 (list[dict]): 源B记录列表（用于ID→索引映射和频次统计）
        特征矩阵 (np.ndarray): 特征矩阵（预留接口）
        配置 (dict): 系统配置，读取inference.final_top_k

    Returns:
        dict: 评估结果字典，包含 precision_all, recall_all, f1_all 等
    """
    user表示, item表示 = 节点表示
    top_k = 配置["inference"]["final_top_k"]

    # 构建record_id → 数组索引的映射
    A的ID映射 = {r["_record_id"]: i for i, r in enumerate(源A记录)}
    B的ID映射 = {r["_record_id"]: i for i, r in enumerate(源B记录)}

    # 统计item节点的关键字段出现频次（用于划分头部/中部/长尾）
    名称字段 = _检测名称字段(源B记录)
    名称计数 = {}
    for r in 源B记录:
        名称 = str(r.get(名称字段, ""))
        名称计数[名称] = 名称计数.get(名称, 0) + 1

    # 每个item节点的频次
    节点频次 = {}
    for i, r in enumerate(源B记录):
        名称 = str(r.get(名称字段, ""))
        节点频次[i] = 名称计数.get(名称, 1)

    # 将测试对转为索引并按频次分组
    分组 = {"all": [], "head": [], "mid": [], "tail": []}

    for a_id, b_id in 测试对列表:
        if a_id not in A的ID映射 or b_id not in B的ID映射:
            continue
        a索引 = A的ID映射[a_id]
        b索引 = B的ID映射[b_id]
        频次 = 节点频次.get(b索引, 1)
        分组["all"].append((a索引, b索引))
        if 频次 >= 6:
            分组["head"].append((a索引, b索引))
        elif 频次 >= 2:
            分组["mid"].append((a索引, b索引))
        else:
            分组["tail"].append((a索引, b索引))

    # 逐组计算指标
    结果 = {}
    for 组名, 对列表 in 分组.items():
        if not 对列表:
            结果[f"precision_{组名}"] = 0.0
            结果[f"recall_{组名}"] = 0.0
            结果[f"f1_{组名}"] = 0.0
            continue

        命中数 = _计算命中数(user表示, item表示, 对列表, top_k)
        总数 = len(对列表)
        精确率 = 命中数 / 总数
        召回率 = 命中数 / 总数  # 每个query只有1个正确答案，P=R=Hit@K
        f1 = 2 * 精确率 * 召回率 / (精确率 + 召回率) if (精确率 + 召回率) > 0 else 0

        结果[f"precision_{组名}"] = 精确率
        结果[f"recall_{组名}"] = 召回率
        结果[f"f1_{组名}"] = f1

    return 结果


def _计算命中数(user表示, item表示, 对列表, top_k):
    """
    计算Hit@K命中数：对每个(user, item)对，检查item是否在user的Top-K检索结果中

    Args:
        user表示 (torch.Tensor): user节点表示矩阵 (num_users, embed_dim)
        item表示 (torch.Tensor): item节点表示矩阵 (num_items, embed_dim)
        对列表 (list[tuple]): 待评估的(user_idx, item_idx)对列表
        top_k (int): 检索返回的候选数量

    Returns:
        int: 命中数
    """
    命中数 = 0
    for a索引, b索引 in 对列表:
        if a索引 >= user表示.shape[0]:
            continue
        # 计算当前user与所有item的点积分数
        分数 = torch.matmul(user表示[a索引], item表示.T)
        # 取分数最高的Top-K个item索引
        topk索引 = 分数.topk(min(top_k, item表示.shape[0])).indices.cpu().numpy()
        # 检查正确答案是否在其中
        if b索引 in topk索引:
            命中数 += 1
    return 命中数


def _检测名称字段(源B记录):
    """
    自动检测records中的关键名称字段（用于频次统计和分组）

    按优先级尝试常见字段名，返回第一个存在的。

    Args:
        源B记录 (list[dict]): 源B记录列表

    Returns:
        str: 检测到的字段名
    """
    if not 源B记录:
        return ""
    样本 = 源B记录[0]
    for 候选 in ("小区名", "village_name", "fwxxdz", "征收处_房屋地址", "地址"):
        if 候选 in 样本:
            return 候选
    键列表 = [k for k in 样本.keys() if not k.startswith("_")]
    return 键列表[0] if 键列表 else ""


def 构建ID映射(记录列表):
    """
    构建record_id到数组索引的映射字典

    Args:
        记录列表 (list[dict]): 记录列表，每条需包含_record_id字段

    Returns:
        dict[str, int]: {record_id: 数组索引}
    """
    return {r["_record_id"]: i for i, r in enumerate(记录列表)}
