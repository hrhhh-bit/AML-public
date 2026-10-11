# 面向跨链反洗钱行为拓扑生成的 RAG 知识库构架与可移植学术工作映射研究

在加密货币与去中心化金融（DeFi）生态迅速扩展的背景下，跨链洗钱行为展现出极高的隐蔽性、动态演化性与拓扑复杂性。传统的基于固定规则或端到端图神经网络（GNN）的检测机制，往往受限于真实洗钱标签数据的极端稀缺性，且难以有效捕获跨链“剥皮链”（Peeling Chain）、“链跳跃”（Chain Hopping）、跨链桥混淆以及多路拆分与聚合等宏观行为模式。针对“高层认知推理与底层数据分布”分层解耦的两阶段合成数据生成框架，阶段一的核心目标是利用 RAG 增强的 LLM Agent 与轻量级状态环境交互，规划并生成宏观、语义合规且满足有向无环图（DAG）约束的抽象洗钱行为拓扑图（Behavioral Graph, $G_b$）。

本研究重点针对模块一（洗钱拓扑先验知识库与 RAG 系统设计）进行系统性探讨。知识库并非简单存储具体的链上交易哈希或绝对数值，而是需要将复杂的洗钱研报与历史案件解构为高度抽象的拓扑结构、子图模式、跨链跳跃逻辑及触发前置条件。本文对近期图检索增强生成（GraphRAG）、领域逻辑集成、图智能体规划及网络安全攻击图等领域的顶尖学术工作进行深度解析，提出可移植的知识库 Schema 架构、双轨检索算法及 Agent 交互范式，并制定消融实验验证方案。

## 理论范式与拓扑先验知识库的抽象建模

洗钱拓扑先验知识库（$K_{AML}$）在生成框架中充当 Agent 的“认知先验集”。由于阶段一仅关注行为拓扑逻辑（节点类型、链属性、DAG 层级步长及抽象资金操作），知识库的设计必须实现从“微观交易事实”到“宏观结构范式”的维度归约与信息蒸馏。

### 洗钱拓扑抽象的“三层本体 Schema”

为了让 LLM Agent 在决策过程中能够高效读取并理解图拓扑先验，知识库不能采用扁平的无结构文本或单纯的节点-边元组，而应构建层次化的图本体结构。借鉴法律与金融领域多粒度知识图谱建模范式，知识库应包含三个核心抽象层级：
知识库 Schema 层级表达对象与核心要素拓扑抽象维度对 Agent 决策的作用机制战术与规则层 (Tactic & Rule Layer)洗钱高层战略目标，如 Layering 阶段的资产混淆、Integration 阶段的多路资金归集。宏观阶段标识、前置依赖条件（Preconditions）、期望状态转移（Post-states）。提供高层动作指引，限定当前状态下的宏观洗钱阶段。拓扑子图层 (Motif & Subgraph Layer)具体的洗钱拓扑基元（Graph Motifs），如“剥皮链”、“多路分拆”与“跨链 Swap-Bridge”。抽象子图结构（节点角色、边操作类型），完全剥离微观金额、绝对时间戳与真实哈希。充当 Agent 的“策略模板”，提供局部连通子图的具体构建范例。关联约束层 (Meta-Path Layer)异构图元路径（Meta-paths）与图结构转移约束。节点角色的合法转移概率、步长界限 $[L_{min}, L_{max}]$ 与分支度上限 $d_{max}$。约束 Agent 的连线动作，防止生成违背金融逻辑或违反 DAG 属性的随机拓扑。

这种多层级的知识表达能够有效消除真实研报中冗余的具体哈希、时间戳与金额数值，提取出纯粹的“拓扑不变性”（Topological Invariants）。

### 拓扑先验对 LLM Agent 决策的催化机制

在缺乏 RAG 先验的冷启动状态下，LLM Agent 倾向于依赖通用大语言模型的幻觉或简单的树状展开生成拓扑，导致生成的拓扑缺乏真实金融犯罪的“对抗性逻辑”。通过注入拓扑先验，RAG 模块在多轮决策循环中起到三重催化作用：

