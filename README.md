# 主实验计划与结果：跨源物理地点实体解析与拒识

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

围绕这三个阶段，本文报告两个独立实验，分别评估、不合并总分：

| 实验 | 评估对象 | 输出口径 | 章节 |
|---|---|---|---|
| 实验一 | 每个 test query × 全部 3,260 个候选 | 按 validation 阈值输出集合 | §4 |
| 实验二 | 1,835 个构造 pair（460 正 / 1,375 负） | 逐对二分类 | §5 |

两者口径不同（集合输出 vs 成对二分类），指标不可合并或横向比较；实验二只用于诊断名称遮蔽下的成对判别与 POI 增量，不作为最终实体解析主结果。

### 1.4 论文主张边界

论文主张限定为：在给定候选库、字段映射和外源地理资产的条件下，建立一个能够融合多源证据、处理字段缺失和冲突、对新记录进行推理，并在候选侧不存在对应地点时拒识的跨源物理地点实体解析方法。

本文不声称解决任意城市、任意业务表的通用地点解析；所有结论限定在数据字段、空间范围、候选库和外源资产条件内。

## 2 数据事实与评测集

### 2.1 已核实的数据事实

> 以下事实来自当前数据核查，是实验设计依据。数字发生变化时，必须先更新数据版本和本节核算。

| 项目 | 事实 | 实验影响 |
|---|---|---|
| 规模 | A：物业处 8,782 / 房交处 3,260；B：征收处 28,101 / 奥格 28,101 | A、B 是同级评测任务；候选侧规模是主要计算约束 |
| A 关系形态 | 非 1:1；query 侧最多 5 个 pair，平均 1.05 pair/query | 必须按集合输出，不能假设一对一 |
| A 金标准 | 3,026 个 pair，覆盖 2,883 个 query；其中 2,709 个原始标注 pair、317 个外源补全 pair | pair 和 query 必须分开计数；按 provenance 分层报告 |
| A 标签核算 | 已确认正例 2,822 个 query / 2,965 个 pair，其中正例坐标不可用 61 个 pair | 恒等式：`2,965 + 61 = 3,026` 个 pair；`2,883 + 5,899 = 8,782` 个 query |
| A mapping 覆盖 | 8,782 个 query 中 2,883 个在 mapping、5,899 个未覆盖；未覆盖中负例坐标不可用 216、近处待核验 215、同名未配对 156 | 未覆盖不等于空集；未核验样本保持 `unknown`，不得直接作为拒识负例 |
| A 名称一致率 | 3,014 / 3,026 = 99.6%（pair 级） | 自然正例存在名称捷径，必须加入同名异地和名称遮蔽切片 |
| A 名称变体 | 15 条（0.5%） | 自然数据中的异名样本不足，不能单凭自然集声称异名解析能力 |
| A 已复核错误 | 878 条可疑对逐条复核，已知标注错误 0 条 | 主要风险是金标准不完整和证据来源混合，不是已知错标 |
| 坐标系 | 房交原始面坐标为 CGCS2000/WGS84；POI 坐标为 GCJ-02 | 距离计算前必须完成坐标转换并记录版本 |
| B 字段同值率 | 主要同行字段高度同值；地址同行相等率 100%，房屋用途为 97.3021%；`id`、奥格编号和地址均存在重复；原始数据无天然空集 | B 与 A 同级评测但单独报告；不得使用行号、编号或同行关系作为实体键；空集需按固定协议构造 |

### 2.2 版本化数据资产

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

### 2.3 A 任务的全量核算

query-level 标签必须与证据和坐标状态分开记录：

- **`complete_positive_set`**：存在完整且非空的 `G(q)`；
- **`confirmed_empty`**：仅由独立排除证据确认 `G(q)=empty`；
- **`unknown`**：当前 mapping 未覆盖、候选覆盖不足、证据不足或存在冲突，不能自动视为负例；
- **坐标状态**：单独记录，坐标不可用不改变实体标签。

原有“强负例/弱负例”是证据或构造类别，不在完成独立排除前直接等同于 `confirmed_empty`；`5,899` 只表示当前 mapping 未覆盖的 query 数，不表示已确认候选侧不存在对应地点。

