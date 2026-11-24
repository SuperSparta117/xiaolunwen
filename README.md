# 主实验计划：跨源物理地点实体解析与拒识

## 1 研究目标

### 1.1 核心问题

给定来自两个业务系统的两条记录，判断它们是否描述同一个现实中的物理地点，并找出对应关系；如果候选侧不存在这个地点，则输出空集合并拒识。

这不是“两个字段是否相等”的表连接问题，而是**跨源物理地点实体解析**（cross-source physical-place entity resolution）：同一地点在不同系统中可能有不同的名称、地址格式、行政区划写法、字段缺失和结构表达。

**实体粒度约定：**一期、二期和不同组团默认是不同的物理地点实体；不带期次的整体名称（例如“龙湖花园”）表示覆盖其各期的项目级名称或名称族，可以对应多个期次候选。整体名称与期次之间记录为项目包含关系，不等同于期次级 exact match；同名本身不能证明期次、组团或地址级实体相同。

模型的输入由任务配置决定，可以包括两张异构表、字段映射、已有索引或关系信息，以及允许使用的外源地理资产。每种信息的可用范围、使用阶段和是否属于模型输入，必须在新系统的配置与论文中显式记录。

### 1.2 统一输出

对每条查询记录 `q`，候选侧记录集合记为 `B`。系统输出：

- 每个候选对 `(q,b)` 的匹配分数 `p(q,b)`；
- 查询记录对应的候选集合 `S(q)`；
- 拒识结果：`S(q)=∅`。

不预设 1:1。一个查询可以对应多个候选；一个候选也可能与多个查询有关。输出集合必须由验证集确定的阈值和集合规则产生，测试集不得参与调阈值。

### 1.3 系统分为三个阶段

1. **候选召回**：从候选表中召回可能对应的记录，保证真实候选尽可能进入候选池；
2. **成对匹配**：对每个 `(q,b)` 融合名称、地址、空间、行政区划和结构字段证据，输出匹配分数；
3. **集合预测与拒识**：根据验证集冻结的阈值和集合规则输出 `S(q)`；没有可靠候选时输出空集合。

三个阶段分别评估。候选没有被召回属于候选生成失败，不能混同为排序模型失败。

### 1.4 论文主张边界

论文主张限定为：在给定候选库、字段映射和外源地理资产的条件下，建立一个能够融合多源证据、处理字段缺失和冲突、对新记录进行推理，并在候选侧不存在对应地点时拒识的跨源物理地点实体解析方法。

本文不声称解决任意城市、任意业务表的通用地点解析；所有结论限定在数据字段、空间范围、候选库和外源资产条件内。

## 2 已核实的数据事实

> 以下事实来自当前数据核查，是实验设计依据。数字发生变化时，必须先更新数据版本和本计划中的核算表。

| 项目 | 事实 | 实验影响 |
|---|---|---|
| 规模 | A：物业处 8,782 / 房交处 3,260；B：征收处 28,101 / 奥格 28,101 | A、B 是同级评测任务；候选侧规模是主要计算约束 |
| A 金标准 | 3,026 个 pair，覆盖 2,883 个 query；其中 2,709 个原始标注 pair、317 个外源补全 pair | pair 和 query 必须分开计数；按 provenance 分层报告 |
| A 名称一致率 | 3,014 / 3,026 = 99.6%（pair 级） | 自然正例存在名称捷径，必须加入同名异地和名称遮蔽切片 |
| A 名称变体 | 15 条（0.5%） | 自然数据中的异名样本不足，不能单凭自然集声称异名解析能力 |
| A 已复核错误 | 878 条可疑对逐条复核，已知标注错误 0 条 | 主要风险是金标准不完整和证据来源混合，不是已知错标 |
| 坐标系 | 房交原始面坐标为 CGCS2000/WGS84；POI 坐标为 GCJ-02 | 距离计算前必须完成坐标转换并记录版本 |
| B 字段同值率 | 主要同行字段高度同值；地址同行相等率 100%，房屋用途为 97.3021%；`id`、奥格编号和地址均存在重复 | B 与 A 同级评测但单独报告；不得使用行号、编号或同行关系作为实体键 |
| A mapping 覆盖 | 物业处 8,782 条 query 中，2,883 条出现在当前 mapping，5,899 条未被 mapping 覆盖 | 未覆盖不等于空集；未核验样本保持 `unknown`，不得直接作为拒识负例 |


## 3 方法方案

本项目最终采用“统一记录视图 -> 多路候选池 -> 成对特征 -> 成对模型 -> 验证集阈值 -> 集合输出”的六步流程。实现过程中对原计划作了两项重要工程化调整：完整候选库评分改为逐 query、逐候选分批计算并持久化到 `.audit_work/full_candidate_cache`，避免将 432 × 3,260 的预测字典同时留在内存；名称遮蔽实验同时保留 `fixed_pool` 诊断协议，并将名称遮蔽后的候选召回作为单独的 `end_to_end` 协议，避免混淆“排序退化”和“候选生成退化”。

```text
① 异构输入 + 字段映射
              |
              v
② 标准化统一记录视图 + POI 可信判定
              |
       +------+------+
       |             |
       v             v
③ 多路候选召回    ④ 成对特征和分层负例
       |             |
       +------+------+
              v
⑤ 规则 / 逻辑回归 / LightGBM 成对评分
              |
              v
⑥ validation 阈值 -> 完整候选集合 -> 拒识诊断
```

### 3.1 ① 输入、映射和统一记录视图

任务 A 的 query 是物业处 SQL 中的 `village_id`、小区名称、区县、街道等字段；候选是房屋交易 CSV 中的 `愉悦安`、小区名、区县、街道等字段。`code/er/config.py` 固定原始文件路径和任务配置，`code/er/io.py` 用真实 INSERT 列名解析 SQL，并将两侧记录标准化为统一视图：

```python
{
    "id": "源内稳定记录 ID",
    "name": "规范化前后可追踪的小区名称",
    "area": "规范化区县",
    "street": "规范化街道",
    "address": "可用时的规范化地址",
    "type": "物业类型",
    "lng": "经度（若可用）",
    "lat": "纬度（若可用）",
    "coords_trust": "坐标可信布尔值",
    "poi_district": "POI 解析区县",
}
```

A SQL 源本身没有独立的地址列，因此查询侧地址证据不能被解释为完整双侧地址匹配。原始 ID 只用于追踪和 mapping，不进入模型特征。

### 3.2 ② POI 连接、坐标可信判定和 provenance

