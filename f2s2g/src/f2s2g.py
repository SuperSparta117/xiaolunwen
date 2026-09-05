"""
F2S2G 三阶段框架：Field → Semantic → Graph
将多源异构表格转化为异构图（纯PyTorch实现，不依赖DGL）

本模块实现了完整的 F2S2G 流水线，包含三个核心阶段：
1. Field（字段阶段）：对原始表格记录进行字段类型化与语义序列化，
   将结构化数据转化为统一格式的文本序列。
2. Semantic（语义阶段）：使用字符级 n-gram TF-IDF 提取文本特征，
   再通过 SVD 降维获得稠密向量表示。
3. Graph（图构建阶段）：基于标注对和辅助关系构建异构图，
   支持匹配边、同区域边、地理邻近边、同物业公司边等多种边类型。
"""

import os
import re
import math

import numpy as np
import pandas as pd
import yaml
import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD


class 异构图:
    """
    轻量级异构图容器（替代DGL的自定义实现）。

    该类用于存储异构图的节点特征和多种类型的边关系，
    支持将整个图迁移到指定设备（CPU/GPU）。

    异构图包含三种节点类型：
    - user：源表A中的记录节点
    - item：源表B中的记录节点
    - knowledge：可选的知识节点（如外部知识库实体）

    边类型包括：
    - rate / rated_by：主匹配边（user→item 及其反向边）
    - user_same_district / item_same_district：同区域辅助边
    - user_geo_near：地理邻近辅助边
    - user_same_company / item_same_company：同物业公司辅助边
    """

    def __init__(self, user节点数, item节点数, 知识节点数=0):
        """
        初始化异构图容器。

        Args:
            user节点数: user类型节点的数量（源表A的记录数）
            item节点数: item类型节点的数量（源表B的记录数）
            知识节点数: knowledge类型节点的数量，默认为0表示不使用知识节点
        """
        self.user节点数 = user节点数
        self.item节点数 = item节点数
        self.知识节点数 = 知识节点数
        self.边集 = {}        # {edge_type: (src_tensor, dst_tensor)}，存储各类型边的源节点和目标节点索引
        self.边权重 = {} # {edge_type: weight_tensor}，存储各类型边的权重（可选）
        self.节点特征 = {}    # {"user": tensor, "item": tensor, "knowledge": tensor}，存储各类型节点的特征向量

    def 添加边(self, 边类型, 源节点, 目标节点, 权重=None):
        """
        向图中添加一种类型的边。

        Args:
            边类型: 边类型名称，如 "rate"、"same_district" 等
            源节点: 源节点索引张量，shape为 (num_edges,)
            目标节点: 目标节点索引张量，shape为 (num_edges,)
            权重: 可选的边权重张量，shape为 (num_edges,)，默认为None表示无权重
        """
        self.边集[边类型] = (源节点, 目标节点)
        if 权重 is not None:
            self.边权重[边类型] = 权重

    def to(self, device):
        """
        将整个异构图迁移到指定的计算设备上。

        创建一个新的 异构图 实例，将所有张量（边索引、边权重、节点特征）
        迁移到目标设备，用于GPU加速训练。

        Args:
            device: 目标设备，如 torch.device("cuda:0") 或 "cpu"

        Returns:
            异构图: 一个新的异构图实例，所有张量已迁移到目标设备
        """
        # 创建新的图容器，保持节点数量不变
        新图 = 异构图(self.user节点数, self.item节点数, self.知识节点数)
        # 迁移所有边索引张量
        for k, (s, d) in self.边集.items():
            新图.边集[k] = (s.to(device), d.to(device))
        # 迁移所有边权重张量
        for k, w in self.边权重.items():
            新图.边权重[k] = w.to(device)
        # 迁移所有节点特征张量
        for k, f in self.节点特征.items():
            新图.节点特征[k] = f.to(device)
        return 新图