`unknown` 和尚未完成核验的未覆盖 query 不进入训练负例、确认标签主指标、TN/拒识率或阈值校准。只有形成逐 query 的独立排除证据后，才可从 `unknown` 升级为 `confirmed_empty`。

主结果必须同时报告：

1. 全量业务覆盖：8,782 个 query 的标签状态、unknown、坐标不可用和待核验数量；
2. 已确认标签性能：仅对确认标签计算正式指标，并报告筛选比例；
3. 证据来源切片：`original_annotation`、`external_derived`、`independent_review` 分层；
4. 坐标可用与不可用切片：坐标不可用样本不能静默删除，应进入文本/结构匹配和拒识分析；
5. 待核验样本：不计入确认标签主分数，但报告数量、抽样复核结果和 unknown 比例。

强负例若使用名称相似度和距离构造，必须明确其为协议规定的反事实负例；另行报告不依赖同一名称阈值的人工或独立证据负例敏感性分析。

### 2.4 Hard Challenge

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

### 2.5 主字段遮蔽

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

## 3 方法方案

本项目最终采用“统一记录视图 -> 多路候选池 -> 成对特征 -> 成对模型 -> 验证集阈值 -> 集合输出”的六步流程。实现过程中对原计划作了两项重要工程化调整：完整候选库评分改为逐 query、逐候选分批计算并持久化到可恢复的磁盘 score cache（`.audit_work/full_candidate_cache_v4`），避免将 432 × 3,260 的预测字典同时留在内存；名称遮蔽实验同时保留 `fixed_pool` 诊断协议，并将名称遮蔽后的候选召回作为单独的 `end_to_end` 协议，避免混淆“排序退化”和“候选生成退化”。

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

### 3.1 统一记录视图与坐标可信判定

任务 A 的 query 来自物业处 SQL（`village_id`、`village_name`、`area_name`、`street_name` 等），候选来自房交 CSV（`愉悦安`、`小区名`、`区县`、`地址`、`物业类型`）。`code/er/config.py` 固定原始文件路径与任务字段，`code/er/io.py` 按真实 INSERT 列名解析 SQL，两侧统一为：

```python
{
    "id": "源内稳定记录 ID",
    "name": "规范化小区名称",
    "area": "规范化区县",
    "street": "规范化行政街道",
    "address": "可用时的规范化地址",
    "type": "物业类型",
    "lng": "经度（若可用）",
    "lat": "纬度（若可用）",
    "coords_trust": "坐标可信布尔值",
    "poi_district": "POI 解析区县",
}
```

原始 ID 只用于追踪和 mapping，不进入模型特征；A 的 SQL 源没有独立地址列，查询侧 `address` 恒为空，因此地址证据不能被解释为完整双侧地址匹配。

任务 A 的召回主字段是整体项目名称/小区名称，实体判定字段是期次、组团、地址、行政区划、可信空间证据和结构字段；任务 B 的主匹配字段是 `征收处_房屋地址` ↔ `fwxxdz`，原始数据保留同行结构。A、B 分别报告、不合并总分，B 的留空负例按固定协议构造。

外源 POI 资产按 `(来源, 记录ID)` 连接两侧。`code/er/geo_asset.py` 复用冻结资产中的“可信/不可信原因”，并按侧使用不同判据：物业处看坐标是否在重庆范围、解析 `level` 是否可信、解析区县是否与业务区县一致；房交坐标来自面坐标质心、没有 `level`，改看面坐标包围盒对角线是否 < 1000m 且逆地理编码区县是否与登记区县一致。当前资产 12,042 条记录中 9,451 条可信（物业处 6,329 + 房交 3,122），可信标记和不可信原因写入地理 manifest。

只有两侧坐标都可信时才计算 Haversine 距离、距离分档和 `poi_district_match`；不可信坐标保留原因，不填为 `(0,0)`，不生成空间证据。mapping 中的原始标注和外源补全在 gold manifest 中分为 `original_annotation` 与 `external_derived`；未覆盖 query 保持 `unknown`，判定规则见 §2.2。

每条外源结果还必须记录用途（`external_used_for_label` / `external_used_for_candidate` / `external_used_as_feature`）；既参与 gold 确认又进入特征的样本，须由不展示该结果的人工或第二来源复核，或标为 `external_derived` 单独报告。外源快照在标签确认、split 和调参前冻结。