POI 资产按 `(来源, 记录ID)` 连接两侧记录。POI 原始坐标为 GCJ-02，源数据坐标按资产规则保留并记录；`code/er/geo_asset.py` 复用冻结资产中的“可信/不可信原因”，并按侧使用不同判据：物业处看坐标是否在重庆范围、解析 level 是否可信、解析区县是否与业务区县一致；房交坐标来自面坐标质心、没有 level，改看面坐标包围盒对角线是否 < 1000m 且逆地理编码区县是否与登记区县一致。当前资产有 12,042 条记录，其中 9,451 条可信（物业处 6,329 + 房交 3,122），可信标记和不可信原因写入地理 manifest。

只有 query 和 candidate 两侧坐标均可信时，才计算 Haversine 距离、距离分档和 `poi_district_match`；不可信坐标保留原因，不填为 `(0,0)`，不生成空间证据。mapping 中的原始标注和外源补全在 gold manifest 中分为 `original_annotation` 与 `external_derived`，未覆盖 query 保持 `unknown`，不能自动当作空集。

### 3.3 ③ 多路候选召回与两个遮蔽协议

自然候选池由名称字符 n-gram、地址字符 n-gram、区县和其他结构通道取并集生成；可信 POI 还通过 2 km 网格及相邻 8 个网格召回。`code/build_candidates.py` 输出候选池、通道来源、候选版本、`candidate_recall_at_k.csv` 和通道增量覆盖率。

名称捷径诊断发现自然名称 n-gram Recall@10 约为 99.83%，因此加入实体级固定 seed=42 的 `rho in {0, 0.3, 0.6, 1.0}` 遮蔽：

- `fixed_pool`：候选池冻结，遮蔽只作用于成对特征和排序；用于隔离排序模型对名称的依赖；
- `end_to_end`：同步清除名称、规范化名称、期次/组团派生文本和名称召回索引，再生成候选池；用于完整系统鲁棒性。

四档完整候选库结果采用前者，因此其候选召回率恒为完整库条件下的 100%，不能当作 `end_to_end` 召回结论。

### 3.4 ④ 成对特征和分层负例

当前成对特征包括 `name_exact`、`name_similarity`、`address_similarity`、`area_match`、`street_match`、坐标可用/可信、POI 距离及距离分档、POI 区县一致、类型一致等。名称遮蔽作用于 query 或 candidate 任一实体时，名称相关特征置零；地址、行政和 POI 特征按协议保留。

`code/build_pair_features.py` 先按 gold 二部图 connected component 生成实体簇 split，再生成正例和同 split 的困难负例，避免按 pair 随机切分导致实体泄漏。负例包含同区县、同街道、空间近邻和结构相似的候选。最终使用 `code/training_assets_full_v4`，训练/validation/test pair 资产分别为 8,454 / 1,788 / 1,835 条，其中 `street_match`、`poi_district_match` 为行政区划补全后的真实值；完整候选库评估不把有限负例表当作最终候选集合。

### 3.5 ⑤ 成对模型

`code/run_pair_model_experiments.py` 比较主字段精确匹配、TF-IDF-like Cosine、逻辑回归、LightGBM Text/Structure、LightGBM + POI 和消融模型。LightGBM 使用原生 API，不把记录 ID、行号或同行关系作为输入。

完整候选库使用 `code/run_full_library_experiment.py`：每个 query 遍历全部 3,260 个候选，每 256 个候选构造一次特征矩阵并将 score CSV 立即写入磁盘 cache。每个 `rho × method × split` 有独立完成标记和 SHA-256；重启时复用完成 split。这样内存只保留当前 query 的候选对象和一个小批量特征矩阵，而不是保留全体 query-candidate Python 字典。

### 3.6 ⑥ validation 阈值和集合输出

每个方法只用 433 个 validation 正例 query 的完整候选分数选择阈值，再冻结阈值到 432 个 test 正例 query。输出定义为：

```text
S(q; tau) = { b in B | p(q,b) >= tau }
```

对每个 test query 保存 `gold_candidate_ids`、`predicted_candidate_ids`、预测数量和 gold 数量；统计 pair-level TP/FP/FN/TN、precision/recall/F1、query-macro 集合指标、any-hit 和正例误拒率。5,899 个未映射 query 保持 `unknown`，不进入这些确认正例分母；非 mapping candidate 作为负例的解释依赖 mapping 完整性假设。当前尚未形成独立 `confirmed_empty` 集，因此不宣称严格业务拒识率。

### 3.7 按命令展开的真实数据流示例

本节严格按实际执行命令展开，分为两个阶段：命令一至三是测试阶段（回归测试、小样本流程冒烟、小样本金标准资产生成），不会构成正式实验结果；命令四至六是使用全量数据准备正式实验资产；命令七才运行完整候选库四档遮蔽模型评估并生成正式结果。为追踪端到端数据流，使用一个真实测试 query `1680855546638295042` 和它的两个真实 gold candidate：`3556656f402e943645de829cc3fe6b17`、`72fb5d015b2cd8492ca8d9c7918e45ea`。该 query 在原始 SQL 中确实存在，mapping 中确实对应这两个候选，其中一条来源标为原始标注，另一条来源标为外源补全。由于当前终端读取中文源文件时可能显示编码替代字符，下面不把乱码强行反解为中文地名，而以稳定 ID、文件字段和生成的 CSV 为准。命令示例均从仓库根目录执行。

阶段分界：

| 命令 | 阶段 | 输入范围 | 产物用途 |
|---|---|---|---|
| 一：单元测试 | 测试 | 固定小型测试夹具 | 验证代码行为 |
| 二：冒烟测试 | 测试 | 12 query、最多 48 candidate | 验证流程可运行 |
| 三：小样本金标准 | 测试 | 12 query、48 candidate、20 mapping | 检查资产格式与标签政策 |
| 四：地理资产审计 | 正式资产准备 | 全量 POI / 行政地理资产 | 冻结正式实验使用的外源资产 |
| 五：实体划分 | 正式资产准备 | 全量 gold mapping | 生成防泄漏 split |
| 六：成对训练资产 | 正式资产准备 | 全量记录、mapping、split 和 POI | 生成 train/validation/test 特征数据 |
| 七：完整候选库实验 | 正式实验 | 全量训练资产及 3,260 candidates | 生成四档比较表和 query 集合 |

#### 3.7.1 命令一：运行回归测试（测试）

```text
py -m unittest discover -s code/tests -v
```

这条命令不读取全量业务数据，也不生成论文结果。`unittest discover` 在 `code/tests` 下寻找测试文件，验证标准化、候选生成、地理计算、标签状态、遮蔽和 split 等基础函数。实际结果为 15 项测试通过；例如测试会验证 `龙湖花园一期` 的名称标准化、候选 `b1` 能被名称通道召回，以及集合阈值 `0.72` 能输出分数 `0.8` 的候选。这里的 `q`/`b1` 是测试代码中人工构造的 fixture，不是业务数据。该命令把源码行为转换成可重复的“代码契约”，失败时后续资产不能视为可靠。

#### 3.7.2 命令二：12 条样本冒烟测试（测试）

