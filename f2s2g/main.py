"""
F2S2G: 面向异构政务表格的多源实体匹配实验系统
==================================================

项目结构:
    f2s2g/
    ├── system.yaml                 # 全局配置文件（路径、超参数、模块开关）
    ├── configs/
    │   ├── field_mapping_a.yaml    # 任务A字段映射（物业处 ↔ 房屋交易中心）
    │   ├── field_mapping_b.yaml    # 任务B字段映射（征收处 ↔ 奥格科技）
    │   ├── enum_alias.yaml         # 枚举同义词典（取值归一化规则）
    │   └── graph_config.yaml       # 异构图辅助边配置
    ├── src/
    │   ├── data_loader.py          # 数据加载：解析SQL/CSV/Excel为DataFrame
    │   ├── f2s2g.py                # F2S2G三阶段框架（Field+Semantic+Graph）
    │   ├── knowledge_enhance.py    # 外部知识增强（长尾节点POI补全）
    │   ├── model.py                # GNN模型 + InfoNCE损失 + 分层负采样
    │   └── utils.py                # 共用工具（评估指标计算）
    ├── main.py                     # 入口脚本（本文件）
    ├── evaluate.py                 # 独立评估脚本
    ├── run_ablation.py             # 消融实验批量运行
    └── requirements.txt            # Python依赖

运行方式:
    # 1. 安装依赖
    pip install -r requirements.txt

    # 2. 运行完整实验（默认任务A）
    python main.py

    # 3. 指定任务
    python main.py --task A
    python main.py --task B

    # 4. 指定配置文件路径（可放在任意目录）
    python main.py --config /path/to/system.yaml

    # 5. 仅评估（跳过训练，加载已保存模型）
    python evaluate.py --config system.yaml --task A

    # 6. 运行全部消融实验
    python run_ablation.py --config system.yaml

    # 7. 清除缓存，强制重新计算所有步骤
    python main.py --task A --no-cache

环境要求:
    - Python >= 3.9
    - PyTorch >= 2.0 (支持CUDA)
    - scikit-learn >= 1.3
"""

import argparse
import sys
import os
import pickle
import hashlib
from pathlib import Path

import yaml
import numpy as np


def 加载配置(配置路径):
    """
    加载system.yaml配置文件，并记录配置文件所在目录

    Args:
        配置路径 (str): system.yaml的路径

    Returns:
        dict: 解析后的配置字典，额外包含 _config_dir 键
    """
    with open(配置路径, "r", encoding="utf-8") as f:
        配置 = yaml.safe_load(f)
    配置["_config_dir"] = str(Path(配置路径).parent.resolve())
    return 配置


def 解析路径(配置, 键):
    """
    将配置中的相对路径解析为绝对路径（支持点分隔嵌套键）

    Args:
        配置 (dict): 系统配置字典
        键 (str): 点分隔的配置键路径，如 'output_dir'

    Returns:
        str: 解析后的绝对路径
    """
    键列表 = 键.split(".")
    值 = 配置
    for k in 键列表:
        值 = 值[k]
    if not os.path.isabs(值):
        值 = os.path.join(配置["_config_dir"], 值)
    return 值


# ======================================================================
# 持久化缓存机制
# ======================================================================


def _获取缓存目录(配置):
    """获取缓存文件存放目录（output/cache/）"""
    输出目录 = 解析路径(配置, "output_dir")
    缓存目录 = os.path.join(输出目录, "cache")
    os.makedirs(缓存目录, exist_ok=True)
    return 缓存目录


def _计算配置哈希(配置, 任务):
    """
    根据影响当前步骤结果的配置项计算哈希值

    当配置改变时缓存自动失效，无需手动清除。
    """
    # 将影响结果的关键配置序列化后取哈希
    关键配置 = {
        "task": 任务,
        "seed": 配置.get("seed"),
        "split": 配置.get("split"),
        "semantic": 配置.get("semantic"),
        "graph": 配置.get("graph"),
        "knowledge_enhance": 配置.get("knowledge_enhance"),
    }
    配置字符串 = str(sorted(str(关键配置).encode("utf-8")))
    return hashlib.md5(配置字符串.encode()).hexdigest()[:8]