### 3.2 多路候选召回与两个遮蔽协议

自然候选池由名称字符 n-gram、地址字符 n-gram、区县和其他结构通道取并集生成；可信 POI 还通过 2 km 网格及相邻 8 个网格召回。`code/build_candidates.py` 输出候选池、通道来源、候选版本、`candidate_recall_at_k.csv` 和通道增量覆盖率。

名称捷径诊断发现自然名称 n-gram Recall@10 约为 99.83%，因此加入实体级固定 seed=42 的 `rho in {0, 0.3, 0.6, 1.0}` 遮蔽：

两个协议的定义、清除范围和报告口径见 §2.5；本节只区分用途：`fixed_pool` 隔离排序对名称的依赖，`end_to_end` 测完整系统鲁棒性。

四档完整候选库结果采用前者，因此其候选召回率恒为完整库条件下的 100%，不能当作 `end_to_end` 召回结论。

### 3.3 按命令展开的真实数据流示例

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

#### 3.3.1 命令一：运行回归测试（测试）

```text
py -m unittest discover -s code/tests -v
```

这条命令不读取全量业务数据，也不生成论文结果。`unittest discover` 在 `code/tests` 下寻找测试文件，验证标准化、候选生成、地理计算、标签状态、遮蔽和 split 等基础函数。实际结果为 16 项测试通过；例如测试会验证 `龙湖花园一期` 的名称标准化、候选 `b1` 能被名称通道召回，以及集合阈值 `0.72` 能输出分数 `0.8` 的候选。这里的 `q`/`b1` 是测试代码中人工构造的 fixture，不是业务数据。该命令把源码行为转换成可重复的“代码契约”，失败时后续资产不能视为可靠。

#### 3.3.2 命令二：12 条样本冒烟测试（测试）

```text
py code/smoke_test.py --sample-size 12
```

`--sample-size 12` 使 `run_sample_pipeline()` 读取前 12 条物业 query；当前冒烟测试代码内部把候选读取上限写成 `sample_size * 4`，因此这次对应前 48 条房交 candidate，并读取有限 POI。这个“4 倍”不是业务规则、模型假设或评测协议，也不是因为每个 query 理论上只对应 4 个 candidate；它只是为了让小样本测试中候选侧比 query 侧更大，能够实际走一遍候选召回、成对特征和集合输出路径，同时把运行时间控制在很小范围内。

因此，`12 -> 48` 在当前 `smoke_test.py` / `run_sample_pipeline()` 入口中是**代码写死的冒烟测试启发式比例**，用户不能通过 `--sample-size` 单独改变这个倍数：改成 `--sample-size 20` 会读取 20 条 query 和 80 条 candidate，改成 `--sample-size 5` 会读取 5 条 query 和 20 条 candidate。它不代表正式实验的候选池大小，也不能据此计算 `candidate_recall@K` 或论文指标。冒烟测试只验证流程能否贯通；正式候选池命令使用 `build_candidates.py` 的 `--query-limit`、`--candidate-limit` 和 `--k` 显式控制读取规模，完整候选库实验则使用全部 3,260 条 candidate。

对当前 `12 -> 48` 的运行，每条样本 query 会从这 48 条 candidate 中得到候选池，再为每个候选产生 `candidate_id`、`probability`、特征和 `recall_sources`。命令输出 `task=A`、实际 sample size、candidate rows、pair rows 和警告 `unknown is not confirmed_empty`，并把汇总写到 `code/sample_output/sample_report.json`。这一命令确认“原始文件 -> 统一记录 -> 候选 -> 特征 -> 集合”的数据类型和字段能贯通，但它不是正式指标。

#### 3.3.3 命令三：生成小样本金标准资产（测试）

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

#### 3.3.4 命令四：审计并锁定外源数据 POI与行政地理，生成sha256指纹（正式资产准备）

```text
py code/audit_geo_assets.py --output-dir code/geo_assets
```

这条命令读取两张外源全量长表，并只生成一个 `code/geo_assets/geo_manifest.json` 审计报告，包含后续流程会用到的指纹(用来锁定数据文件的，只要改动，后续流程会报警)。**其中 `asset1_poi_coord.csv` 当前只包含任务 A 的两侧记录：物业处 8,782 条和房交处 3,260 条，不包含任务 B 的征收处或奥格记录；`asset2_admin_geo.csv` 是重庆行政区划及行政中心坐标参考表，不是任务 A 或任务 B 的业务记录表。**