```text
py code/smoke_test.py --sample-size 12
```

`--sample-size 12` 使 `run_sample_pipeline()` 读取前 12 条物业 query；当前冒烟测试代码内部把候选读取上限写成 `sample_size * 4`，因此这次对应前 48 条房交 candidate，并读取有限 POI。这个“4 倍”不是业务规则、模型假设或评测协议，也不是因为每个 query 理论上只对应 4 个 candidate；它只是为了让小样本测试中候选侧比 query 侧更大，能够实际走一遍候选召回、成对特征和集合输出路径，同时把运行时间控制在很小范围内。

因此，`12 -> 48` 在当前 `smoke_test.py` / `run_sample_pipeline()` 入口中是**代码写死的冒烟测试启发式比例**，用户不能通过 `--sample-size` 单独改变这个倍数：改成 `--sample-size 20` 会读取 20 条 query 和 80 条 candidate，改成 `--sample-size 5` 会读取 5 条 query 和 20 条 candidate。它不代表正式实验的候选池大小，也不能据此计算 `candidate_recall@K` 或论文指标。冒烟测试只验证流程能否贯通；正式候选池命令使用 `build_candidates.py` 的 `--query-limit`、`--candidate-limit` 和 `--k` 显式控制读取规模，完整候选库实验则使用全部 3,260 条 candidate。

对当前 `12 -> 48` 的运行，每条样本 query 会从这 48 条 candidate 中得到候选池，再为每个候选产生 `candidate_id`、`probability`、特征和 `recall_sources`。命令输出 `task=A`、实际 sample size、candidate rows、pair rows 和警告 `unknown is not confirmed_empty`，并把汇总写到 `code/sample_output/sample_report.json`。这一命令确认“原始文件 -> 统一记录 -> 候选 -> 特征 -> 集合”的数据类型和字段能贯通，但它不是正式指标。

#### 3.7.3 命令三：生成小样本金标准资产（测试）

```text
py code/build_evaluation_assets.py \
  --query-limit 12 \
  --candidate-limit 48 \
  --mapping-limit 20 \
  --output-dir code/_smoke/evaluation_assets
```

这条命令从相同原始数据读取 12 条 query、48 条候选和 20 条 mapping，生成四个文件：

```text
code/_smoke/evaluation_assets/
  gold_pairs.csv
  gold_sets.csv
  evaluation_queries.csv
  manifest.json
```

对真实 query `1680855546638295042`，如果它在这 12 条 query 和前 20 条 mapping 范围内，`gold_pairs.csv` 会把 mapping 的每一条 pair 变成一行，并保留 `match_type`、`source`、`confidence`、距离和备注；`gold_sets.csv` 会把该 query 的两个 candidate ID 聚合为一个 JSON 集合。`evaluation_queries.csv` 则写 `complete_positive_set`、gold 数量、provenance 和 coordinate status。若 query 不在有限范围，代码会写 `unknown`，而不是假造空集。`manifest.json` 还保存输入文件 SHA-256、读取限制和 mapping 重复检查，因此小样本阶段能确认标签政策和输出结构。

#### 3.7.4 命令四：审计并锁定外源数据 POI与行政地理，生成sha256指纹（正式资产准备）

```text
py code/audit_geo_assets.py --output-dir code/geo_assets
```

这条命令读取两张外源全量长表，并只生成一个 `code/geo_assets/geo_manifest.json` 审计报告，包含后续流程会用到的指纹(用来锁定数据文件的，只要改动，后续流程会报警)。**其中 `asset1_poi_coord.csv` 当前只包含任务 A 的两侧记录：物业处 8,782 条和房交处 3,260 条，不包含任务 B 的征收处或奥格记录；`asset2_admin_geo.csv` 是重庆行政区划及行政中心坐标参考表，不是任务 A 或任务 B 的业务记录表。**

命令对 POI 长表按 `(来源, 记录ID)` 检查记录键，统计总行数、可索引行数、来源分布、重复键数量以及可信/不可信原因分布；对行政区划长表检查中心坐标是否可解析，并统计总行数和可索引行数。报告还记录两张输入文件的路径和 SHA-256。

当前报告中的汇总结果为 POI 12,042 条、可信 9,451 条、重复键 0 个，行政区划记录 1,094 条。


#### 3.7.5 命令五：并查集区分实体并划分数据集（正式资产准备）

```text
py code/build_entity_splits.py \
  --output-dir code/split_manifest_full \
  --version split-v1
```

这条命令只有一个输入文件：邻接表`数据/A_mission_匹配映射_v2.csv`（3,026 行，SHA-256 `8a4bee5c0d9dbf3d15041e346f055495a59d3b9198b7e4f3877a1ee1a8e7caa5`），实际读取的字段只有 `sql_village_id` 和 `csv_yuyue_id` 两列 ID。**本命令不读任务 B**，映射路径由 `er/config.py` 的 `MAPPING_PATH` 固定。

**第 1 步** · 读边。 从邻接表 数据/A_mission_匹配映射_v2.csv 取两列 ID，得到 3,026 条 (小区ID, 房源ID)。

**第 2 步** · 并查集建实体。 由于源表格是多对多的，所以使用并查集算法，把每个物理实体分到一组，放在split_entities.csv 文件内（实际上第3步和第2步在代码里面是同时做的），里面内容如下。
```text
entity_type,entity_id,component_id,split,seed
query,1674362158372081665,component-000001,train,13
query,1680855546638295042,component-000002,test,13
query,1681204215828897794,component-000003,train,13
```
逐行解读
```text
query                           ← 被分类为 query 记录（只有query或candidate两类）
1680855546638295042             ← 它自己在源文件中的 ID
component-000002                ← 它被分到了 2 号物理实体
test                            ← 2 号组整体被分到 test数据集（划分为train validation test） 
13                              ← 这套划分是 seed=13 产生的
```

| 一组物理实体内构成 | 物理实体数  | 含义 |
|---|---|---|
| 1 query + 1 candidate | 2,754 | 普通一对一 gold |
| 1 query + 2 candidates | 107 | 一个小区对上两个房源 |
| 1 query + 3 candidates | 7 | 同上 |
| 1 query + 4 candidates | 6 | 同上 |
| 1 query + 5 candidates | 1 | 示例之外最"多对一"的一个 |
| 2 queries + 1 candidate | 4 | 两个小区同时主张同一个房源 |

**第 3 步** · 划分train/validation/test数据集
使用哈希排序（实际上就是一次随机）后，将数据集train validation test的物理实体各自划分为 2,015 / 432 / 432 即 70.0% / 15.0% / 15.0%，放在split_entities.csv 文件内。如果是"pair 单位"，train/validation/test 应该是 2,114 / 452 / 460；如果写"候选库单位"，是 2,111 / 451 / 460。