1. 搜索空间剪枝： 在状态 $State_t$ 下，根据当前节点的角色与活跃分支度，匹配最相似的洗钱子图模板，限定 Action 的候选空间 $Action_t \in \{\text{Transfer, Swap, Bridge, Split, Merge}\}$。
2. 跨链语义桥接： 解决 Agent 在多链环境下的语义断层问题，提供“特定链种-资产类型-混淆工具”的拓扑转化模式。
3. 动态深度诱导： 通过先验中的多跳依赖链，引导 Agent 执行长距离、多层级的混淆路径，避免生成过早截断的平庸图结构。

## 可移植 SOTA 论文与技术构架对照分析

针对模块一的研发需求，本研究从反洗钱与加密货币异常检测、结构化图检索（GraphRAG）以及网络安全攻击图与智能体规划三个技术维度，挑选了具有代表性的 SOTA 学术工作进行系统梳理，分析其核心机制并评估向本项目 Stage 1 $G_b$ 生成架构的可移植性。

### 代表性研究工作解析

1. RDLI (Na et al., 2026): 该工作针对极度标签稀缺场景（0.01%），提出了结合专家知识图谱与检索增强上下文（RGC）的逻辑感知表征学习范式。其核心在于利用大语言模型（LLM）将专家定义的洗钱类型学与异常规则转化为结构化的 Expert Knowledge Graph，并生成路径级解释。RDLI 利用 LLM 从无结构文本中抽取专家知识并构建高语义密度知识图谱的 Prompting 策略与模式，可直接移植用于模块一知识库的自动构建与范式提炼。
2. Agentic AML Typology Classification (Grzeczkowicz et al., 2026): 探讨了基于 LLM Agent 的反洗钱调查与洗钱类型学（Typology）分类范式。该工作提供了标准化洗钱 Typology 的分类体系与 Agent 启发式推理流程，有助于本项目明确 $G_b$ 生成过程中的场景定义与动作空间划分。
3. Bit-CHetG (ResearchGate, 2024): 提出了基于异构图子图对比学习的比特币洗钱团伙检测方法，引入预定义的元路径（如 TAT、ATA）构建同质子图并提取拓扑表征。Bit-CHetG 对 Address-Transaction 异构拓扑的元路径定义，可直接映射为本项目模块一知识库中抽象节点角色的连接约束。
4. SubgraphRAG / SG-RAG (Li et al., 2024; MDPI, 2025): 提出了基于平行三元组打分与方向距离编码（Directional Distance Encoding, DDE）的高效子图检索框架，并引入“三元组合并与排序”（Merging and Ordering Triplets, MOT）机制以减少结构冗余。MOT 机制能够在不破坏拓扑连通性的前提下，将检索出的复杂洗钱子图压缩为适合 LLM 上下文窗口的精简三元组序列，非常适合作为模块一的图检索器。
5. LegalGraphRAG (arXiv, 2026): 构建了包含 Ontology、Fact 和 Rule 三层结构的领域知识图谱，解决了平铺检索（Flat Retrieval）导致的高频事实细节覆盖抽象法理原则的“粒度偏置”问题。法理与案情的分层设计与本项目“抽象洗钱规则-拓扑模式-状态条件”的三层需求高度契合，其多粒度检索机制具有极高移植价值。
6. PentestAgent & PENTEST-AI (2025/2026): 在网络安全领域，将 MITRE ATT&CK 攻击图谱与 RAG 结合，驱动 Agent 在渗透测试中根据目标环境状态规划高层攻击路径。网络攻击中的 TTP（战术、技术、过程）与状态转移映射，与洗钱中的“分拆-跨链-混淆-聚合”战术完全对等，其基于攻击图的状态机 Agent 交互设计可直接迁移至阶段一的环境交互循环。
7. LAGA (Large Language and Graph Agent, 2025): 提出了包含 Detection、Planning、Action、Evaluation 的闭环多智能体系统，用于文本属性图（TAG）的质量优化与修剪。其 Planning Agent 与 Action Agent 的闭环协作机制，可用于本项目阶段一中 Agent 与 Hard Verifier / LLM Critic 的协同优化。
8. LLM Subgraph Reasoning for AML (2025): 探索了提取实体周围的 $k$-hop 局部子图并将其序列化为结构化文本，通过 Few-Shot 提示 LLM 进行洗钱推理的机制。这验证了将局部拓扑序列化输入 LLM 进行图结构推理的可行性。