class F2S2GPipeline:
    """
    F2S2G 三阶段流水线主类。

    该类封装了从原始表格数据到异构图的完整转换流程：
    - Stage 1 (Field)：字段类型化与语义序列化，将结构化记录转为统一文本
    - Stage 2 (Semantic)：TF-IDF + SVD 语义向量化，生成稠密特征表示
    - Stage 3 (Graph)：异构图构建，包含匹配边和多种辅助边

    使用方式：
        pipeline = F2S2GPipeline(system_cfg, task_cfg)
        文本A, 文本B = pipeline.stage1_字段类型化(records_a, records_b)
        features, vectorizer, svd = pipeline.stage2_语义向量化(文本A, 文本B)
        graph, train, val, test = pipeline.stage3_构图(features, records_a, records_b, pairs, cfg)
    """

    def __init__(self, system_cfg, task_cfg):
        """
        初始化 F2S2G 流水线。

        加载系统配置和任务配置，并读取枚举别名映射表和图构建配置。

        Args:
            system_cfg: 系统级配置字典，包含以下关键字段：
                - _config_dir: 配置文件目录路径
                - configs.enum_alias: 枚举别名配置文件名
                - configs.graph: 图构建配置文件名
                - semantic: 语义向量化相关参数
                - seed: 随机种子
            task_cfg: 任务级配置字典，包含以下关键字段：
                - source_a: 源表A的配置（table_name, field_map）
                - source_b: 源表B的配置（table_name, field_map）
        """
        self.system_cfg = system_cfg
        self.task_cfg = task_cfg
        配置目录 = system_cfg["_config_dir"]

        # 加载枚举别名映射表（用于字段值标准化）
        枚举路径 = os.path.join(配置目录, system_cfg["configs"]["enum_alias"])
        with open(枚举路径, "r", encoding="utf-8") as f:
            self.枚举别名 = yaml.safe_load(f)

        # 加载图构建配置（定义辅助边的构建规则）
        图配置路径 = os.path.join(配置目录, system_cfg["configs"]["graph"])
        with open(图配置路径, "r", encoding="utf-8") as f:
            self.图配置 = yaml.safe_load(f)

    # ======================================================================
    # Stage 1: Field — 字段类型化与语义序列化
    # ======================================================================

    def stage1_字段类型化(self, records_a, records_b):
        """
        第一阶段：将原始表格记录序列化为统一格式的文本序列。

        对两个源表的每条记录，按照字段映射关系提取字段值，
        经过标准化处理后拼接成带有字段标签的文本序列。

        序列化格式示例：
            "[TABLE=物业处] [地址]某某路123号 [面积]1500.0 [用途]住宅"

        Args:
            records_a: 源表A的记录列表，每条记录为字典格式
            records_b: 源表B的记录列表，每条记录为字典格式

        Returns:
            tuple: (文本A, 文本B)
                - 文本A: 源表A各记录的序列化文本列表
                - 文本B: 源表B各记录的序列化文本列表
        """
        源A配置 = self.task_cfg["source_a"]
        源B配置 = self.task_cfg["source_b"]

        # 对源表A的每条记录进行序列化
        文本A = [
            self._序列化记录(r, 源A配置["table_name"], 源A配置["field_map"])
            for r in records_a
        ]
        # 对源表B的每条记录进行序列化
        文本B = [
            self._序列化记录(r, 源B配置["table_name"], 源B配置["field_map"])
            for r in records_b
        ]
        return 文本A, 文本B

    def _序列化记录(self, 记录, 表名, 字段映射):
        """
        将单条记录序列化为带有字段标签的文本。

        按照统一字段名（unified_name）的顺序，逐一提取原始列值，
        经过标准化后拼接为 "[字段名]值" 格式的文本序列。

        Args:
            记录: 单条记录字典，key为原始列名，value为字段值
            表名: 表名标识，用于在序列化文本中标注数据来源
            字段映射: 字段映射字典，{统一字段名: 原始列名}

        Returns:
            str: 序列化后的文本，如 "[TABLE=物业处] [地址]某路1号 [面积]100.0"
        """
        # 以表名标签开头
        部分 = [f"[TABLE={表名}]"]
        for 统一字段名, 原始列名 in 字段映射.items():
            # 跳过未映射的字段（原始列名为None）
            if 原始列名 is None:
                continue
            值 = 记录.get(原始列名)
            # 对字段值进行标准化处理
            值 = self._标准化取值(值, 统一字段名)
            部分.append(f"[{统一字段名}]{值}")
        return " ".join(部分)

    def _标准化取值(self, 值, 字段名):
        """
        对字段值进行综合标准化处理。

        根据字段名的类型，依次执行以下标准化操作：
        1. 缺失值统一替换为 <MISSING> 标记
        2. 地址类字段执行地址标准化（去空格、全角转半角等）
        3. 枚举类字段执行别名归一化
        4. 数值类字段执行格式化（控制小数位数）
        5. 多值字段执行分隔符统一
        6. 公司名称字段执行格式标准化

        Args:
            值: 原始字段值，可以是任意类型
            字段名: 统一字段名，用于确定标准化策略

        Returns:
            str: 标准化后的字段值字符串
        """
        # 处理缺失值：None、NaN、空字符串等统一为 <MISSING>
        if 值 is None or (isinstance(值, float) and math.isnan(值)):
            return "<MISSING>"
        值 = str(值).strip()
        if 值 in ("", "null", "NULL", "None", "未填写", "nan"):
            return "<MISSING>"

        # 地址类字段：去除多余空格、全角转半角、规范化门牌号
        if 字段名 in ("地址", "街道", "小区名"):
            值 = self._标准化地址(值)

        # 枚举类字段：将别名映射为标准值
        值 = self._枚举归一(值, 字段名)

        # 数值类字段：按不同精度格式化
        if 字段名 in ("面积", "建筑面积"):
            值 = self._格式化数值(值, 小数位数=1)
        elif 字段名 in ("层数",):
            值 = self._格式化数值(值, 小数位数=0)
        elif 字段名 in ("年份",):
            值 = self._格式化数值(值, 小数位数=0)
        elif 字段名 in ("经度", "纬度"):
            值 = self._格式化数值(值, 小数位数=6)

        # 多值字段：统一分隔符为竖线
        if 字段名 in ("用途",):
            值 = self._多值展开(值)

        # 公司名称：全角转半角、括号标准化
        if 字段名 in ("物业公司", "管理单位", "建设单位"):
            值 = self._标准化公司名(值)

        return 值

    def _标准化地址(self, 值):
        """
        地址字段标准化处理。

        执行以下操作：
        1. 去除全角空格、半角空格、不间断空格
        2. 全角字符转半角字符
        3. 修复数字与量词之间的多余空格（如"123 号" → "123号"）

        Args:
            值: 原始地址字符串

        Returns:
            str: 标准化后的地址字符串
        """
        # 去除各类空白字符（全角空格、普通空格、不间断空格）
        值 = 值.replace("　", "").replace(" ", "").replace(" ", "")
        # 全角字符统一转换为半角字符
        值 = self._全角转半角(值)
        # 去除数字与门牌号量词之间的空格
        值 = re.sub(r"(\d)\s+(号|栋|幢|楼|期|组团)", r"\1\2", 值)
        return 值

    def _全角转半角(self, s):
        """
        将字符串中的全角字符转换为半角字符。

        转换规则：
        - 全角ASCII字符（！到～，Unicode 0xFF01-0xFF5E）转为对应半角字符
        - 全角空格（Unicode 0x3000）转为半角空格

        Args:
            s: 可能包含全角字符的字符串

        Returns:
            str: 全角字符已转换为半角的字符串
        """
        结果 = []
        for 字符 in s:
            编码 = ord(字符)
            # 全角ASCII字符范围：0xFF01（！）到0xFF5E（～）
            if 0xFF01 <= 编码 <= 0xFF5E:
                # 全角转半角：Unicode码点减去0xFEE0的偏移量
                结果.append(chr(编码 - 0xFEE0))
            elif 编码 == 0x3000:
                # 全角空格转半角空格
                结果.append(" ")
            else:
                结果.append(字符)
        return "".join(结果)

    def _枚举归一(self, 值, 字段名):
        """
        枚举值别名归一化。

        根据预加载的枚举别名配置表，将同义词映射为标准值。
        例如："住宅楼"、"居民楼" → "住宅"

        Args:
            值: 原始枚举值字符串
            字段名: 统一字段名，用于查找对应的别名映射表

        Returns:
            str: 标准化后的枚举值；若无匹配别名则原样返回
        """
        # 如果该字段没有配置枚举别名，直接返回原值
        if 字段名 not in self.枚举别名:
            return 值
        别名字典 = self.枚举别名[字段名]
        # 遍历所有标准值及其别名列表，查找匹配
        for 标准值, 别名列表 in 别名字典.items():
            if 值 in 别名列表 or 值 == 标准值:
                return 标准值
        return 值

    def _格式化数值(self, 值, 小数位数=1):
        """
        数值格式化，统一数值的小数位数表示。

        Args:
            值: 原始值字符串（应为可转换为浮点数的格式）
            小数位数: 保留的小数位数，0表示取整

        Returns:
            str: 格式化后的数值字符串；若无法转换则原样返回
        """
        try:
            数值 = float(值)
            if 小数位数 == 0:
                # 整数：四舍五入后转为整数字符串
                return str(int(round(数值)))
            # 浮点数：保留指定小数位
            return f"{数值:.{小数位数}f}"
        except (ValueError, TypeError):
            # 无法解析为数值时，返回原始字符串
            return 值

    def _多值展开(self, 值):
        """
        多值字段分隔符统一处理。

        将中文逗号、顿号、分号等分隔符统一为竖线(|)，
        并去除各子项的前后空格。

        Args:
            值: 原始多值字符串，如 "住宅，商业、办公"

        Returns:
            str: 统一分隔符后的字符串，如 "住宅|商业|办公"
        """
        # 将各类分隔符统一为英文逗号
        值 = 值.replace("，", ",").replace("、", ",").replace(";", ",")
        # 按逗号分割、去空格、过滤空串，再用竖线连接
        部分 = [p.strip() for p in 值.split(",") if p.strip()]
        return "|".join(部分)

    def _标准化公司名(self, 值):
        """
        公司名称标准化处理。

        执行以下操作：
        1. 全角字符转半角字符
        2. 中文括号转英文括号

        Args:
            值: 原始公司名称字符串

        Returns:
            str: 标准化后的公司名称
        """
        # 全角转半角
        值 = self._全角转半角(值)
        # 中文括号统一转为英文括号
        值 = 值.replace("（", "(").replace("）", ")")
        return 值

    # ======================================================================
    # Stage 2: Semantic — 字符级n-gram TF-IDF + SVD 向量化
    # ======================================================================

    def stage2_语义向量化(self, 文本A, 文本B):
        """
        第二阶段：将序列化文本转化为稠密语义向量。

        处理流程：
        1. 合并两个源表的文本序列
        2. 使用字符级 n-gram TF-IDF 提取稀疏特征矩阵
        3. 使用 TruncatedSVD 进行降维，得到稠密向量表示

        字符级 n-gram 的优势：
        - 不依赖分词器，适合中文和混合文本
        - 能捕捉字符级别的相似性（如地址中的部分匹配）
        - 对错别字和缩写有一定容错能力

        Args:
            文本A: 源表A的序列化文本列表（来自stage1_字段类型化的输出）
            文本B: 源表B的序列化文本列表（来自stage1_字段类型化的输出）

        Returns:
            tuple: (降维特征, 向量化器, svd)
                - 降维特征: 降维后的特征矩阵，shape=(n_a+n_b, svd_components)，dtype=float32
                - 向量化器: 训练好的TfidfVectorizer对象（可用于新数据转换）
                - svd: 训练好的TruncatedSVD对象（可用于新数据降维）
        """
        语义配置 = self.system_cfg["semantic"]
        # 合并两个表的文本，统一进行TF-IDF特征提取
        全部文本 = 文本A + 文本B

        # 构建字符级 n-gram TF-IDF 向量化器
        向量化器 = TfidfVectorizer(
            analyzer=语义配置["analyzer"],           # 分析粒度，通常为 "char" 或 "char_wb"
            ngram_range=tuple(语义配置["ngram_range"]),  # n-gram范围，如 (2, 4) 表示2-gram到4-gram
            min_df=语义配置["min_df"],               # 最小文档频率，过滤稀有特征
        )
        # 拟合并转换为稀疏TF-IDF矩阵
        稀疏矩阵 = 向量化器.fit_transform(全部文本)

        # 使用 TruncatedSVD 对稀疏矩阵进行降维
        svd = TruncatedSVD(
            n_components=语义配置["svd_components"],  # 目标维度数
            random_state=self.system_cfg["seed"]     # 固定随机种子以确保可重复性
        )
        降维特征 = svd.fit_transform(稀疏矩阵)

        # 转换为float32以节省内存并兼容PyTorch
        return 降维特征.astype(np.float32), 向量化器, svd

    # ======================================================================
    # Stage 3: Graph — 异构图构造（纯PyTorch）
    # ======================================================================

    def stage3_构图(self, 特征矩阵, records_a, records_b, 标注对, cfg):
        """
        第三阶段：基于语义特征和标注数据构建异构图。

        构建过程包括：
        1. 建立记录ID到索引的映射
        2. 将标注对划分为训练/验证/测试集
        3. 添加主匹配边（仅使用训练集的正例对）
        4. 根据配置添加辅助边（同区域、地理邻近、同物业公司）
        5. 将语义特征挂载到图的节点上

        Args:
            特征矩阵: 语义特征矩阵，shape=(n_a+n_b, dim)，来自stage2_语义向量化的输出
            records_a: 源表A的记录列表，每条记录须包含 "_record_id" 字段
            records_b: 源表B的记录列表，每条记录须包含 "_record_id" 字段
            标注对: 标注的匹配对列表，每个元素为 (record_id_a, record_id_b)
            cfg: 运行时配置字典，包含 split（数据划分）和 graph（图构建开关）等

        Returns:
            tuple: (图, 训练对, 验证对, 测试对)
                - 图: 构建好的 异构图 实例
                - 训练对: 训练集匹配对列表
                - 验证对: 验证集匹配对列表
                - 测试对: 测试集匹配对列表
        """
        数量A = len(records_a)
        数量B = len(records_b)

        # 建立记录ID到数组索引的映射，方便后续通过ID快速查找索引
        id到索引A = {r["_record_id"]: i for i, r in enumerate(records_a)}
        id到索引B = {r["_record_id"]: i for i, r in enumerate(records_b)}

        # 按比例将标注对划分为训练/验证/测试集
        划分配置 = cfg["split"]
        训练对, 验证对, 测试对 = self._划分数据集(
            标注对, id到索引A, id到索引B, 划分配置
        )

        # 创建异构图容器
        图 = 异构图(user节点数=数量A, item节点数=数量B)

        # 添加主匹配边（仅使用训练集的标注对，避免数据泄漏）
        匹配源 = [id到索引A[a] for a, b in 训练对 if a in id到索引A and b in id到索引B]
        匹配目标 = [id到索引B[b] for a, b in 训练对 if a in id到索引A and b in id到索引B]

        if 匹配源:
            # 添加正向边 user→item（rate）和反向边 item→user（rated_by）
            图.添加边("rate", torch.tensor(匹配源), torch.tensor(匹配目标))
            图.添加边("rated_by", torch.tensor(匹配目标), torch.tensor(匹配源))

        # 根据任务配置确定使用哪组边构建规则
        任务键 = "task_a" if self.task_cfg["source_a"]["table_name"] == "物业处" else "task_b"
        边配置 = self.图配置.get(任务键, {}).get("edges", {})

        # 添加"同区域"辅助边：同一行政区划下的记录互相连接
        if cfg["graph"].get("enable_same_district", True) and 边配置.get("same_district", {}).get("enabled", False):
            匹配字段列表 = 边配置["same_district"]["match_fields"]
            self._添加同字段边(图, records_a, records_b, 匹配字段列表, "same_district")

        # 添加"地理邻近"辅助边：地理距离小于阈值的记录互相连接
        if cfg["graph"].get("enable_geo_near", True) and 边配置.get("geo_near", {}).get("enabled", False):
            阈值 = 边配置["geo_near"].get("threshold_m", 500)
            self._添加地理邻近边(图, records_a, 阈值)

        # 添加"同物业公司"辅助边：归属同一物业公司的记录互相连接
        if cfg["graph"].get("enable_same_company", True) and 边配置.get("same_company", {}).get("enabled", False):
            匹配字段列表 = 边配置["same_company"]["match_fields"]
            self._添加同字段边(图, records_a, records_b, 匹配字段列表, "same_company")

        # 将语义特征向量挂载到图节点上
        # 特征矩阵[:数量A] 对应源表A的记录（user节点）
        图.节点特征["user"] = torch.tensor(特征矩阵[:数量A], dtype=torch.float32)
        # 特征矩阵[数量A:] 对应源表B的记录（item节点）
        图.节点特征["item"] = torch.tensor(特征矩阵[数量A:], dtype=torch.float32)

        return 图, 训练对, 验证对, 测试对

    def _划分数据集(self, 标注对, id到索引A, id到索引B, 划分配置):
        """
        将标注的匹配对按比例划分为训练集、验证集和测试集。

        仅保留两端ID都能在索引映射中找到的有效对，
        使用固定随机种子打乱顺序后按比例切分。

        Args:
            标注对: 全部标注匹配对列表，每个元素为 (id_a, id_b)
            id到索引A: 源表A的记录ID到索引的映射字典
            id到索引B: 源表B的记录ID到索引的映射字典
            划分配置: 划分配置字典，包含 train_ratio 和 val_ratio

        Returns:
            tuple: (训练对, 验证对, 测试对)
                - 训练对: 训练集匹配对列表
                - 验证对: 验证集匹配对列表
                - 测试对: 测试集匹配对列表（剩余部分）
        """
        # 过滤掉无效的匹配对（ID不在索引映射中的对）
        有效对 = [
            (a, b) for a, b in 标注对 if a in id到索引A and b in id到索引B
        ]
        # 使用固定随机种子生成随机排列索引，确保结果可重复
        随机生成器 = np.random.RandomState(self.system_cfg["seed"])
        随机索引 = 随机生成器.permutation(len(有效对))

        # 计算各集合的样本数量
        训练数量 = int(len(有效对) * 划分配置["train_ratio"])
        验证数量 = int(len(有效对) * 划分配置["val_ratio"])

        # 按随机排列索引切分为三部分
        训练对 = [有效对[随机索引[i]] for i in range(训练数量)]
        验证对 = [有效对[随机索引[i]] for i in range(训练数量, 训练数量 + 验证数量)]
        测试对 = [有效对[随机索引[i]] for i in range(训练数量 + 验证数量, len(随机索引))]

        return 训练对, 验证对, 测试对

    def _添加同字段边(self, 图, records_a, records_b, 匹配字段列表, 边名称):
        """
        添加基于相同字段值的辅助边。

        对同一源表内的记录，如果指定字段的值完全相同，则在它们之间添加无向边。
        分别为 user-user 和 item-item 两类同构边。

        为避免构建过大的全连接子图，限制每个分组最多50条记录。

        Args:
            图: 异构图 实例，边将被添加到此图中
            records_a: 源表A的记录列表
            records_b: 源表B的记录列表
            匹配字段列表: 用于匹配的统一字段名列表，如 ["区", "街道"]
            边名称: 边类型后缀名，如 "same_district"，最终边类型为 "user_same_district"
        """
        字段映射A = self.task_cfg["source_a"]["field_map"]
        字段映射B = self.task_cfg["source_b"]["field_map"]

        # ---- 构建 user-user 同字段边 ----
        user分组 = {}
        for i, r in enumerate(records_a):
            # 将匹配字段的值组合为元组作为分组键
            键 = tuple(
                str(r.get(字段映射A.get(f, ""), ""))
                for f in 匹配字段列表 if 字段映射A.get(f) is not None
            )
            # 过滤掉包含无效值的记录
            if all(k and k != "None" and k != "nan" for k in 键):
                user分组.setdefault(键, []).append(i)

        源u, 目标u = [], []
        for 分组 in user分组.values():
            # 仅对大小在2到50之间的分组构建全连接边，避免单点和超大组
            if 1 < len(分组) <= 50:
                for i in range(len(分组)):
                    for j in range(i + 1, len(分组)):
                        # 添加双向边（无向图用两条有向边表示）
                        源u.extend([分组[i], 分组[j]])
                        目标u.extend([分组[j], 分组[i]])

        if 源u:
            图.添加边(f"user_{边名称}", torch.tensor(源u), torch.tensor(目标u))

        # ---- 构建 item-item 同字段边 ----
        item分组 = {}
        for i, r in enumerate(records_b):
            # 将匹配字段的值组合为元组作为分组键
            键 = tuple(
                str(r.get(字段映射B.get(f, ""), ""))
                for f in 匹配字段列表 if 字段映射B.get(f) is not None
            )
            # 过滤掉包含无效值的记录
            if all(k and k != "None" and k != "nan" for k in 键):
                item分组.setdefault(键, []).append(i)

        源i, 目标i = [], []
        for 分组 in item分组.values():
            # 同样限制组大小在2到50之间
            if 1 < len(分组) <= 50:
                for i in range(len(分组)):
                    for j in range(i + 1, len(分组)):
                        # 添加双向边
                        源i.extend([分组[i], 分组[j]])
                        目标i.extend([分组[j], 分组[i]])

        if 源i:
            图.添加边(f"item_{边名称}", torch.tensor(源i), torch.tensor(目标i))

    def _添加地理邻近边(self, 图, records_a, 阈值米):
        """
        添加基于地理距离的辅助边。

        计算源表A中所有记录两两之间的 Haversine 地理距离，
        对距离小于阈值的记录对添加无向边。

        仅在源表A的 user 节点之间构建，因为地理坐标通常只有源表A有。

        Args:
            图: 异构图 实例，边将被添加到此图中
            records_a: 源表A的记录列表，需包含经度和纬度字段
            阈值米: 距离阈值，单位为米；距离小于此值的记录对将被连接
        """
        字段映射A = self.task_cfg["source_a"]["field_map"]
        # 获取经纬度对应的原始列名
        经度字段 = 字段映射A.get("经度")
        纬度字段 = 字段映射A.get("纬度")
        # 如果源表A没有经纬度字段映射，直接返回
        if not 经度字段 or not 纬度字段:
            return

        # 提取所有记录的经纬度坐标
        坐标列表 = []
        for r in records_a:
            try:
                经度 = float(r.get(经度字段, 0) or 0)
                纬度 = float(r.get(纬度字段, 0) or 0)
                坐标列表.append((经度, 纬度))
            except (ValueError, TypeError):
                # 无法解析坐标时，标记为无效坐标(0, 0)
                坐标列表.append((0, 0))

        # 过滤出有效坐标（排除(0,0)无效点）
        源, 目标 = [], []
        有效坐标 = [(i, c) for i, c in enumerate(坐标列表) if c != (0, 0)]
        # 两两比较有效坐标点之间的距离
        for idx_i in range(len(有效坐标)):
            for idx_j in range(idx_i + 1, len(有效坐标)):
                i, ci = 有效坐标[idx_i]
                j, cj = 有效坐标[idx_j]
                # 计算Haversine距离，若小于阈值则添加双向边
                if self._计算地面距离(ci, cj) < 阈值米:
                    源.extend([i, j])
                    目标.extend([j, i])

        if 源:
            图.添加边("user_geo_near", torch.tensor(源), torch.tensor(目标))

    @staticmethod
    def _计算地面距离(坐标1, 坐标2):
        """
        计算两个经纬度坐标之间的 Haversine（半正矢）地球表面距离。

        Haversine 公式用于计算球面上两点之间的大圆距离，
        适用于地球表面短距离计算（忽略椭球体修正）。

        公式：
            a = sin²(Δlat/2) + cos(lat1) * cos(lat2) * sin²(Δlng/2)
            distance = 2R * arcsin(√a)
        其中 R = 6371000米（地球平均半径）

        Args:
            坐标1: 第一个坐标点，格式为 (经度, 纬度)，单位为度
            坐标2: 第二个坐标点，格式为 (经度, 纬度)，单位为度

        Returns:
            float: 两点之间的地球表面距离，单位为米
        """
        # 将经纬度从角度转换为弧度
        经度1, 纬度1 = math.radians(坐标1[0]), math.radians(坐标1[1])
        经度2, 纬度2 = math.radians(坐标2[0]), math.radians(坐标2[1])
        # 计算经纬度差值
        经度差 = 经度2 - 经度1
        纬度差 = 纬度2 - 纬度1
        # Haversine 公式核心计算
        a = math.sin(纬度差 / 2) ** 2 + math.cos(纬度1) * math.cos(纬度2) * math.sin(经度差 / 2) ** 2
        # 返回距离，单位为米（地球半径取 6371000 米）
        return 6371000 * 2 * math.asin(math.sqrt(a))