问：为什么必须整簇分，不能按 pair 随机分？
答：看那 4 个 2 queries + 1 candidate 的簇——同一个房源被两个小区都标成了 gold。如果按 pair 随机切，完全可能出现：query A 和这个房源在 train（模型见到这条正例），query B 和同一个房源在 test（模型又被要求再判一次）。模型等于背过了这个房源的名字和坐标，test 指标虚高，而且这种泄漏从结果上看不出来。


#### 3.7.6 命令六：构造train/vali/test的负例 并向量化（正式资产准备）

```text
py code/build_pair_features.py \
  --output-dir code/training_assets_full_v4 \
  --split-manifest code/split_manifest_full/split_manifest.json \
  --candidate-source full \
  --negative-ratio 3 \
  --split-seed 13
```
输入任务A的3个文件和外源的2个文件的excel表格，3个文件所属的任务A的mapping 里只有正例（3,026 条），一条负例标签都没有，所以需要构造。

构造负例，以 query_id=1852284257089507329 为例，它在 mapping 里只有一行（配 da915017… 明月小区）。要造 3 条负例（`--negative-ratio 3`设置的数量）：
**1.** 把同训练集(split) 的所有元素都当候选池：这个 query 在 train训练集中，train训练集有 2015个物理实体簇(共 2,111 个 candidate)；
**2.** 扣掉同物理实体簇的金标准gold：把这 1 条 gold（da915017… 明月小区）从池子里剔除 → 剩 2,110个candidate,共2014个物理实体；
**3.** 计算14 维向量：放入 `pairs_train.csv`中

| # | 特征 | 怎么算 | 备注 |
|---|---|---|---|
| 1 | name_exact | 归一化名字相等且非空 → 1 | 会被 rho 遮蔽 |
| 2 | name_similarity | 归一化名字的字符二元组 Jaccard | 会被 rho 遮蔽 |
| 3 | address_similarity | 同样的 Jaccard，作用在地址上 | query 地址恒空 → 恒 0；无合法对称替代 |
| 4 | area_match | 区县字符串相等（应走别名/代管等价） |  |
| 5 | street_match | 行政街道/镇/乡一致（去后缀，不按文本相似度） | candidate 侧已由逆地理编码补全 |
| 6 | coords_available | 距离算得出来 → 1 |  |
| 7 | coords_trust_both | 两侧坐标都可信 → 1 |  |
| 8 | poi_distance_m | 距离（米）除以 2000，上限 10 | 158.1 m → 0.0791 |
| 9–12 | poi_distance_lt_100m / 100_300m / 300_1000m / gt_1000m | 距离分档 one-hot |  |
| 13 | poi_district_match | 高德区县相等 |  |
| 14 | type_match | 物业类型相等 |  |

**3.** 按三个维度组合候选：先按 POI 距离升序（query 坐标周围 9 个网格、最近 30 个），再按名字相似度name_similarity降序，最后同区县兜底；三段是按优先级首尾相接的一条队列，先来的先筛掉，后来的不用；POI 距离近的行够多时，文本和区县通道对结果没有任何贡献。
**4.** 取前 3 条（3 × gold 数 = 3 × 1 = 3），写成 3 行 label=0、provenance=constructed_negative、match_type=full_hard_negative。

最后如果这个源query是train的，就都放入 `pairs_train.csv`。如果是另外两个数据集就放入对应的文件。结果就是 pairs_train.csv 里这 4 行：

| candidate_id | label | 候选名 | 候选区县 | poi_distance_m |...|
|---|---|---|---|---|---|
| da915017…f835 | 1 | 明月小区 | 垫江县 | 158.11 | ...|
| 252bfe53…1765 | 0 | 丽水南岸 | 垫江县 | 184.40 |... |
| 0931ed39…ae25 | 0 | 翠湖名都 | 垫江县 | 194.20 | ...|
| 4cafda4a…ffd45 | 0 | 滨湖郡 | 垫江县 | 265.19 | ...|


这 4 行的 address_similarity=0.0、street_match=0、poi_distance_lt_100m=0、poi_distance_100_300m=1 也写入 CSV。两项恒 0 的原因不同且都是**结构性**的：

- `address_similarity`：物业处 SQL 没有地址列，query 侧 `address` 恒为空，`similarity()` 任一侧为空即返回 0.0，因此**正例也为 0**；
- `street_match`：房交 CSV 没有街道列，candidate 侧 `street` 恒为空，比较式恒为假。

`street_match` 已在资产侧修复：对房交已冻结的面坐标质心做逆地理编码，补出行政街道与 `高德区县`（3,260/3,260，坐标未改动），使 `street_match` 在现有成对资产上的正例命中达到 94.1% / 91.6% / 91.7%（train/validation/test）、负例 58.9% / 34.0% / 38.0%。地址侧没有合法的对称定义（粗粒度街道不能推细粒度门牌），应改为单向的行政一致性特征或删除。下表是**补全前**的字段快照：
| 字段 | query（物业处 SQL） | candidate 负例（房交 CSV） |
|---|---|---|
| name | 明月小区 | 丽水南岸 |
| area | 垫江县 | 垫江县 |
| street | 桂阳街道 | （空字符串） |
| address | （空字符串） | 丽水南岸6栋1单元1楼 |
| type | 住宅（纯住宅） | 住宅 |

补全后，candidate 负例的 `street` 变为逆地理编码得到的行政街道（同一批垫江县记录多为 `桂阳街道`），`poi_district_match` 也随之可用；query 侧仍没有地址，`address_similarity` 保持恒 0。

输出为：

```text
pairs_train.csv       # 8,454 rows
pairs_validation.csv  # 1,788 rows
pairs_test.csv        # 1,835 rows
feature_manifest.json # 只记字段白名单、输入哈希、负例政策，不存任何向量
```

#### 3.7.7 命令七：四档遮蔽 跑模型

```text
py code/run_full_library_experiment.py \
  --data-dir code/training_assets_full_v4 \
  --cache-dir .audit_work/full_candidate_cache_v4 \
  --output-dir code/full_library_results_disk_v4 \
  --mask-ratios 0,0.3,0.6,1.0 \
  --seed 42 \
  --split-seed 13
```


参数含义如下：`--data-dir` 指向第六步的训练/validation/test pair 资产；`--cache-dir` 指向可恢复的磁盘 score cache；`--output-dir` 保存最终比较表和 query 集合；`--mask-ratios` 依次运行不遮蔽、遮蔽 30%、60% 和 100%；`--seed 42` 固定实体级名称遮蔽；`--split-seed 13` 选择第五步的 split。