命令对 POI 长表按 `(来源, 记录ID)` 检查记录键，统计总行数、可索引行数、来源分布、重复键数量以及可信/不可信原因分布；对行政区划长表检查中心坐标是否可解析，并统计总行数和可索引行数。报告还记录两张输入文件的路径和 SHA-256。

当前报告中的汇总结果为 POI 12,042 条、可信 9,451 条、重复键 0 个，行政区划记录 1,094 条。


#### 3.3.5 命令五：并查集区分实体并划分数据集（正式资产准备）

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

主结果报告两种协议：**跨记录归纳**（测试记录 ID 未在训练出现，但同一物理地点可能有另一条记录）与**跨地点归纳**（测试物理地点实体簇完全不出现在训练；论文主协议）。随机 pair 划分只作附录诊断；整体名称覆盖多个期次时，项目级名称与其期次实体进入同一实体簇；B 侧地址重复且确认属同一建筑物的记录共享 `entity_cluster_id`，原记录保留、不删行。使用 5 个固定 seed，方法之间配对复用 split、候选池、负例和 mask。


#### 3.3.6 命令六：构造train/vali/test的负例 并向量化（正式资产准备）

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

#### 3.3.7 命令七：四档遮蔽 跑模型

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
**2.** 用遮蔽后的训练集训练：输入 14 维数值特征，实际运行表中 1–7 共 7 个方法并输出正类概率；8–13 为补充对照，尚未在完整候选库上运行。

| # | 方法 | 类型 | 用到的特征 |
|---|---|---|---|
| 1 | 主字段精确匹配 | 规则 | 只取 name_exact（0/1）当分数 |
| 2 | TF-IDF-like Cosine | 规则 | 只取 name_similarity（字符二元组 Jaccard） |
| 3 | LightGBM Text/Structure | 学习 | 14 维中把 poi_*、coords_trust_both 置 0 |
| 4 | LightGBM + POI | 学习 | 全部 14 维 |
| 5 | **Full Model** | 学习 | 与 4 配置完全相同 |
| 6 | E2 remove POI | 学习 | 与 3 配置完全相同 |
| 7 | E4b 全特征关闭 | 学习 | 文本/POI/行政开关全关，14 维全 0（退化对照） |
| 8 | 规范化字段规则（未做实验） | 规则 | 非神经规则基线：规范化字段加权 |
| 9 | 距离/行政规则（未做实验） | 规则 | 空间与粗粒度行政基线 |
| 10 | 逻辑回归 pair classifier（完整候选库未做实验） | 学习 | 成对级已运行，完整候选库尚未纳入 |
| 11 | LightGBM + POI + 行政中心（未做实验） | 学习 | 在当前 Full Model 上接入行政区划中心特征 |
| 12 | 原始 LightGCN（未做实验） | 图模型 | 图传播附加对照，只作 transductive 结果 |
| 13 | 随机负采样（未做实验） | 学习 | 特征同 Full Model，仅把分层困难负例改为随机负采样 |

**3.** validation定阈值：因为F1等指标的计算过程需要知道预测为正的候选数具体有多少，而模型并不是输出的正负，而是概率，所以才需要计算阈值tau，大于tau就是正，小于就是负。阈值怎么计算？

把433 个 validation的 query × 3,260 个候选=得到的 1,411,580 组query和candidate，即 1,411,580个分数放到20,000个桶里面，第一个桶装载1/20000 = 0.00005 ，即0 ~ 0.00005的概率，第二个桶装载0.00005 ~ 0.00010 这个分段的概率，这个方法叫 “最大 F1 阈值法”。分别累计正例和负例落在每个桶里的数量，从高分往低分扫，每降低一次门槛就多纳入一批分数，下面以小数点后两位数的tau距离（实际是小数点后5位数）：

