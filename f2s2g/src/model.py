"""
GNN模型 + 损失函数 + 分层负采样
LightGCN实现基于纯PyTorch稀疏矩阵，无DGL依赖

本模块实现了实体匹配任务中的核心模型组件：
1. 轻量图卷积网络 - 轻量级图卷积网络，通过多层邻域聚合学习用户和物品的嵌入表示
2. 对比损失 - 基于信息噪声对比估计的对比学习损失函数
3. 分层负采样器 - 分层负采样器，按地理层级（区县/街道）生成不同难度的负样本
4. 训练模型 - 端到端训练流程，包含早停机制和验证评估
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ======================================================================
# LightGCN 模型
# ======================================================================


class 轻量图卷积网络(nn.Module):
    """轻量图卷积网络 + 置信度加权消息传递（纯PyTorch）

    LightGCN是一种简化的图卷积网络，去除了特征变换和非线性激活，
    仅保留邻域聚合操作。其核心思想是：通过多层图卷积传播邻居信息，
    然后将各层的嵌入进行均匀融合，得到最终的节点表示。

    本实现支持多种边类型（用户-物品交互、用户-用户相似、物品-物品相似、
    知识节点补全等），并支持边权重（置信度）加权的消息传递。

    Attributes:
        user节点数: 用户节点总数
        item节点数: 物品节点总数（即数据源B的记录数）
        知识节点数: 知识节点总数（用于知识图谱补全边）
        层数: 图卷积层数，层数越多感受野越大
        嵌入维度: 嵌入维度
        user嵌入: 用户嵌入矩阵
        item嵌入: 物品嵌入矩阵
        知识嵌入: 知识节点嵌入矩阵（可选）
    """

    def __init__(self, user节点数, item节点数, 嵌入维度, 层数, 知识节点数=0):
        """初始化轻量图卷积网络模型。

        Args:
            user节点数: 用户节点数量（数据源A的记录数）
            item节点数: 物品节点数量（数据源B的记录数）
            嵌入维度: 嵌入向量维度，控制模型表达能力
            层数: 图卷积层数，决定信息传播的跳数（hop）
            知识节点数: 知识节点数量，默认为0表示不使用知识图谱
        """
        super().__init__()
        self.user节点数 = user节点数
        self.item节点数 = item节点数
        self.知识节点数 = 知识节点数
        self.层数 = 层数
        self.嵌入维度 = 嵌入维度

        # 创建用户和物品的可学习嵌入表
        self.user嵌入 = nn.Embedding(user节点数, 嵌入维度)
        self.item嵌入 = nn.Embedding(item节点数, 嵌入维度)
        # 如果有知识节点，则额外创建知识节点嵌入表
        self.知识嵌入 = nn.Embedding(知识节点数, 嵌入维度) if 知识节点数 > 0 else None

        # 使用Xavier均匀分布初始化所有嵌入权重
        self._初始化权重()

    def _初始化权重(self):
        """使用Xavier均匀初始化所有嵌入权重。

        Xavier初始化能使各层的输出方差保持一致，
        避免训练初期梯度消失或爆炸的问题。
        """
        nn.init.xavier_uniform_(self.user嵌入.weight)
        nn.init.xavier_uniform_(self.item嵌入.weight)
        if self.知识嵌入 is not None:
            nn.init.xavier_uniform_(self.知识嵌入.weight)

    def 从特征初始化(self, graph):
        """用F2S2G特征工程输出的预计算特征来初始化嵌入表。

        F2S2G（Feature to Structured to Graph）是上游的特征抽取模块，
        它会为每个节点生成初始特征向量。用这些特征初始化嵌入表，
        可以给模型一个更好的起点，加快收敛速度。

        Args:
            graph: 包含节点特征字典的图对象，
                   节点特征["user"]为用户特征矩阵，
                   节点特征["item"]为物品特征矩阵，
                   节点特征["knowledge"]为知识节点特征矩阵
        """
        with torch.no_grad():
            # 如果图中包含用户预计算特征，则用其覆盖随机初始化的嵌入
            if "user" in graph.节点特征:
                self.user嵌入.weight.copy_(graph.节点特征["user"])
            # 如果图中包含物品预计算特征，则用其覆盖随机初始化的嵌入
            if "item" in graph.节点特征:
                self.item嵌入.weight.copy_(graph.节点特征["item"])
            # 如果存在知识节点嵌入且图中有对应特征，同样进行初始化
            if self.知识嵌入 is not None and "knowledge" in graph.节点特征:
                self.知识嵌入.weight.copy_(graph.节点特征["knowledge"])

    def forward(self, graph):
        """前向传播：执行多层图卷积聚合并进行层间均匀融合。

        LightGCN的核心流程：
        1. 取出第0层（原始）嵌入
        2. 逐层执行消息传递，得到每一层的嵌入
        3. 将所有层（包括第0层）的嵌入取平均，作为最终表示

        这种层间融合策略能有效缓解过度平滑问题，同时利用不同层次的信息。

        Args:
            graph: 包含边信息和边权重的图对象

        Returns:
            最终user表示: 融合后的用户嵌入矩阵，形状为 [user节点数, 嵌入维度]
            最终item表示: 融合后的物品嵌入矩阵，形状为 [item节点数, 嵌入维度]
        """
        # 获取第0层（初始）嵌入
        user表示 = self.user嵌入.weight
        item表示 = self.item嵌入.weight

        # 存储各层嵌入的列表，第0层为原始嵌入
        所有user层 = [user表示]
        所有item层 = [item表示]

        # 当前层的嵌入，用于下一层的输入
        当前user = user表示
        当前item = item表示

        # 逐层执行图卷积消息传递
        for _ in range(self.层数):
            新user表示, 新item表示 = self._消息传递(graph, 当前user, 当前item)
            所有user层.append(新user表示)
            所有item层.append(新item表示)
            当前user = 新user表示
            当前item = 新item表示

        # 将所有层的嵌入沿第0维堆叠后取平均，实现均匀层融合
        最终user表示 = torch.stack(所有user层, dim=0).mean(dim=0)
        最终item表示 = torch.stack(所有item层, dim=0).mean(dim=0)

        return 最终user表示, 最终item表示

    def _消息传递(self, graph, user表示, item表示):
        """执行单层消息传递（图卷积）。

        根据图中不同类型的边，将邻居节点的嵌入聚合到目标节点上。
        支持的边类型包括：
        - "rate": 用户评价物品（用户从物品接收消息）
        - "rated_by": 物品被用户评价（物品从用户接收消息）
        - "user_*": 用户之间的相似关系
        - "item_*": 物品之间的相似关系
        - "completed_by": 知识节点补全物品信息

        聚合后会使用度数的平方根进行归一化（类似GCN的对称归一化）。

        Args:
            graph: 包含边集和边权重的图对象
            user表示: 当前层的用户嵌入，形状 [user节点数, 嵌入维度]
            item表示: 当前层的物品嵌入，形状 [item节点数, 嵌入维度]

        Returns:
            新user表示: 聚合并归一化后的用户嵌入
            新item表示: 聚合并归一化后的物品嵌入
        """
        # 初始化聚合结果为零向量
        新user表示 = torch.zeros_like(user表示)
        新item表示 = torch.zeros_like(item表示)
        # 初始化节点度数计数器，用于后续归一化
        user度数 = torch.zeros(self.user节点数, device=user表示.device)
        item度数 = torch.zeros(self.item节点数, device=item表示.device)

        # 遍历图中所有边类型，根据类型执行不同的消息传递
        for 边类型, (源节点, 目标节点) in graph.边集.items():
            # 跳过没有边的类型
            if len(源节点) == 0:
                continue
            # 获取该边类型对应的权重（置信度），可能为None
            权重 = graph.边权重.get(边类型)

            if 边类型 == "rate":
                # "rate"边：用户->物品方向，用户节点从其评价过的物品接收消息
                # 源节点是用户索引，目标节点是物品索引
                消息 = item表示[目标节点] if 权重 is None else item表示[目标节点] * 权重.unsqueeze(1)
                新user表示.index_add_(0, 源节点, 消息)
                # 累加度数，用于归一化
                度数增量 = torch.ones(len(源节点), device=user表示.device) if 权重 is None else 权重
                user度数.index_add_(0, 源节点, 度数增量)

            elif 边类型 == "rated_by":
                # "rated_by"边：物品->用户方向，物品节点从评价它的用户接收消息
                # 源节点是物品索引，目标节点是用户索引
                消息 = user表示[目标节点] if 权重 is None else user表示[目标节点] * 权重.unsqueeze(1)
                新item表示.index_add_(0, 源节点, 消息)
                度数增量 = torch.ones(len(源节点), device=item表示.device) if 权重 is None else 权重
                item度数.index_add_(0, 源节点, 度数增量)

            elif 边类型.startswith("user_"):
                # 用户间相似边：用户节点从相似的其他用户接收消息
                # 例如 "user_sim" 表示用户相似关系
                消息 = user表示[目标节点] if 权重 is None else user表示[目标节点] * 权重.unsqueeze(1)
                新user表示.index_add_(0, 源节点, 消息)
                度数增量 = torch.ones(len(源节点), device=user表示.device) if 权重 is None else 权重
                user度数.index_add_(0, 源节点, 度数增量)

            elif 边类型.startswith("item_"):
                # 物品间相似边：物品节点从相似的其他物品接收消息
                # 例如 "item_sim" 表示物品相似关系
                消息 = item表示[目标节点] if 权重 is None else item表示[目标节点] * 权重.unsqueeze(1)
                新item表示.index_add_(0, 源节点, 消息)
                度数增量 = torch.ones(len(源节点), device=item表示.device) if 权重 is None else 权重
                item度数.index_add_(0, 源节点, 度数增量)

            elif 边类型 == "completed_by" and self.知识嵌入 is not None:
                # 知识补全边：物品节点从关联的知识节点接收消息（带置信度加权）
                # 这允许外部知识（如地址解析结果）补充物品的表示
                知识表示 = self.知识嵌入.weight[目标节点]
                消息 = 知识表示 if 权重 is None else 知识表示 * 权重.unsqueeze(1)
                新item表示.index_add_(0, 源节点, 消息)
                度数增量 = torch.ones(len(源节点), device=item表示.device) if 权重 is None else 权重
                item度数.index_add_(0, 源节点, 度数增量)

        # 使用度数平方根进行归一化，防止高度数节点的嵌入尺度过大
        # clamp(min=1)防止除零，sqrt对应GCN中的D^{-1/2}归一化
        新user表示 = 新user表示 / user度数.clamp(min=1).sqrt().unsqueeze(1)
        新item表示 = 新item表示 / item度数.clamp(min=1).sqrt().unsqueeze(1)

        return 新user表示, 新item表示


# ======================================================================
# 损失函数
# ======================================================================


class 对比损失(nn.Module):
    """InfoNCE对比损失 + Class-Balanced权重。

    InfoNCE（Information Noise Contrastive Estimation）损失函数，
    用于对比学习。其核心思想是：将正样本对的得分拉近，
    同时将负样本对的得分推远。

    此外，引入了Class-Balanced权重机制，根据节点在训练数据中的出现频率
    调整损失权重，使低频节点获得更高的权重，缓解类别不平衡问题。

    公式：L = -log(exp(sim(u,v+)/τ) / Σ exp(sim(u,vi)/τ))
    其中τ为温度参数，控制分布的锐度。

    Attributes:
        温度: 温度参数τ，值越小分布越尖锐，模型越关注困难样本
        beta: Class-Balanced权重的超参数，控制重加权的强度
    """

    def __init__(self, temperature=0.1, beta=0.9999):
        """初始化对比损失函数。

        Args:
            temperature: 温度参数，默认0.1。较小的温度使模型更关注困难负样本
            beta: Class-Balanced权重的β参数，默认0.9999。
                  越接近1，权重差异越大（越倾向于补偿低频样本）
        """
        super().__init__()
        self.温度 = temperature
        self.beta = beta

    def forward(self, user表示, 正样本item表示, 负样本item表示, 节点频率=None):
        """计算InfoNCE对比损失。

        将正样本和负样本的相似度得分组合成分类问题，
        正样本标签为0（即第一个位置），使用交叉熵计算损失。

        Args:
            user表示: 用户（锚点）嵌入，形状 [batch_size, 嵌入维度]
            正样本item表示: 正样本物品嵌入，形状 [batch_size, 嵌入维度]
            负样本item表示: 负样本物品嵌入，形状 [batch_size, num_neg, 嵌入维度]
            节点频率: 节点频率张量，形状 [batch_size]，用于计算Class-Balanced权重。
                       为None时不进行重加权

        Returns:
            损失值: 标量损失值（已取batch平均）
        """
        # 计算正样本得分：用户嵌入与正样本物品嵌入的点积，除以温度
        正样本得分 = (user表示 * 正样本item表示).sum(dim=-1) / self.温度
        # 计算负样本得分：用户嵌入与每个负样本物品嵌入的点积，除以温度
        # bmm: batch矩阵乘法，[B, num_neg, D] x [B, D, 1] -> [B, num_neg, 1]
        负样本得分 = torch.bmm(
            负样本item表示, user表示.unsqueeze(2)
        ).squeeze(2) / self.温度

        # 拼接正负样本得分，正样本在第0位
        logits = torch.cat([正样本得分.unsqueeze(1), 负样本得分], dim=1)
        # 标签全为0，因为正样本始终在第一个位置
        标签 = torch.zeros(logits.shape[0], dtype=torch.long, device=logits.device)
        # 计算交叉熵损失（不做reduce，保留每个样本的损失）
        损失 = F.cross_entropy(logits, 标签, reduction="none")

        # 如果提供了节点频率，则应用Class-Balanced权重
        if 节点频率 is not None:
            # Class-Balanced权重公式：w = (1-β) / (1-β^n)
            # n为节点出现频率，频率越高权重越低
            权重 = (1 - self.beta) / (1 - self.beta ** 节点频率.float().clamp(min=1))
            损失 = 损失 * 权重

        return 损失.mean()


# ======================================================================
# 分层负采样
# ======================================================================


class 分层负采样器:
    """分层负采样器，基于地理行政区划生成不同难度级别的负样本。

    在实体匹配任务中，负样本的质量直接影响模型的判别能力。
    本采样器根据地理层级将负样本分为三个难度级别：
    - 简单负样本（Easy）：与正样本不在同一区县的记录，差异明显
    - 中等负样本（Medium）：与正样本同区县但不同街道的记录，有一定相似性
    - 困难负样本（Hard）：与正样本同街道的记录，非常相似但不是同一实体

    这种分层策略使模型能同时学习粗粒度和细粒度的区分能力。

    Attributes:
        B总数: 数据源B的记录总数
        负样本比例: 每个正样本对应的负样本数量
        简单比例: 简单负样本占比
        中等比例: 中等负样本占比
        困难比例: 困难负样本占比
        区县分组: 按区县分组的记录索引字典 {区县名: [索引列表]}
        街道分组: 按街道分组的记录索引字典 {区县_街道: [索引列表]}
    """

    def __init__(self, records_b, cfg):
        """初始化分层负采样器。

        解析数据源B中每条记录的区县和街道信息，
        构建地理分组索引，供后续采样使用。

        Args:
            records_b: 数据源B的记录列表，每条记录为字典
            cfg: 配置字典，包含training.neg_ratio和training.neg_strategy
        """
        self.B总数 = len(records_b)
        self.负样本比例 = cfg["training"]["neg_ratio"]

        # 从配置中读取各难度级别的占比
        策略 = cfg["training"]["neg_strategy"]
        self.简单比例 = 策略["easy_ratio"]
        self.中等比例 = 策略["medium_ratio"]
        self.困难比例 = 策略["hard_ratio"]

        # 构建按区县和街道分组的索引
        self.区县分组 = {}
        self.街道分组 = {}

        # 遍历所有记录，提取区县和街道字段并建立分组索引
        for i, r in enumerate(records_b):
            # 尝试多个可能的字段名来获取区县信息
            区县 = self._获取字段(r, ("区县", "fwssqx", "征收处_房屋所属区县"))
            # 尝试多个可能的字段名来获取街道信息
            街道 = self._获取字段(r, ("街道", "fwssjd", "征收处_房屋所属街道"))
            # 将记录索引加入对应的区县分组
            if 区县:
                self.区县分组.setdefault(区县, []).append(i)
            # 将记录索引加入对应的街道分组（键为"区县_街道"以避免不同区县同名街道冲突）
            if 街道:
                键 = f"{区县}_{街道}"
                self.街道分组.setdefault(键, []).append(i)

    @staticmethod
    def _获取字段(记录, 候选字段名):
        """从记录中尝试多个候选字段名，返回第一个有效值。

        由于不同数据源可能使用不同的字段命名规范，
        需要尝试多个候选名称来获取同一语义的字段值。

        Args:
            记录: 单条记录字典
            候选字段名: 候选字段名元组，按优先级排列

        Returns:
            第一个非空且非NaN的字段值字符串，若全部无效则返回空字符串
        """
        for c in 候选字段名:
            值 = str(记录.get(c, ""))
            # 过滤掉空值、NaN和None字符串
            if 值 and 值 != "nan" and 值 != "None":
                return 值
        return ""

    def 采样(self, 正样本item索引, rng):
        """为给定的正样本生成分层负样本索引列表。

        按照配置的比例，从三个难度级别分别采样负样本：
        1. 简单负样本：从不同区县的记录中随机采样
        2. 中等负样本：从同区县不同街道的记录中随机采样
        3. 困难负样本：从同街道的记录中随机采样

        如果某个难度级别的候选池不足，则从全局随机采样补足。

        Args:
            正样本item索引: 正样本在数据源B中的索引
            rng: numpy随机数生成器（RandomState），确保可复现性

        Returns:
            长度为负样本比例的负样本索引列表
        """
        # 计算各难度级别需要的负样本数量
        负样本总数 = self.负样本比例
        简单数量 = max(1, int(负样本总数 * self.简单比例))
        中等数量 = max(1, int(负样本总数 * self.中等比例))
        困难数量 = 负样本总数 - 简单数量 - 中等数量

        负样本索引 = []
        正样本所属区县 = None
        正样本所属街道键 = None

        # 找到正样本所在的区县
        for d, 索引列表 in self.区县分组.items():
            if 正样本item索引 in 索引列表:
                正样本所属区县 = d
                break
        # 找到正样本所在的街道
        for sk, 索引列表 in self.街道分组.items():
            if 正样本item索引 in 索引列表:
                正样本所属街道键 = sk
                break

        # === 简单负样本：从不同区县的记录中采样（地理距离远，差异大）===
        其他区县记录 = [idx for d, 索引列表 in self.区县分组.items()
                 if d != 正样本所属区县 for idx in 索引列表]
        if 其他区县记录:
            负样本索引.extend(rng.choice(其他区县记录, size=min(简单数量, len(其他区县记录)), replace=False).tolist())

        # === 中等负样本：从同区县但不同街道的记录中采样（有一定相似性）===
        同区县记录 = self.区县分组.get(正样本所属区县, [])
        同街道集合 = set(self.街道分组.get(正样本所属街道键, [])) if 正样本所属街道键 else set()
        中等候选池 = [i for i in 同区县记录 if i not in 同街道集合 and i != 正样本item索引]
        if 中等候选池:
            负样本索引.extend(rng.choice(中等候选池, size=min(中等数量, len(中等候选池)), replace=False).tolist())

        # === 困难负样本：从同街道的记录中采样（非常相似，需要精细区分）===
        困难候选池 = [i for i in 同街道集合 if i != 正样本item索引]
        if 困难候选池 and 困难数量 > 0:
            负样本索引.extend(rng.choice(list(困难候选池), size=min(困难数量, len(困难候选池)), replace=False).tolist())

        # 如果上述采样不足负样本总数个，则从全局随机采样补足
        while len(负样本索引) < 负样本总数:
            idx = rng.randint(0, self.B总数)
            if idx != 正样本item索引:
                负样本索引.append(idx)

        # 截取前负样本总数个，确保数量精确
        return 负样本索引[:负样本总数]


# ======================================================================
# 训练
# ======================================================================


def 获取设备(cfg):
    """根据配置确定计算设备（CPU或GPU）。

    如果配置为"auto"，则自动检测CUDA是否可用，
    优先使用GPU加速计算。

    Args:
        cfg: 配置字典，从中读取"device"字段

    Returns:
        torch.device对象，可能是"cuda"或"cpu"
    """
    设备字符串 = cfg.get("device", "auto")
    if 设备字符串 == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(设备字符串)


def 训练模型(graph, 训练对, 验证对, records_a, records_b, features, cfg):
    """端到端训练轻量图卷积网络模型的主函数。

    训练流程：
    1. 初始化模型和优化器
    2. 构建训练对索引映射和节点频率统计
    3. 按epoch迭代训练：
       - 随机打乱训练数据
       - 分batch进行前向传播、损失计算和反向传播
       - 每5个epoch在验证集上评估
    4. 使用早停机制防止过拟合
    5. 加载最优模型参数并返回最终嵌入

    Args:
        graph: 构建好的异构图对象，包含节点特征和边信息
        训练对: 训练集匹配对列表 [(record_id_a, record_id_b), ...]
        验证对: 验证集匹配对列表，格式同上
        records_a: 数据源A的记录列表
        records_b: 数据源B的记录列表
        features: 特征字典（由F2S2G模块生成），本函数中未直接使用
        cfg: 完整配置字典

    Returns:
        模型: 训练好的轻量图卷积网络模型
        (user表示, item表示): 最终的用户和物品嵌入矩阵元组
    """
    # 确定计算设备
    设备 = 获取设备(cfg)
    模型配置 = cfg["model"]
    训练配置 = cfg["training"]

    # 获取知识节点数量
    知识数 = graph.知识节点数

    # 创建轻量图卷积网络模型实例并移至目标设备
    模型 = 轻量图卷积网络(
        user节点数=graph.user节点数,
        item节点数=graph.item节点数,
        嵌入维度=模型配置["embedding_dim"],
        层数=模型配置["num_layers"],
        知识节点数=知识数,
    ).to(设备)

    # 用F2S2G预计算特征初始化模型嵌入
    模型.从特征初始化(graph.to(设备))
    # 将图数据移至目标设备
    graph = graph.to(设备)

    # 构建record_id到数组索引的映射字典
    id转索引_a = {r["_record_id"]: i for i, r in enumerate(records_a)}
    id转索引_b = {r["_record_id"]: i for i, r in enumerate(records_b)}

    # 将训练对和验证对从record_id转换为数组索引
    训练索引对 = [(id转索引_a[a], id转索引_b[b]) for a, b in 训练对 if a in id转索引_a and b in id转索引_b]
    验证索引对 = [(id转索引_a[a], id转索引_b[b]) for a, b in 验证对 if a in id转索引_a and b in id转索引_b]

    # 统计每个用户节点在训练集中出现的频率（用于Class-Balanced权重）
    节点频率 = {}
    for a索引, _ in 训练索引对:
        节点频率[a索引] = 节点频率.get(a索引, 0) + 1

    # 初始化分层负采样器
    采样器 = 分层负采样器(records_b, cfg)
    # 使用固定种子的随机数生成器，确保实验可复现
    rng = np.random.RandomState(cfg["seed"])

    # 初始化损失函数
    损失配置 = 训练配置["loss"]
    损失函数 = 对比损失(temperature=损失配置["temperature"], beta=损失配置["class_balance_beta"]).to(设备)
    # 使用Adam优化器，支持L2正则化（weight_decay）
    优化器 = torch.optim.Adam(模型.parameters(), lr=训练配置["learning_rate"], weight_decay=训练配置.get("weight_decay", 0))

    # 早停相关变量
    最佳验证F1 = 0          # 最佳验证集指标
    耐心计数器 = 0     # 连续未改善的次数
    最佳状态 = None        # 最佳模型参数副本
    批次大小 = 训练配置["batch_size"]

    # ====== 训练主循环 ======
    for epoch in range(训练配置["epochs"]):
        模型.train()
        轮次损失 = 0.0
        # 随机打乱训练样本顺序
        打乱索引 = rng.permutation(len(训练索引对))

        # 按batch迭代训练
        for start in range(0, len(打乱索引), 批次大小):
            # 获取当前batch的索引
            批次索引 = 打乱索引[start:start + 批次大小]
            批次对 = [训练索引对[i] for i in 批次索引]

            # 构建当前batch的用户和正样本物品索引张量
            user索引张量 = torch.tensor([p[0] for p in 批次对], device=设备)
            正样本item索引张量 = torch.tensor([p[1] for p in 批次对], device=设备)

            # 为每个正样本生成分层负样本
            负样本索引 = [采样器.采样(b索引, rng) for _, b索引 in 批次对]
            负样本索引 = torch.tensor(负样本索引, device=设备)

            # 前向传播：通过轻量图卷积网络获取所有节点的最终嵌入
            user表示, item表示 = 模型(graph)

            # 根据索引取出当前batch对应的嵌入向量
            批次user = user表示[user索引张量]
            批次正样本 = item表示[正样本item索引张量]
            批次负样本 = item表示[负样本索引]

            # 获取当前batch中用户节点的频率，用于Class-Balanced加权
            频率 = torch.tensor([节点频率.get(p[0], 1) for p in 批次对], dtype=torch.float32, device=设备)

            # 计算InfoNCE损失
            损失 = 损失函数(批次user, 批次正样本, 批次负样本, 频率)
            # 梯度清零、反向传播、参数更新
            优化器.zero_grad()
            损失.backward()
            优化器.step()
            轮次损失 += 损失.item()

        # 计算当前epoch的平均损失
        批次总数 = max(1, len(打乱索引) // 批次大小)
        平均损失 = 轮次损失 / 批次总数

        # ====== 每5个epoch进行一次验证评估 ======
        if (epoch + 1) % 5 == 0:
            模型.eval()
            with torch.no_grad():
                user表示, item表示 = 模型(graph)
            # 使用快速评估函数计算验证集上的Hit@10指标
            验证F1 = _快速评估(user表示, item表示, 验证索引对)
            print(f"  Epoch {epoch+1:3d} | Loss: {平均损失:.4f} | Val Hit@50: {验证F1:.4f}")

            # 早停判断：如果验证指标有提升，保存模型；否则增加耐心计数
            if 验证F1 > 最佳验证F1:
                最佳验证F1 = 验证F1
                耐心计数器 = 0
                # 深拷贝当前最优模型参数
                最佳状态 = {k: v.clone() for k, v in 模型.state_dict().items()}
            else:
                耐心计数器 += 1
                # 超过耐心阈值则触发早停
                if 耐心计数器 >= 训练配置["patience"]:
                    print(f"  早停于 Epoch {epoch+1}")
                    break

    # 加载训练过程中的最优模型参数
    if 最佳状态 is not None:
        模型.load_state_dict(最佳状态)

    # 使用最优模型生成最终嵌入
    模型.eval()
    with torch.no_grad():
        user表示, item表示 = 模型(graph)

    return 模型, (user表示, item表示)


def _快速评估(user表示, item表示, 验证对):
    """快速评估验证集上的Hit@50指标。

    使用较大的K值（50）作为验证指标，因为在3260个item中搜Top-10
    本身就是极具挑战性的任务（随机基线仅0.3%）。
    使用Top-50能更早检测到模型是否在朝正确方向学习。

    Args:
        user表示: 用户嵌入矩阵，形状 [user节点数, 嵌入维度]
        item表示: 物品嵌入矩阵，形状 [item节点数, 嵌入维度]
        验证对: 验证集匹配对索引列表 [(user_idx, item_idx), ...]

    Returns:
        Hit@50指标值（0到1之间的浮点数）
    """
    if not 验证对:
        return 0.0
    命中数 = 0
    样本 = 验证对[:min(200, len(验证对))]
    for a索引, b索引 in 样本:
        得分 = torch.matmul(user表示[a索引], item表示.T)
        前k个 = 得分.topk(50).indices.cpu().numpy()
        if b索引 in 前k个:
            命中数 += 1
    return 命中数 / len(样本)