用 pairs_train.csv 训练、用 pairs_validation.csv 定阈值，然后让 432 个物理实体的 test query 各自对全部 3,260 个pair候选打分，按阈值切成预测集合，最后算指标；rho = 0 / 0.3 / 0.6 / 1.0 四档 × 7 个方法，共 28 次独立运行（每次运行一次）。
**1.** 四挡遮蔽：实体级别的遮蔽，只要这个query或者candidate被遮蔽了，就固定隐去这一行14维向量中的name_exact和name_similarity列（由命令六计算得出）。四挡指的是rho为四个数值时，按各自的概率隐去各自数量的行的这两列。pairs_train.csv永远是未遮蔽版本，遮蔽只发生在实验运行时的内存里。
**2.** 用遮蔽后的trian训练：输入 14 维数值特征，一共用了7个方法进行训练，输出正类概率。

| # | 方法 | 类型 | 用到的特征 |
|---|---|---|---|
| 1 | 主字段精确匹配 | 规则 | 只取 name_exact（0/1）当分数 |
| 2 | TF-IDF-like Cosine | 规则 | 只取 name_similarity（字符二元组 Jaccard） |
| 3 | LightGBM Text/Structure | 学习 | 14 维中把 poi_*、coords_trust_both 置 0 |
| 4 | LightGBM + POI | 学习 | 全部 14 维 |
| 5 | **Full Model** | 学习 | 与 4 配置完全相同 |
| 6 | E2 remove POI | 学习 | 与 3 配置完全相同 |
| 7 | E4 structure-only | 学习 | 名字/地址/街道/类型全部置 0 |

**3.** validation定阈值：因为F1等指标的计算过程需要知道预测为正的候选数具体有多少，而模型并不是输出的正负，而是概率，所以才需要计算阈值tau，大于tau就是正，小于就是负。阈值怎么计算？

把433 个 validation的 query × 3,260 个候选=得到的 1,411,580 组query和candidate，即 1,411,580个分数放到20,000个桶里面，第一个桶装载1/20000 = 0.00005 ，即0~0.00005的概率，第二个桶装载0.00005~0.00010 这个分段的概率，这个方法叫 “最大 F1 阈值法”。分别累计正例和负例落在每个桶里的数量，从高分往低分扫，每降低一次门槛就多纳入一批分数，下面以小数点后两位数的tau距离（实际是小数点后5位数）：

| tau（切点） | 判为正的 | TP | FP | FN | 全局 F1 |
|---|---|---|---|---|---|
| > 0.95 | 无 | 0 | 0 | 5 | 0 |
| 0.95 | 1 个 | 1 | 0 | 4 | 0.333 |
| 0.90 | 2 个 | 2 | 0 | 3 | 0.571 |
| 0.85 | +1 负例 | 2 | 1 | 3 | 0.500 |
| 0.80 | +1 正例 | 3 | 1 | 2 | 0.667 |
| 0.60 | +1 负例 | 3 | 2 | 2 | 0.600 |
| 0.40 | +1 正例 | 4 | 2 | 1 | 0.727 |
| 0.30 | +1 正例 | 5 | 2 | 0 | 0.833 ← 这里最高 |
| 0.20 | +1 负例 | 5 | 3 | 0 | 0.769 |
| 0.10 | +1 负例 | 5 | 4 | 0 | 0.714 |

所以最后tau就是0.833。注意validation 被用了两次：既做早停监控，又用来选阈值，阈值指标存在轻微乐观偏差，应说明这是"validation-tuned"而非"test-tuned"。

**4.** test预测打分：按照上一步validation的阈值tau 直接进行切割来计算F1等指标。test 不重新训练，validation 和 test 共用同一个已训练模型，test 阶段只做"打分 + 用 validation 定的阈值切集合"。 预测主要计算三个指标Precision	Recall	F1。全量汇总写入 `full_candidate_comparison.csv`

#### 3.7.8 命令七产生的正式结果文件如何被使用

第七步最终产生：

```text
code/full_library_results_disk_v4/
  full_candidate_comparison.csv
  full_candidate_manifest.json
  rho_0_*_query_sets.csv
  rho_0.3_*_query_sets.csv
  rho_0.6_*_query_sets.csv
  rho_1_*_query_sets.csv
```

`full_candidate_comparison.csv` 用于主对比和消融表；`rho_0.6_Full_Model_query_sets.csv` 这类文件用于逐 query 错误分析；`full_candidate_manifest.json` 用于核对 query 数、candidate 数、rho、seed、split seed、POI 哈希和 `data_fingerprint`（输入 pair 资产的指纹，缓存据此失效）。注意：结果目录为 `code/full_library_results_disk_v4/`；特征修复前的旧结果已删除，不再保留对照基线。这里的四档完整库结果是 `fixed_pool` 排序诊断，候选池固定为全量 3,260 条，因此不能代替名称遮蔽后重新生成名称召回索引的 `end_to_end` 候选召回实验。`unknown` query 仍不等于 `confirmed_empty`，所以这些文件也不能单独证明严格业务拒识率。

### 3.8 结果资产和复现顺序

从仓库根目录按以下顺序运行：

```text
py -m unittest discover -s code/tests -v
py code/smoke_test.py --sample-size 12
py code/build_evaluation_assets.py --query-limit 12 --candidate-limit 48 --mapping-limit 20 --output-dir code/_smoke/evaluation_assets
py code/audit_geo_assets.py --output-dir code/geo_assets
py code/build_entity_splits.py --output-dir code/split_manifest_full --version split-v1
py code/build_pair_features.py --output-dir code/training_assets_full_v4 --split-manifest code/split_manifest_full/split_manifest.json --candidate-source full --negative-ratio 3 --split-seed 13
py code/run_full_library_experiment.py --data-dir code/training_assets_full_v4 --cache-dir .audit_work/full_candidate_cache_v4 --output-dir code/full_library_results_disk_v4 --mask-ratios 0,0.3,0.6,1.0 --seed 42 --split-seed 13
```

结果、manifest、query 集合和审计文件必须与 `rho`、split seed、数据版本和候选库协议一同保存。

## 4 两个任务的定位

### 4.1 任务 A：同级评测任务

| 项 | 内容 |
|---|---|
| Query 侧 | 物业处 8,782 条 |
| 候选侧 | 房交处 3,260 条 |
| 关系形态 | 非 1:1；query 侧最多 5 个 pair，平均 1.05 pair/query |
| 召回主字段 | 整体项目名称/小区名称 |
| 实体判定字段 | 期次、组团、地址、行政区划、可信空间证据和结构字段 |
| 当前 mapping 未覆盖 query | 5,899 条；未覆盖不等于 `confirmed_empty` |
| 研究作用 | 独立业务表条件下的跨源地点解析 |

A 的自然名称一致率很高，必须单独报告名称遮蔽、同名异地、近距离异地和坐标不可用切片，避免把名称捷径当成物理地点理解。

### 4.2 任务 B：同级评测任务