| tau（切点） | 判为正的 | TP | FP | FN | 全局 F1 |
|---|---|---|---|---|---|
| > 0.95 | 无 | 0 | 0 | 5 | 0 |
| > 0.95 | 1 个 | 1 | 0 | 4 | 0.333 |
| > 0.90 | 2 个 | 2 | 0 | 3 | 0.571 |
| > 0.85 | +1 负例 | 2 | 1 | 3 | 0.500 |
| > 0.80 | +1 正例 | 3 | 1 | 2 | 0.667 |
| > 0.60 | +1 负例 | 3 | 2 | 2 | 0.600 |
| > 0.40 | +1 正例 | 4 | 2 | 1 | 0.727 |
| > 0.30 | +1 正例 | 5 | 2 | 0 | 0.833 ← 这里最高 |
| > 0.20 | +1 负例 | 5 | 3 | 0 | 0.769 |
| > 0.10 | +1 负例 | 5 | 4 | 0 | 0.714 |

所以最后tau就是0.833。注意validation 被用了两次：既做早停监控，又用来选阈值，阈值指标存在轻微乐观偏差，应说明这是"validation-tuned"而非"test-tuned"。

**4.** test预测打分：按照上一步validation的阈值tau 直接进行切割来计算F1等指标。test 不重新训练，validation 和 test 共用同一个已训练模型，test 阶段只做"打分 + 用 validation 定的阈值切集合"。

模型须能对新记录编码和推理；ID、已有关系、索引或图结构的使用方式必须在协议中写明。TF-IDF/SVD 只在 train 拟合；训练图只含 train gold 边，validation/test gold 边和测试标签派生边不得入图。每次运行前后检查：ID/行号/索引未作特征、同一实体未跨 split、train/validation/test gold 无交集、预处理符合 inductive/transductive 声明，并保存数据版本、配置、split manifest、候选池版本、外源快照哈希与阈值配置。 预测主要计算三个指标Precision	Recall	F1。全量汇总写入 `full_candidate_comparison.csv`

#### 3.3.8 命令七产生的正式结果文件如何被使用

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

### 3.4 结果资产和复现顺序

按 §3.3 的命令一至七依次执行；结果、manifest、query 集合和审计文件必须与 `rho`、split seed、数据版本和候选库协议一同保存。

## 4 实验一：完整候选库集合评估

### 4.1 设置

以下结果来自 A 任务完整候选库穷举评估，覆盖每个测试 query 的全部 3,260 个房交候选，而不是有限构造负例。测试集为 432 个已映射正例 query，共 1,408,320 个 query-candidate pair；另外 5,899 个未映射 query 保持 `unknown` 并排除。映射完整性假设下，未列入现有 mapping 的候选暂按负例计，因此这些指标是条件性评估，不能当作已独立确认的负例结论。

- 训练资产：`code/training_assets_full_v4`
- 完整候选库结果：`code/full_library_results_disk_v4/full_candidate_comparison.csv`
- 名称遮蔽比例：`rho ∈ {0, 0.3, 0.6, 1.0}`；实体级确定性遮蔽，seed=42
- split：gold 图连通分量划分，seed=13；validation 433 个正例 query，test 432 个正例 query
- 各模型阈值仅依据 validation 完整候选集选择
- POI / Full Model 当前采用相同特征配置；`E1 remove admin` 尚未形成独立有效消融

名称遮蔽作用于训练、validation 和 test 的名称成对特征。该完整候选库实验仍是 `fixed_pool` 排序/集合输出评估，不等于名称遮蔽后同步重新生成名称召回索引的 `end_to_end` 实验。特别是 `rho=1.0` 的精确匹配基线会对每个候选给出相同的零分，validation 选出的阈值因此可能输出全部候选，不能把其 100% recall 解读为有区分能力。

### 4.2 主对比（全候选集合评估）

本节是**正式的全候选库实体解析主对比**：对每个测试 query 逐一评分全部 3,260 个房交 candidate，再按 validation 阈值输出一个候选集合。负例是该 query 的完整候选库中未被 gold mapping 标注的 candidate；因此这里评估的是“一个 query 最终返回哪些 candidate”的集合质量，而不是只在预先抽取的少量 pair 上做二分类。

本节报告 4 个名称遮蔽比例 `rho`，每格为 Precision / Recall / F1（%），括号内是 pair-level TP / FP / FN。宏平均 F1 单独报告，用于体现 query 间集合质量。

