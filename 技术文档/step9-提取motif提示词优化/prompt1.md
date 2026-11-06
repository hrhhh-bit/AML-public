# 任务指令：阶段 3 知识库基准种子与 Handbook Motif 语义保真度专项纠偏与测试回归

## 一、 任务背景与核心目标

经过 P0 级 Human-in-the-Loop（HITL）因果审计，发现 `data/distilled_kb_v1.json`（及 `data/distilled_kb.json` 中对应的基准条目）存在早期手工编写残留的本体论缺陷与范畴混淆（主要表现为：节点角色与边动作错位、`Asset_Conversion` 缺少 `SWAP` 支撑、汇聚边操作不对称、元数据前置条件遗漏等）。
这些缺陷直接导致了下游大模型蒸馏时产生了严重的“Few-Shot 先验污染”。

**本任务目标**：
对既有 18 个基准 Motif（12 个 Initial Seeds + 6 个 Handbook Motifs）进行**外科手术式语义校准（Semantic Patching）**，同步适配修改受影响的测试断言，确保全量自动化测试套件（`pytest`）维持 **100% PASS（≥ 364 项全绿，0 失败）**，并重新生成哈希存证。

---

## 二、 核心架构公理与不可逾越红线（必须严格遵守）

1. **零微观噪声铁律**：严禁引入真实钱包地址（`0x...`）、代币符号（USDT/ETH 等）或微观数值；
2. **流量守恒硬门禁**：
   - 节点多出边（分流）：出边必须满足 $\sum \text{flow\_share} \approx 1.0 \pm 0.01$；
   - 节点单出边（`out_degree == 1`）：强制显式标为 $1.0$；
3. **跨账本物理动作闭环**：有向边跨越不同 Chain 时，操作类型必须且仅能为 **`BRIDGE`**；同链严禁标注为 `BRIDGE`；
4. **`Asset_Conversion` 实体契约**：定义为“资产形态突变中继节点”。**其入边或出边必须且仅能有一条是 `SWAP`**，严禁出现两端皆为 `TRANSFER` 的虚假转换节点；
5. **汇聚对称性契约**：多股资金汇聚进入 `Aggregator` 节点时，所有汇聚入边操作基必须统一规范为 **`MERGE`**。

---

## 三、 具体纠偏清单与因果校准规范（请代码 Agent 自主定位源码与数据）

请代码 Agent 通读 `data/distilled_kb_v1.json` 及 `data/distilled_kb.json`，定位并完成以下 9 个 Motif 的定向校准：

### 1. 种子库修正（6 项）

- **`Cross_Chain_Swap_Bridge`**：
  - _病灶_：`S -> AC` 为 Transfer，`AC -> I` 为 Swap，导致 AC 角色与动作倒置。
  - _校准_：采纳因果对齐方案：将 `AC` 的角色修正为 `Intermediate`（暂存原代币）；将 `I` 的角色修正为 `Asset_Conversion`（接收兑换出的稳定币）；或将 `S -> AC` 改为 `Swap`、`AC -> I` 改为 `Transfer`。
- **`DEX_Liquidity_Pool_Swap`**：
  - _病灶_：`S -> AC` 为 Transfer，`AC -> T` 为 Swap，动作时序倒置。
  - _校准_：边 1 (`S -> AC`) 操作改为 **`Swap`**（换币后打入转换节点 `AC`）；边 2 (`AC -> T`) 操作改为 **`Transfer`**（`AC` 将干净币转给 `T`）。
- **`Mixer_Anonymization_Split_Merge`**：
  - _病灶_：描述有 Swap 但全图无 Swap 边；命名滥用 Mixer。
  - _校准_：边 1 (`S -> AC`) 操作改为 **`Swap`**，激活 `Asset_Conversion` 角色；在 `tags` 中剔除 `"mixer"`，改为 `"layering"`。
- **`Single_Chain_Multi_Swap_Layering`**：
  - _病灶_：首跳转账尾跳换币，与描述中的“多次换币后最终转账出金”首尾颠倒。
  - _校准_：边 1 (`S -> AC1`) 改为 **`Swap`**；边 2 (`AC1 -> AC2`) 保持 **`Swap`**；边 3 (`AC2 -> T`) 改为 **`Transfer`**。