| 项 | 内容 |
|---|---|
| Query 侧 | 征收处 28,101 条 |
| 候选侧 | 奥格 28,101 条 |
| 关系形态 | 原始数据保留同行结构；实验输出仍允许集合 |
| 主匹配字段 | `征收处_房屋地址` ↔ `fwxxdz` |
| 空集标签 | 原始数据无天然空集；需按固定协议构造留空样本 |
| 研究作用 | 同一工作簿内异构字段条件下的同级协议评测 |

A、B 使用同一套三态标签、候选生成、成对匹配、集合输出和拒识协议，分别报告，不合并为一个总分。B 两侧来自同一 Excel，且字段高度同值；`id`、奥格编号和地址存在重复，不能使用行号、原始行顺序、编号或同行关系作为实体键或模型特征。B 的留空负例构造方式必须在配置中固定，并单独标记为构造协议。

## 5 金标准与评测集

### 5.1 版本化数据资产

实验开始前冻结并版本化：

- `gold_pairs`：pair 级金标准；
- `gold_sets`：每个 query 的完整 `G(q)`；
- `evaluation_queries`：全量 query 及标签状态；
- `candidate_pool`：完整候选池及版本；
- `split_manifest`：实体簇与 train/validation/test 划分；
- `mask_manifest`：遮蔽比例、query、seed 和派生字段处理；
- `feature_manifest`：字段白名单、黑名单和特征版本。

每条 gold pair 至少包含：

```text
query_id
candidate_id
gold_status
relation_granularity
provenance
evidence_source_id
annotator_or_script_version
verified_at
split
```

每条 query 还必须包含：

```text
query_label_state  # complete_positive_set / confirmed_empty / unknown
label_completeness
negative_evidence_status
review_status
coordinate_status
```

`unknown` 不自动等同于 `confirmed_empty`，不进入训练负例、确认标签主指标、拒识阈值选择或概率校准。

`provenance` 至少区分：

- `original_annotation`：原始业务标注；
- `external_derived`：依赖外源地理结果形成或补全；
- `independent_review`：不展示同一模型输入中的外源证据而完成的独立复核。

2,709 个原始标注 pair 与 317 个外源补全 pair 必须分别报告。`2,709 + 317` 是 pair 数，不是 query 数；query 数按 pair 去重后统计。

### 5.2 A 任务的全量核算

query-level 标签必须与证据和坐标状态分开记录：

- **`complete_positive_set`**：存在完整且非空的 `G(q)`；
- **`confirmed_empty`**：仅由独立排除证据确认 `G(q)=empty`；
- **`unknown`**：当前 mapping 未覆盖、候选覆盖不足、证据不足或存在冲突，不能自动视为负例；
- **坐标状态**：单独记录，坐标不可用不改变实体标签。

当前数据版本的已知核算如下。原有“强负例/弱负例”是证据或构造类别，不在完成独立排除前直接等同于 `confirmed_empty`：

| 类别 | query 数 | 对应 pair 数 |
|---|---:|---:|
| 已确认正例，可评测 | 2,822 | 2,965 |
| 当前 mapping 未覆盖，待核验 | 5,899 | — |
| 其中：正例坐标不可用/不可信 | 61 | 61 |
| 其中：负例坐标不可用/不可信 | 216 | — |
| 其中：近处有候选且相似度处于待核验区间 | 215 | — |
| 其中：同名但未配对、证据不足 | 156 | — |
| **全量物业处 query** | **8,782** | **3,026 个 pair** |

校验：`2,965 + 61 = 3,026` 个 pair；`2,883 + 5,899 = 8,782` 个 query。`5,899` 仅表示当前 mapping 未覆盖的 query 数，不表示已经确认候选侧不存在对应地点。

`unknown` 和尚未完成核验的未覆盖 query 不进入训练负例、确认标签主指标、TN/拒识率或阈值校准。只有形成逐 query 的独立排除证据后，才可从 `unknown` 升级为 `confirmed_empty`。

主结果必须同时报告：

1. 全量业务覆盖：8,782 个 query 的标签状态、unknown、坐标不可用和待核验数量；
2. 已确认标签性能：仅对确认标签计算正式指标，并报告筛选比例；
3. 证据来源切片：`original_annotation`、`external_derived`、`independent_review` 分层；
4. 坐标可用与不可用切片：坐标不可用样本不能静默删除，应进入文本/结构匹配和拒识分析；
5. 待核验样本：不计入确认标签主分数，但报告数量、抽样复核结果和 unknown 比例。

强负例若使用名称相似度和距离构造，必须明确其为协议规定的反事实负例；另行报告不依赖同一名称阈值的人工或独立证据负例敏感性分析。

### 5.3 Hard Challenge

自然评测集用于反映业务分布；Hard Challenge 单独用于检验物理地点歧义和抗名称捷径能力，不与自然集合并为一个总分。

困难类别包括：

| 类别 | 内容 | 标签要求 |
|---|---|---|
| P1 | 名称变体正例：简称、前后缀、分隔符、轻微错写 | 人工或独立证据确认同一地点 |
| P2 | 同名消歧正例：同名候选中只有部分地点一致 | 按完整 `G(q)` 标注 |
| P3 | 主字段完整遮蔽正例 | 遮蔽前后标签不变 |
| P4 | 整体名称对应多个期次的正例 | 记录 `project_contains_phase`，允许集合输出 |
| N1 | 同名异地负例 | 独立证据确认不同地点 |
| N2 | 近距离异地负例：不同小区、期次或组团 | 至少保留可竞争候选 |
| N3 | 同区县/同街道但不同物理地点 | 不把行政中心当精确地点 |
| N4 | 整体名称下不同期次或不同组团的近邻负例 | 例如一期与二期默认不同实体 |
| P5/N5 | 坐标不可用的可确认正例/负例切片 | 坐标不可用不能自动当负例 |

Hard Challenge 的每条记录至少包含：

```text
query_id
gold_candidate_ids
label
difficulty
name_sim
distance_m
admin_match
coords_trust
evidence_source
provenance
annotation_status
split
mask_seed
```

无法独立确认的样本标记为 `unknown`，不计入确认标签主分数，另报抽样结果。若困难样本只出现在测试集，报告为 OOD stress test；若要解释为常规能力，训练和 validation 也必须包含实体不重叠的同类样本。

### 5.4 主字段遮蔽

遮蔽比例统一设为：

```text
rho in {0, 0.3, 0.6, 1.0}
```

同时报告两种协议：

- `fixed_pool`：候选池在未遮蔽输入上冻结，遮蔽只作用于成对特征和排序，评估固定候选池上的条件性能；
- `end_to_end`：遮蔽后同步清除名称、期次名称、重复拼接片段、召回索引和缓存文本，并重新执行候选召回；这是主结果协议。