本节是固定 3,260 候选的集合输出评估；实验二（§5）的有限负例成对分类口径不同，两表不可合并或横向比较。

| 方法 | rho=0 | rho=0.3 | rho=0.6 | rho=1.0 |
|---|---:|---:|---:|---:|
| 主字段精确匹配 | 91.38 / 99.13 / 95.10 (456/43/4) | 88.66 / 47.61 / 61.95 (219/28/241) | 84.15 / 15.00 / 25.46 (69/13/391) | 0.03 / 100.00 / 0.07 (460/1,407,860/0) |
| TF-IDF-like Cosine | 91.38 / 99.13 / 95.10 (456/43/4) | 88.66 / 47.61 / 61.95 (219/28/241) | 84.15 / 15.00 / 25.46 (69/13/391) | 0.03 / 100.00 / 0.07 (460/1,407,860/0) |
| LightGBM Text/Structure | 94.59 / 98.91 / 96.71 (455/26/5) | 92.70 / 46.96 / 62.34 (216/17/244) | 71.43 / 17.39 / 27.97 (80/32/380) | 4.13 / 91.09 / 7.90 (419/9,727/41) |
| LightGBM + POI | 92.74 / 100.00 / 96.23 (460/36/0) | 94.12 / 66.09 / 77.65 (304/19/156) | 95.63 / 47.61 / 63.57 (219/10/241) | 98.08 / 33.26 / 49.68 (153/3/307) |
| Full Model | 92.74 / 100.00 / 96.23 (460/36/0) | 94.12 / 66.09 / 77.65 (304/19/156) | 95.63 / 47.61 / 63.57 (219/10/241) | 98.08 / 33.26 / 49.68 (153/3/307) |

| 方法 | rho=0 宏平均 F1 | rho=0.3 宏平均 F1 | rho=0.6 宏平均 F1 | rho=1.0 宏平均 F1 |
|---|---:|---:|---:|---:|
| 主字段精确匹配 / TF-IDF-like Cosine | 96.56% | 47.21% | 15.34% | 0.07% |
| LightGBM Text/Structure | 97.64% | 47.30% | 16.94% | 14.03% |
| LightGBM + POI / Full Model | 97.95% | 66.24% | 48.41% | 33.83% |

### 4.3 消融

| 消融设置 | rho=0 P/R/F1 | rho=0.3 P/R/F1 | rho=0.6 P/R/F1 | rho=1.0 P/R/F1 |
|---|---:|---:|---:|---:|
| Full Model | 92.74 / 100.00 / 96.23 | 94.12 / 66.09 / 77.65 | 95.63 / 47.61 / 63.57 | 98.08 / 33.26 / 49.68 |
| E1 remove admin | 未运行：当前特征接口未隔离行政中心证据 | 未运行 | 未运行 | 未运行 |
| E2 remove POI | 94.59 / 98.91 / 96.71 | 92.70 / 46.96 / 62.34 | 71.43 / 17.39 / 27.97 | 4.13 / 91.09 / 7.90 |
| E4b 全特征关闭 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 |

E2 在 rho=0.6 下相较 Full Model 的 Recall 低 30.22 个百分点、F1 低 35.60 个百分点；rho=1.0 时差距扩大到 Recall 低 55.78 个百分点、F1 低 41.78 个百分点。rho=1.0 时 Full Model precision 98.08%、F1 49.68%，而 Text/Structure F1 为 7.90%。Full Model 在高遮蔽档呈“高精确率、低召回”形态（rho=1.0 的误拒率 65.05%），说明当前全局单一阈值在名称不可用时偏保守。E4b 这一行不能作为“结构特征能力”的结论：`E4b 全特征关闭` 同时关闭 POI、行政与文本三档开关，14 维特征全部为 0，模型退化为常数并输出全部候选（P 0.03% / R 100.00%），因此其 F1 0.07% 只反映退化行为。上述结果使用 validation 阈值，需同时看 precision、recall、macro F1 和 false-reject，不能只看单一指标。

### 4.4 输出核验与限制

已核对：28 个 comparison 组合（4 个 rho × 7 个方法）；每个 query-set 文件均有 432 个唯一 query；各行 `prediction_count` / `gold_count` 与 JSON ID 列表长度一致；每个 rho 的 pair 混淆矩阵总数均为 432 × 3,260；预测列表无重复，且预测与 gold candidate ID 均属于标准化后的 3,260 条候选记录。