- **`Cross_Chain_Layered_Integration`**：
  - _病灶_：`AGG2` 的两条汇聚边不对称（一条 Merge，一条 Transfer）；元数据角色遗漏。
  - _校准_：边 `CC -> AGG2` 的操作改为 **`Merge`**；在 `preconditions.allowed_node_roles` 中补齐 `"Aggregator"` 和 `"Target"`。
- **`Multi_Split_Cross_Chain_Bridge`**：
  - _病灶_：支路 2 穿透直连 T 导致因果不对称；元数据角色遗漏。
  - _校准_：将 `CC2` 的目标链统一规范为 `Chain_B`，`CC2 -> T` 改为 **`Transfer`**（或保持三路严格对称的跨链落地规范）；在 `preconditions.allowed_node_roles` 补齐 `"Target"`。

### 2. Handbook 库修正（3 项）

- **`mixer_pooling_obfuscation`**：
  - _病灶_：末端节点标为 `Target` 却推荐后续跨链/换币，角色与状态转移冲突。
  - _校准_：将 `T1, T2` 的角色由 `Target` 修正为 **`Intermediate`**（符合混币后作为跳板继续离析的因果）；`preconditions.allowed_node_roles` 补入 `"Intermediate"`。
- **`motif_chain_hopping_bridge_evasion`**：
  - _病灶_：`AC` 标为 `Asset_Conversion`，但两端均为 `Transfer`，无 `SWAP`。
  - _校准_：落实研报代币变化事实，将边 1 (`S -> AC`) 改为 **`Swap`**（先换成支持跨链的资产再转账跨链）。
- **`otc_p2p_integration_merge`**：
  - _病灶_：尾部给 `T` 标注链上 `Swap`，混淆了链下 OTC 承兑；`AG` 作为中介却发起跨链。
  - _校准_：将 `AC` 改为 `Intermediate`（目标链接收中继）；最后一条边改为 **`Transfer`** 入 `T`（`T` 作为 OTC 承兑商链上存币地址，完成链上出金终止）；修正 `description` 明确 `AG` 为源链归集钱包。

---

## 四、 执行步骤与自治回归工作流

1. **静态审计与定位**：
   - 检索并确定受此批校准影响的 JSON 文件：`data/distilled_kb_v1.json`、`data/distilled_kb.json`，以及 `aml_rag/` 或 `tests/` 下可能包含 Hardcoded Seed 数据/断言的模块；
2. **精准数据修补（Patching）**：
   - 就地更新相关 JSON，保持 JSON 格式严格合法、缩进一致；
3. **单测套件审计与断言同步**：
   - 运行 `pytest`，排查因 Motif 边类型或角色改动引起的断言失败；
   - 对断言中硬编码旧字段的测试用例进行自洽性同步更新（严禁删除核心逻辑测试，只更新与语义纠偏一致的预期值）；
4. **全量回归验收（Hard Verification Gate）**：
   - 执行全量回归：`pytest -v`，必须实现 **100% PASS（0 failures, 0 errors）**，测试总数不得低于既有的 364 项；
   - 运行图公理校验脚本（如 Kahn 无环性校验、流量守恒校验、跨链 BRIDGE 校验），确保所有被改动 Motif 达成率 100%；
5. **状态存证与报告交付**：
   - 计算并打印修补后 `data/distilled_kb_v1.json` 和 `data/distilled_kb.json` 的 SHA-256 哈希值；
   - 输出简明的修补摘要大表与 `git diff` 关键片段。

【证据链查阅指引（权威事实来源）】：
本次校准的完整因果推导、研报原文对照及专家定性意见已完整归档至：
`技术文档\step9-人工审查motif\motif_semantic_audit_log.md`。
在对具体 Motif 进行 JSON 字段修补或断言调整时，必须以该文档中的审计诊断与 Patch 方案为唯一语义真理标准，严禁凭空揣测！

请代码 Agent 自主通读既有代码与测试，严禁机械喂饭，结论先行，以测试全绿与数据守恒为唯一交付标准！