query 侧和 candidate 侧执行相同的遮蔽协议。两种协议复用同一 `mask_manifest`，但分别保存候选池版本和召回指标。`fixed_pool` 只能解释为排序诊断，`end_to_end` 才能解释为字段缺失下的完整系统鲁棒性。

当主字段被遮蔽时，同时清除：

- 原始主字段；
- 规范化主字段；
- 期次、组团和拼接字段中的重复名称；
- 地址或 POI 查询文本中的重复名称片段；
- 由主字段派生的缓存文本和召回索引。

遮蔽后的结果报告为字段缺失鲁棒性，不表述为自然缺失分布的无偏估计。

## 6 划分与防泄漏

### 6.1 主划分

不能按 pair 随机切分。先建立完整 gold 二部图，以 connected component 作为最小划分单元；必要时把经独立证据确认的同一物理地点或同一组团合并为实体簇。相关 query、candidate、别名、困难扰动和由其生成的负候选只能进入同一 split。

主结果报告两种协议：

- **跨记录归纳**：测试记录 ID 在训练阶段未出现，但同一物理地点可能在训练数据中有另一条记录；
- **跨地点归纳**：测试物理地点实体簇不出现在训练阶段；这是论文主协议。

整体名称覆盖多个期次时，项目级名称实体及其期次实体必须进入同一实体簇；一期与二期不能按名称拆开后跨 split。地址重复且已确认属于同一物理地址建筑物的 B 记录共享 `entity_cluster_id`，但原始记录保留，不以删除行替代实体聚合。

随机 pair 划分只能作为附录诊断，不作为主结论。使用 5 个固定 seed，报告均值和标准差；方法之间配对复用 split、候选池、负例和 mask。

### 6.2 归纳式要求

主模型应能够对新记录进行编码和推理。是否使用记录 ID、已有关系、索引信息或图结构，由具体模型协议决定；每个协议必须明确写出这些信息的来源、作用和是否可能造成传导式结果。

若使用 TF-IDF/SVD，归纳式主结果只在 train fit，再 transform validation/test；允许全量无标签文本参与拟合时，必须单列为 transductive 结果。

训练图若保留，只能包含允许的 train gold 边。validation/test gold 边、测试标签和由测试标签派生的辅助边不得进入训练图。

### 6.3 外源证据独立性

外源 API 快照必须在标签确认、split 和调参前冻结，保存原始响应、查询文本、采集时间、API 版本、坐标系、许可和配额信息。

同一 POI 结果如果参与 gold 确认，又进入模型特征，则不能在同一主结果中同时被当作独立标签证据和模型证据。每条外源结果必须记录其用途：

```text
external_used_for_label
external_used_for_candidate
external_used_as_feature
```

此类样本必须：

- 由不展示该 POI 结果的人工或第二独立来源复核；或
- 标为 `external_derived`，单独报告。

POI 进入 Full Model 的可信空间特征。`text/structure-only` 作为必要对照；如果 POI 参与候选召回，POI-disabled 运行必须重新生成候选池和召回指标，不能只删除距离特征。

### 6.4 泄漏检查清单

每次实验运行前后保存并检查：

- query ID、candidate ID、Excel 行号和合并索引是否作为特征，必须按实验协议显式记录；
- 同一 B 实体和同一物理地点未跨 split；
- train/validation/test 的 gold 集合没有交叉；
- TF-IDF/SVD 和可学习预处理符合 inductive/transductive 声明；
- 测试标签、已有对应关系和索引信息的使用方式与实验协议一致，并有独立对照；
- 外源快照在标签、split 和调参前冻结；
- 训练图只含允许的 train gold 边；
- 每次运行保存数据版本哈希、配置哈希、split manifest、候选池版本、外源快照哈希和阈值配置。

## 7 指标

### 7.1 候选与排序

候选阶段：

- `candidate_recall@K`；
- 平均候选数；
- 候选覆盖率；
- 各召回通道的增量覆盖率。

排序阶段：

- Recall@1/5/10；
- MRR；
- nDCG；
- query-macro 集合 Precision/Recall/F1；
- pair-micro 集合 Precision/Recall/F1。

### 7.2 链接与拒识

对于 `G(q) != empty` 的正例 query：

- any-hit：`S(q) ∩ G(q) != empty`；
- 集合级 precision/recall：惩罚漏配和过量输出；
- 误拒率：预测空集合的正例比例。

对于 `G(q) = empty` 的 query，只有 `query_label_state=confirmed_empty` 才进入确认负例拒识指标：

- 正确拒识率/特异度：正确输出空集合的确认空集比例；
- 错误链接率：确认空集 query 输出非空集合的比例。

`unknown`、未覆盖待核验 query 和无法证明完整性的 query 不进入上述分母，也不进入训练负例和阈值校准。

主表必须报告：

```text
TP, FP, FN, TN
预测链接率
link precision / recall / F1
负例拒识率
正例误拒率
balanced accuracy
AUROC / AUPRC
```

Precision 的分母是预测为链接的 query 数，Recall 的分母是真实正 query 数；不得把所有指标都写成“分母为全部 query”。所有表格注明 query 或 pair 基数。

### 7.3 可靠性

在不使用测试标签调参的前提下报告：

- coverage-risk 曲线；
- risk@coverage；
- P@90% coverage；
- ECE；
- Brier score；
- 校准曲线；
- 强负例和弱负例分别的拒识率。

旧版 `P = R = Hit@K` 的评估定义废弃。Hit@K 只能作为附录检索诊断，不能作为主 Precision、Recall 和 F1。

## 8 方法对照与消融

所有方法使用相同候选池、实体划分、mask、阈值选择协议和输出定义。

| 方法 | 作用 |
|---|---|
| 主字段精确匹配 | 主字段可见时的强基线，不能作为系统最终规则 |
| 规范化字段规则 | 非神经规则基线 |
| 距离/行政规则 | 空间与粗粒度行政基线 |
| TF-IDF Cosine | 纯文本相似度基线 |
| 逻辑回归 pair classifier | 可解释的成对模型 |
| LightGBM text/structure | 无 POI 对照模型 |
| LightGBM + POI | POI 增量模型 |
| LightGBM + POI + 行政中心 | Full Model 主模型 |
| 原始 LightGCN | 图传播附加对照，只作 transductive 结果 |

消融统一编号：

- E1：去行政区划中心特征；
- E2：去 POI 坐标和距离特征；
- E3：去空间/行政辅助关系，仅保留成对字段特征；
- E4：距离分层负采样改为随机负采样；
- E5：`rho=0` 与各遮蔽率对照；
- E6：按 POI 可信度、level 和 provenance 分层，或完全禁用 POI。

每项消融只改变一个因素。结论必须按自然评测集、Hard Challenge、坐标可信度、gold provenance 和遮蔽率分层报告。

## 9 执行顺序与验收标准