- `unknown` query 未作为负例，且本轮没有独立确认的 `confirmed_empty`，因此不报告严格拒识率或业务特异度。
- 非 mapping 候选按负例计仅在当前 mapping 完整的假设下成立；需人工复核抽样 FP/FN 后再作业务结论。
- `rho=0` 指不遮蔽名称；其余 rho 在各自训练和 validation 数据中也按固定实体哈希规则遮蔽。
- 固定候选库实验未改变候选召回，所以不能替代 `end_to_end` 名称遮蔽召回实验。
- A 查询侧没有独立地址字段；`Full Model` 与 `LightGBM + POI` 的特征配置当前相同。

## 5 实验二：有限负例成对分类诊断

### 5.1 设置

本节记录当前 A 任务在主字段名称遮蔽协议下的成对分类实验结果。结果来自：

- 训练资产：`code/training_assets_full_v4`
- 主对比结果：`code/experiment_results_masked/main_comparison.csv`
- 消融结果：`code/experiment_results_masked/ablation.csv`
- 遮蔽比例：`rho = 0.6`
- 遮蔽随机种子：`42`
- 评估 split：实体簇 connected component 划分，seed=13
- 测试集：1,835 个 pair，其中 460 个正例、1,375 个构造负例
- 阈值：仅在 validation 集上按 pair-level F1 选择，测试集不参与调参

本轮是**名称遮蔽下的成对分类诊断实验**。它用于检验模型对名称捷径的依赖，以及 POI 特征的增量作用；不能直接解释为完整候选库上的最终实体解析结果，也不包含严格拒识指标。

名称遮蔽只作用于名称相关成对特征：`name_exact` 和 `name_similarity`。地址、行政、结构和 POI 特征按当前训练资产保留。当前 A 查询侧没有独立地址字段，因此 `address_similarity` 不能解释为完整的双侧地址证据。

### 5.2 主对比

本节是**名称遮蔽下的成对分类诊断主对比**，不是完整候选库上的最终实体解析主对比。模型只对预先构造的 1,835 个 query-candidate pair 做二分类：其中 460 个正例、1,375 个困难负例，然后报告 pair-level Precision / Recall / F1 和混淆矩阵。

本节是 1,835 个 pair 上的成对二分类；实验一（§4）是完整候选库集合输出，两表不可合并或横向比较。

| 方法 | 类型 | Precision | Recall | F1 | TP | FP | FN | TN |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 主字段精确匹配 | 规则 | 100.00% | 40.43% | 57.59% | 186 | 0 | 274 | 1,375 |
| TF-IDF-like Cosine | 规则基线 | 99.47% | 41.09% | 58.15% | 189 | 1 | 271 | 1,374 |
| Text/Structure Rule | 规则基线 | 45.06% | 93.26% | 60.76% | 429 | 523 | 31 | 852 |
| Logistic Text/Structure | 逻辑回归 | 85.43% | 56.09% | 67.72% | 258 | 44 | 202 | 1,331 |
| LightGBM Text/Structure | LightGBM | 85.35% | 58.26% | 69.25% | 268 | 46 | 192 | 1,329 |
| LightGBM + POI | LightGBM | 88.96% | 89.35% | 89.15% | 411 | 51 | 49 | 1,324 |
| Full Model | LightGBM | 88.96% | 89.35% | 89.15% | 411 | 51 | 49 | 1,324 |

#### 结果解读

在 `rho=0.6` 的名称遮蔽下，名称精确匹配和 TF-IDF 基线的 Recall 降至约 40%（40.43% / 41.09%），说明自然数据中的高结果明显依赖名称信息。Text/Structure 规则通过放宽判定把 Recall 提到 93.26%，但 FP 达 523、Precision 仅 45.06%，F1 为 60.76%。LightGBM Text/Structure 把 Precision 提到 85.35%，F1 为 69.25%。加入可信 POI 后，Recall 提升到 89.35%、F1 提升到 89.15%，Precision 保持 88.96%。

因此，在当前遮蔽协议下，POI 对抗名称缺失具有明显增量效果：