### 学术工作可移植性与技术特征对比

论文/工作名称核心领域图表征与抽象层级检索/图处理机制移植至模块一 Gb​ 生成的可行性与适配切入点RDLI[cite: 4, 21]加密货币异常检测专家逻辑图谱 + 路径级子图检索增强上下文 (RGC) + 规则 Latent 嵌入极高：移植其 LLM 驱动的文本到知识图谱抽取范式，用于构建 $K_{AML}$。SubgraphRAG / SG-RAG[cite: 12, 20]通用 GraphRAG节点/边/子图三元组DDE 打分 + 子图合并与排序 (MOT)极高：作为 RAG 模块检索引擎，抽取并压缩 $G_b$ 子图拓扑送入 Prompt。LegalGraphRAG[cite: 7]法律智能推理三层本体 (Ontology-Fact-Rule)多粒度层次化检索高：移植其分层 Schema，解决“微观交易动作”与“宏观洗钱战术”的粒度偏置。Bit-CHetG[cite: 3]比特币洗钱检测异构图元路径 (TAT/ATA)拓扑对比学习 + 子图嵌入中高：吸收其异构元路径定义，转化为 $G_b$ 中角色演化的转移概率约束。PentestAgent / PENTEST-AI[cite: 26, 27]网络渗透攻击图战术-技术-路径攻击图 (MITRE)状态感知 RAG + 战术决策链高（跨域）：迁移其“战术-状态-动作”映射图结构，设计洗钱 Agent 的规划机制。LAGA[cite: 16, 17]图质量优化文本属性图 (TAG)多智能体闭环规划与修剪中高：迁移其 Evaluation-Action 闭环，优化生成拓扑与 Hard Verifier 的交互。Agentic AML Investigation[cite: 22, 23]金金融合规分类文本-类型学语义映射Agent 启发式推理 + 案例匹配中：提供洗钱类型学（Typology）元数据标准与 LLM 评估 Baseline。LLM Subgraph AML[cite: 5]金融风险推理$k$-hop 局部子图序列化Few-shot 在线上下文推理高：移植其子图序列化 Prompting 格式，实现拓扑状态的自然语言/JSON 编码。

## 洗钱拓扑先验知识库（Module 1）的核心架构设计

综合上述学术工作的优势，针对本项目阶段一的具体需求，模块一（洗钱拓扑先验知识库与 RAG 系统）的整体架构包含三大部分：知识抽取与蒸馏管线、双轨检索引擎、以及 Agent 上下文集成接口。

### 知识抽取与蒸馏管线（Distillation Pipeline）

知识库的原生数据源包含非结构化的安全研报（如 Chainalysis、Elliptic、FBI 报告）及历史链上攻击/洗钱案例。构建管线分为三个步骤：

1. 实体与关系解耦提取： 借鉴 RDLI 的 LLM 结构化标注方法，利用高能力大语言模型解析研报文本，忽略具体的真实地址（如 0x7a2...）、特定时间点与绝对金额，仅提取角色语义（如 Mixer_Deposit、Bridge_Contract）与操作类型。
2. 拓扑基元归一化： 将抽取出的局部逻辑转化为符合项目 JSON 规范的规范化子图 $g_{motif} = (V_{abstract}, E_{abstract})$。
3. 先验元数据绑定： 为每个拓扑基元附加元数据，包括触发前置条件（如 Current_Chain == Chain_A 且 Active_Branches > 3）、推荐后续动作概率以及风险等级。