def _加载缓存(缓存路径):
    """尝试从磁盘加载缓存，失败返回None"""
    if os.path.exists(缓存路径):
        try:
            with open(缓存路径, "rb") as f:
                return pickle.load(f)
        except (pickle.UnpicklingError, EOFError, Exception):
            pass
    return None


def _保存缓存(缓存路径, 数据):
    """将中间产物保存到磁盘"""
    with open(缓存路径, "wb") as f:
        pickle.dump(数据, f, protocol=pickle.HIGHEST_PROTOCOL)


# ======================================================================
# 主流水线
# ======================================================================


def 运行实验流水线(配置, 任务, 使用缓存=True):
    """
    运行完整的F2S2G实验流水线（支持持久化缓存）

    缓存机制：
        - 每个步骤的输出保存为 output/cache/task_{任务}_{步骤}_{配置哈希}.pkl
        - 下次运行时如果缓存存在且配置未变，直接加载跳过计算
        - 修改system.yaml中的参数会自动使对应缓存失效
        - 使用 --no-cache 参数可强制重新计算

    Args:
        配置 (dict): 系统配置字典
        任务 (str): 任务标识 "A" 或 "B"
        使用缓存 (bool): 是否使用缓存，默认True

    Returns:
        dict: 评估结果字典
    """
    from src.data_loader import 加载任务数据
    from src.f2s2g import F2S2GPipeline
    from src.knowledge_enhance import 注入外部知识
    from src.model import 训练模型
    from src.utils import 评估指标

    print(f"{'='*60}")
    print(f"  F2S2G 实验流程 - 任务 {任务}")
    print(f"{'='*60}")

    缓存目录 = _获取缓存目录(配置)
    配置哈希 = _计算配置哈希(配置, 任务)

    # === 第1步：数据加载（不缓存，很快） ===
    print("\n[1/6] 加载数据...")
    源A记录, 源B记录, 标注对列表, 任务配置 = 加载任务数据(配置, 任务)
    print(f"  源A: {len(源A记录)} 条记录")
    print(f"  源B: {len(源B记录)} 条记录")
    print(f"  标注对: {len(标注对列表)} 对")

    # === 第2步：F2S2G 三阶段（缓存） ===
    缓存路径_stage = os.path.join(缓存目录, f"task_{任务}_f2s2g_{配置哈希}.pkl")
    缓存数据 = _加载缓存(缓存路径_stage) if 使用缓存 else None

    if 缓存数据 is not None:
        print("\n[2/6] F2S2G Pipeline [从缓存加载]")
        文本A, 文本B, 特征矩阵, 向量化器, 降维器, 图, 训练对, 验证对, 测试对 = 缓存数据
        print(f"  Stage2 特征矩阵: {特征矩阵.shape}")
        节点数 = 图.user节点数 + 图.item节点数 + 图.知识节点数
        边数 = sum(len(s) for s, _ in 图.边集.values())
        print(f"  Stage3 图: 节点数={节点数}, 边数={边数}")
    else:
        print("\n[2/6] F2S2G Pipeline...")
        流水线 = F2S2GPipeline(配置, 任务配置)

        文本A, 文本B = 流水线.stage1_字段类型化(源A记录, 源B记录)
        print(f"  Stage1 输出: {len(文本A) + len(文本B)} 条序列化文本")

        特征矩阵, 向量化器, 降维器 = 流水线.stage2_语义向量化(文本A, 文本B)
        print(f"  Stage2 输出: 特征矩阵 {特征矩阵.shape}")

        图, 训练对, 验证对, 测试对 = 流水线.stage3_构图(
            特征矩阵, 源A记录, 源B记录, 标注对列表, 配置
        )
        节点数 = 图.user节点数 + 图.item节点数 + 图.知识节点数
        边数 = sum(len(s) for s, _ in 图.边集.values())
        print(f"  Stage3 输出: 节点数={节点数}, 边数={边数}")

        # 保存缓存
        _保存缓存(缓存路径_stage, (文本A, 文本B, 特征矩阵, 向量化器, 降维器, 图, 训练对, 验证对, 测试对))
        print(f"  [缓存已保存]")

    # === 第3步：外部知识增强（缓存） ===
    知识增强配置 = 配置.get("knowledge_enhance", {})
    if 知识增强配置.get("enabled", True):
        缓存路径_知识 = os.path.join(缓存目录, f"task_{任务}_knowledge_{配置哈希}.pkl")
        缓存数据 = _加载缓存(缓存路径_知识) if 使用缓存 else None

        if 缓存数据 is not None:
            print("\n[3/6] 外部知识增强 [从缓存加载]")
            图 = 缓存数据
        else:
            print("\n[3/6] 外部知识增强...")
            图 = 注入外部知识(
                图, 源B记录, 特征矩阵, 向量化器, 降维器, 任务配置, 知识增强配置
            )
            _保存缓存(缓存路径_知识, 图)
            print(f"  [缓存已保存]")

        节点数 = 图.user节点数 + 图.item节点数 + 图.知识节点数
        边数 = sum(len(s) for s, _ in 图.边集.values())
        print(f"  增强后: 节点数={节点数}, 边数={边数}")
    else:
        print("\n[3/6] 外部知识增强 [已关闭]")

    # === 第4步：模型训练（不缓存，每次都训练） ===
    print("\n[4/6] 模型训练...")
    模型, 节点表示 = 训练模型(
        图, 训练对, 验证对, 源A记录, 源B记录, 特征矩阵, 配置
    )

    # === 第5步：评估 ===
    print("\n[5/6] 评估...")
    结果 = 评估指标(
        模型, 节点表示, 测试对, 源A记录, 源B记录, 特征矩阵, 配置
    )

    # === 第6步：输出结果 ===
    print("\n[6/6] 实验结果")
    print(f"  {'指标':<12} {'全量':>8} {'头部':>8} {'中部':>8} {'长尾':>8}")
    print(f"  {'-'*48}")
    for 指标名 in ["precision", "recall", "f1"]:
        行 = f"  {指标名:<12}"
        for 组 in ["all", "head", "mid", "tail"]:
            值 = 结果.get(f"{指标名}_{组}", 0)
            行 += f" {值:>7.4f}"
        print(行)

    # 保存模型权重
    输出目录 = 解析路径(配置, "output_dir")
    os.makedirs(输出目录, exist_ok=True)
    模型路径 = os.path.join(输出目录, f"model_task_{任务}.pt")
    import torch
    torch.save(模型.state_dict(), 模型路径)
    print(f"\n  模型已保存: {模型路径}")

    return 结果


def main():
    """
    程序主入口：解析命令行参数，加载配置，启动实验流水线
    """
    parser = argparse.ArgumentParser(description="F2S2G 多源实体匹配实验")
    parser.add_argument(
        "--config",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "system.yaml"),
        help="配置文件路径 (默认: system.yaml)",
    )
    parser.add_argument(
        "--task", type=str, default="A", choices=["A", "B", "all"], help="任务选择"
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子（覆盖配置）")
    parser.add_argument(
        "--no-cache", action="store_true", help="禁用缓存，强制重新计算所有步骤"
    )
    args = parser.parse_args()

    配置 = 加载配置(args.config)

    种子 = args.seed if args.seed is not None else 配置.get("seed", 42)
    np.random.seed(种子)
    try:
        import torch
        torch.manual_seed(种子)
    except ImportError:
        pass

    使用缓存 = not args.no_cache

    if args.task == "all":
        for t in ["A", "B"]:
            运行实验流水线(配置, t, 使用缓存)
    else:
        运行实验流水线(配置, args.task, 使用缓存)


if __name__ == "__main__":
    main()