- 相比 LightGBM Text/Structure，Full Model 的 Recall 提升 31.09 个百分点；
- F1 提升 19.90 个百分点；
- TP 从 268 增至 411、FN 从 192 降至 49；FP 从 46 微增至 51。

### 5.3 消融

| 消融设置 | 模型类型 | Precision | Recall | F1 | TP | FP | FN | TN |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Full Model LightGBM | LightGBM | 88.96% | 89.35% | 89.15% | 411 | 51 | 49 | 1,324 |
| E1 remove admin | LightGBM | 88.96% | 89.35% | 89.15% | 411 | 51 | 49 | 1,324 |
| E2 remove POI | LightGBM | 85.35% | 58.26% | 69.25% | 268 | 46 | 192 | 1,329 |
| E3 text structure only | LightGBM | 85.35% | 58.26% | 69.25% | 268 | 46 | 192 | 1,329 |
| E4a 结构+行政-only | LightGBM | 32.50% | 99.13% | 48.95% | 456 | 947 | 4 | 428 |

#### 消融解读

- 去除 POI 后，F1 从 89.15% 降至 69.25%，FN 从 49 增至 192，说明 POI 是名称遮蔽条件下的主要补充证据。
- 仅使用结构特征时 Recall 很高（99.13%），但 FP 增加到 947、Precision 降至 32.50%，说明结构字段只能提供宽松筛选，不能单独完成精确链接。
- 当前 E1 与 Full Model 数值相同，原因是当前成对特征资产尚未真正加入独立的行政中心距离特征。因此 E1 只能作为占位诊断，不能写成“去行政中心后的有效消融结论”。
- 当前 E2 与 E3 使用相同的特征白名单，后续若拆分行政、街道和其他结构特征，需要重新生成特征资产后再报告独立 E3。
- E4 的两种实现已分开命名：本节 **E4a 结构+行政-only** 保留 `area_match`、`street_match`、`coords_available`（`experiments.vector` 只清空文本与 POI 字段）；§4.3 **E4b 全特征关闭** 在 `full_library.record_features` 里同时关闭行政开关，14 维全为 0 并退化为常数模型。两者不可互相引用。
- 现有结果 CSV 与 query_sets 文件名生成于改名之前，`method` 列仍是旧名 `E4 structure-only`；对应关系为 **E4a = 成对级（本节）**、**E4b = 完整候选库（§4.3）**。

## 6 评估边界

1. 当前负例是按同一实体 split 构造的有限困难负例，不是每个 query 对完整候选库的集合预测。
2. `unknown` query 没有作为负例；当前没有足够的 `confirmed_empty` 样本，因此本表不报告严格拒识率、特异度或 TN-based 拒识指标。
3. 当前 query-level 指标是对测试候选集合进行汇总的集合指标，不等同于对全量业务 query 的完整 macro 指标。
4. 当前 A 查询侧没有独立地址字段，地址相关特征不能被解释为双侧完整地址匹配。
5. `Full Model` 与 `LightGBM + POI` 当前特征配置相同，因此结果相同；完整行政中心特征接入后需要重新生成 Full Model。
6. 当前遮蔽只清除成对名称特征。正式 `end_to_end` 主协议还应同步清除名称派生召回索引，并重新生成候选池；本表主要用于成对分类和名称捷径诊断。
7. 结果不得与未遮蔽自然集结果合并为一个总分。自然集、遮蔽集、provenance 和坐标可信度必须分层报告。

## 7 可复现命令

```text
py code/run_experiments.py \
  --data-dir code/training_assets_full_v4 \
  --output-dir code/experiment_results_masked \
  --mask-ratio 0.6 \
  --mask-seed 42
```

回归测试：16 项测试通过。

## 8 代码结构

| 模块 | 职责 |
|---|---|
| `code/*.py` | 入口脚本：`build_evaluation_assets`、`audit_geo_assets`、`build_entity_splits`、`build_pair_features`、`build_candidates`、`run_masked_candidate_sweep`、`run_pair_model_experiments`、`run_full_library_experiment`、`smoke_test` |
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
| `code/external/` | 外源资产重建：行政区划补全、区划表生成、复核清单、资产合并与命中率评估 |
| `tests/` | 16 项回归测试 |