```JSON
{
  "motif_id": "MOTIF_CROSS_CHAIN_PEELING_01",
  "pattern_type": "Chain_Hopping_And_Layering",
  "preconditions": {
    "min_level": 2,
    "source_node_type": "Intermediate",
    "required_environment": "Multi_Chain"
  },
  "topology_structure": {
    "nodes": [
      {"temp_id": "N1", "role": "Intermediate", "chain": "Chain_A"},
      {"temp_id": "N2", "role": "Asset_Conversion", "chain": "Chain_A"},
      {"temp_id": "N3", "role": "Cross_Chain", "chain": "Chain_B"}
    ],
    "edges": [
      {"source": "N1", "target": "N2", "operation": "Swap"},
      {"source": "N2", "target": "N3", "operation": "Bridge"}
    ]
  },
  "post_state_effect": {
    "branch_increment": 1,
    "chain_transition": true
  }
}
```

### 结构与语义双轨检索机制（Dual-Track Retrieval）

传统的 RAG 多依赖单纯的文本向量相似度（Semantic Similarity），在处理图拓扑时容易丢失关键的结构依赖与方向性。为此，模块一引入“语义-拓扑双轨检索”：

1. 语义轨（Semantic Track）： 将当前 Agent 的高层战术目标（如 “资产跨链混淆与多路拆分”）与局部状态描述转化为 Embedding，在 Vector Store 中进行初步 Top-$K$ 粗筛。
2. 结构轨（Structural Track）： 借鉴 SubgraphRAG 中的 Directional Distance Encoding (DDE) 与 PPA-GNN 中的 Meta-Path 渗透机制，计算当前局部图 $State_t$ 的拓扑同构度与路径匹配得分：
   $$\text{Score}(g_{motif} \vert{} State_t) = \alpha \cdot \cos(\mathbf{e}_{context}, \mathbf{e}_{motif}) + (1-\alpha) \cdot \text{Sim}_{topo}(State_t, g_{motif}^{pre})$$

其中 $\text{Sim}_{topo}$ 衡量局部状态 $State_t$ 的 DAG 边界与基元前置条件的结构重合度。3. 三元组合并与排序（MOT 模块移植）： 借鉴 SG-RAG MOT 的思想，将检索出的多个候选子图进行层次化合并，消除重叠边与冗余节点，并按 DAG 执行顺序重排，生成低冗余的 Prompt 上下文。

### Agent 交互与状态机整合

在阶段一的多轮决策循环中，RAG 系统与 Agent 及 Environment 的交互遵循严格的阶段流转流程，如下表所示：

交互阶段执行主体关键输入核心处理逻辑阶段输出1. 状态感知Environment / Agent当前局部 DAG导出当前状态 $State_t$ 的 JSON 描述（已执行层级 $L$、当前链、活跃节点等）。$State_t$ 状态向量2. 先验检索RAG 检索引擎$State_t$ + 战术目标执行语义-结构双轨匹配，并通过 MOT 压缩检索到的 $g_{motif}$。拓扑先验 Prompt3. 策略动作输出LLM Agent状态 + 检索先验在候选空间中选择宏观拓扑动作 $Action_t \in \{\text{Transfer, Swap, Bridge, Split, Merge}\}$。动作 $Action_t$4. 环境转移Environment 状态机$Action*t$ + $State_t$执行转移函数，增量构建 DAG 节点与边，更新图结构。增量图 $State*{t+1}$5. 双重约束过滤Hard Verifier & LLM Critic$State\_{t+1}$Hard Verifier 检查 DAG 无环性、步长与度上限；通过后交由 LLM Critic 评判软语义真实性。校验通过/重试指令

## 消融实验设计与评估体系

为了在后续研究中严谨验证 RAG 知识库对高层认知推理的提升作用，设计了系统化的消融实验（Ablation Studies）与多维度评估指标。

### 对比 Baseline 配置

消融实验包含以下四个组别，以精确隔离 RAG 模块及其不同组件的贡献：