| # | 步骤 | 验收标准 | 状态 |
|---|---|---|---|
| 1 | 冻结数据和外源资产 | 原始文件、POI、行政中心、坐标转换和快照均有版本与哈希 | 基础资产和 POI manifest 已完成；行政中心特征仍待接入审计 |
| 2 | 锁定 gold provenance | 3,026 pair、2,883 query、2,709/317 来源分层；独立复核状态明确 | 已完成原始标注/外源补全分层；independent_review 和 mapping 完整性仍待确认 |
| 3 | 生成评测资产 | `gold_sets`、全量 query、候选池、unknown、confirmed_empty、负例和 manifest 数字闭合 | gold/candidate/split/training 资产已生成；confirmed_empty 和独立排除证据仍待做 |
| 4 | 实现实体簇划分 | connected component/物理地点簇不跨 split；整体名称与期次归入同一项目簇；地址重复的 B 记录共享实体簇；保存 5 个 seed | A connected component split 已完成 5 个 seed；B 和项目/期次人工簇仍待做 |
| 5 | 实现字段遮蔽 | 四个 rho、派生字段同步清除、mask 固定复用 | 四个 rho 的 fixed_pool 已完成；end_to_end 候选池遮蔽框架已完成，完整库结果仍属 fixed_pool |
| 6 | 实现候选生成 | 多路召回、候选版本、candidate recall@K 和失败记录 | A 自然/fixed_pool/end_to_end 候选池与召回审计已完成；POI-disabled 独立重召回仍需作为最终消融固化 |
| 7 | 实现成对特征和主模型 | 记录对特征、LightGBM/逻辑回归、缺失和冲突处理 | A 成对特征、分层负例、逻辑回归/LightGBM 诊断已完成；行政中心距离特征和独立 E1 尚未实现 |
| 8 | 实现集合输出与拒识 | validation 校准、冻结阈值、集合指标和拒识指标 | validation 阈值和 full-pool 集合输出已完成；概率校准、confirmed_empty 拒识指标未完成 |
| 9 | 实现对照和消融 | A、B 两个同级任务、Hard Challenge、E1–E6；分别报告，不合并总分 | A 完整库四档遮蔽主对照及部分消融已完成；B、Hard Challenge、E1/E3/E4–E6 正式对照仍待做 |
| 10 | 泄漏审计和错误分析 | checklist、哈希、错误样本、provenance 和坐标切片报告 | split、输入/POI manifest、缓存 SHA-256 和集合一致性已审计；人工 FP/FN、可靠性和校准分析仍待做 |

在第 3–10 步完成前，运行结果只能称为现有代码基线或数据核查，不得称为 Full Model 主结果。`unknown` 保持为 `unknown`，不因当前未映射而升级为 `confirmed_empty`。在 `confirmed_empty` 尚未由独立排除证据形成前，只报告其覆盖情况和诊断结果，不报告严格拒识主指标。

## 10 当前风险与结论边界

1. A 的名称一致率为 99.6%，自然集可能被主字段捷径主导；必须以遮蔽和困难集检验物理地点证据。
2. A 的自然名称变体只有 15 条，不能据此声称自然异名解析已经充分验证。
3. B 与 A 同级评测但必须分别报告；B 的同行字段同值、重复地址和已修复 ID 不能被解释为独立跨源泛化证据。
4. 外源 POI 是由名称/地址派生的地理证据，进入 Full Model 但必须记录标签、候选和特征用途并按 provenance 分层。
5. 行政区划中心是粗粒度位置，不是行政边界，也不是精确地点坐标。
6. 坐标不可用样本不能静默删除，至少要单独报告文本/结构匹配和拒识结果。
7. 未映射 query 和 unknown 不能自动作为 confirmed_empty；严格拒识结论需有独立排除证据。
8. 如果 Hard Challenge 只在测试出现，它是 OOD stress test；低分不能直接解释为一般模型能力不足。

## 11 可复现性

- 固定随机种子和软件环境；
- 版本化原始数据、gold、候选池、split、mask、特征配置和模型配置；
- 保存外源 API 原始响应、查询文本、采集日期、坐标系、许可与配额信息；
- 保存每次运行的配置哈希、数据哈希、split manifest、候选池版本、阈值和校准器；
- 所有结果注明任务、split 协议、rho、query/pair 基数、gold provenance 和坐标可信度切片。

## 12 运行入口与代码结构

### 12.1 环境

- Python 3.12；核心单元测试只用标准库，完整模型实验需要 LightGBM 4.x：`py -m pip install lightgbm`。
- 原始数据默认从 `数据/` 读取，路径与字段映射集中在 `code/er/config.py`；所有命令都不修改原始数据。
- 全部命令在仓库根目录执行；完整执行顺序见 §3.8，本节只补 §3.8 未包含的入口。

### 12.2 补充命令

| 用途 | 命令 |
|---|---|
| 小样本候选池 | `py code/build_candidates.py --query-limit 12 --candidate-limit 48 --mapping-limit 20 --output-dir code/_smoke/candidate_pool --k 20` |
| 自然候选池与召回审计 | `py code/build_candidates.py --output-dir code/candidate_pool_full --protocol natural --k 20` |
| 四档 `end_to_end` 遮蔽召回 | `py code/run_masked_candidate_sweep.py --output-dir code/candidate_pool_mask_sweep --protocol end_to_end --k 20 --seed 42` |
| 有限负例成对诊断 | `py code/run_pair_model_experiments.py --data-dir code/training_assets_full_v4 --output-dir code/pair_model_results --mask-ratio 0.6 --mask-seed 42` |

`code/_smoke/` 是临时诊断目录，命令验证通过后可删除，不作为论文结果。

### 12.3 代码结构

| 模块 | 职责 |
|---|---|
| `er/config.py` | 数据路径与任务字段配置 |
| `er/io.py`、`er/normalize.py` | 读取、字段标准化与文本相似度 |
| `er/geo.py`、`er/geo_asset.py`、`er/poi_candidate.py` | 坐标、可信 POI 与网格召回 |
| `er/gold.py` | 金标准与三态标签资产 |
| `er/candidate.py`、`er/candidate_pool.py` | 多通道候选召回与召回审计 |
| `er/split.py` | 实体簇 split |
| `er/mask.py`、`er/mask_sweep.py` | 名称遮蔽与候选池遮蔽实验 |
| `er/features.py`、`er/training_data.py` | 成对特征与分层负例 |
| `er/experiments.py`、`er/lightgbm_model.py` | 成对模型、阈值与 LightGBM |
| `er/full_library.py`、`er/disk_cache.py` | 完整候选库、磁盘缓存与集合输出 |
| `er/pipeline.py`、`er/model.py`、`er/output.py` | 小样本基线流程 |
| `tests/` | 16 项回归测试 |

已完成结果与解释边界见 `experiment.md`。