1. 纯规则基线（Rule-based Baseline）： 使用预定义的硬编码转移概率矩阵与模板树生成 $G_b$，无 LLM 参与。
2. 无 RAG 的 Agent（Vanilla Agent）： 仅向 LLM Agent 提供全局 Scenario（金额、链、资产）与动作定义，依赖 LLM 内部参数化知识进行多轮拓扑规划。
3. 扁平 RAG 增强 Agent（Flat-RAG Agent）： 仅使用传统的文本向量数据库（将研报切块），通过语义相似度检索纯文本描述注入 Prompt。
4. 本案 GraphRAG 增强 Agent（Proposed Struct-RAG Agent）： 使用基于三层本体 Schema、双轨检索及 MOT 子图压缩的结构化拓扑知识库。

### 评估指标体系

评估包含硬性结构指标（Structural Validity）与软性语义指标（Semantic Realism）：

评估维度具体指标测量方法与公式预期 RAG 收益效果硬规则合规性DAG 无环率 (DAG Pass Rate)$\frac{N_{valid\_DAG}}{N_{total}}$，检测是否存在非法回溯边。显著降低违例重试次数，提高生成效率。硬规则合规性步长与度约束覆盖率检查步长 $L \in [L_{min}, L_{max}]$ 与分支度 $d \le d_{max}$ 的比例。确保生成的图处于可控粒度内。拓扑丰富度图同构多样性 (Graph Novelty)计算生成的 $G_b$ 与训练/知识库图之间的 Weisfeiler-Lehman (WL) 树核相似度。避免 Vanilla Agent 容易产生的模式坍缩（Mode Collapse）。拓扑丰富度拓扑熵 (Topological Entropy)评估节点角色分布与边操作类型的香农熵 $H(V_{type}), H(E_{op})$。增加跨链跳跃与混合操作的合理多样性。语义真实性洗钱模式匹配度 (Typology Match)基于专家规则/LLM Critic 识别生成的 $G_b$ 中包含典型洗钱 Motifs（如 Peeling Chain）的数量。本案方法应显著高于 Vanilla 与 Flat-RAG 组。生成效率收敛步数与 Token 开销平均生成一张有效 $G_b$ 所需的交互轮数与 Token 消耗。通过 MOT 压缩大幅降低 Token 消耗并提升一次成功率。

## 结论与工程落地路线图

本研究通过对 RDLI、SubgraphRAG、LegalGraphRAG 及网络攻击图智能体 等前沿工作的交叉比对分析，明确了跨链反洗钱行为拓扑生成框架阶段一中模块一（洗钱拓扑先验知识库）的构建路径。研究表明，将真实链上/链下情报去伪存真，抽象为包含战术层、子图层与约束层的三层本体 Schema，并结合“语义-结构双轨检索”与 MOT 子图压缩机制，能够有效解决 LLM Agent 在生成洗钱拓扑时的冷启动与模式单一问题，为阶段二的条件图扩散模型提供高质量、符合金融逻辑的条件图输入 $G_b$。

### 工程落地实施路线图

1. 第一阶段：知识库 Schema 实例化与数据蒸馏
   参照 RDLI 的 LLM 标注范式，编写专业抽取 Prompt，解析 Elliptic、Chainalysis 公开研报及典型黑客跨链洗钱案例。建立包含至少 50 种标准洗钱拓扑基元（Motifs）的初始知识库 $K_{AML}$，覆盖 Chain Hopping, Peeling Chain, Multi-Split-Merge 等经典模式。
2. 第二阶段：双轨检索与 MOT 引擎开发
   基于图数据库/内存图结构搭建拓扑存储，实现 Dense Vector + DDE 拓扑打分的双轨检索器。集成 SubgraphRAG 的 MOT 算法，实现候选子图的无损文本化序列压缩。
3. 第三阶段：Agent 交互闭环与消融验证
   将 RAG 模块接入轻量级 Environment 与 Agent 决策循环，配置 Hard Verifier。运行四组消融对比实验，采集 DAG Pass Rate、WL 拓扑多样性及 Typology Match 评分，完成实验验证报告。
