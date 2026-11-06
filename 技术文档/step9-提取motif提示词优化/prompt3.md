# 【任务指令】Task 3：实施 Prompt v2.1 宏观战役级契约重构、复杂度下界门禁与基准白板重置

## 一、 任务背景与核心技术根因

在初版 Prompt v2 的真机测试中，系统成功跑通全链路并激活了双阶段提取，但触发了严重的**“粒度坍塌与微观碎片化（Granularity Collapse）”**：

- **实证证据**：在长篇研报 `rep_slowmist_002` 中，模型抽出了 28 个 Motif，其中大量边数仅为 `1` 或 `2`（即单笔转账或简单两跳中继），导致单篇净增膨胀至 20 个；
- **根因研判**：
  1. 注意力脚手架（`evidence_chain`）列出了多条出金支路，模型将每条支路/每个交易所存款分别切碎成独立的微观碎片，未进行宏观聚合；
  2. 既有契约缺乏**拓扑复杂度下界（Minimum Cardinality Axiom）**约束，缺少过滤 trivial transfer 的程序守门员。

在 Stage-1 架构中，Motif 必须是**战役级宏观洗钱拓扑（Campaign-level Topology Skeletons）**，严禁将原子级交易片段当作 Motif 入库。

---

## 二、 架构红线与刚性约束

1. **复杂度下界公理（Cardinality Lower Bound）**：
   - **硬性红线**：单个合法的 AML Motif 其内部有向边数必须 **$\ge 3$**（即 `len(edges) >= 3`）；
   - **形式化拒识**：严禁将单笔转账（1 边）或简单两跳单线中继（2 边）作为独立 Motif；
2. **多支路宏观聚合铁律（Unified Parallel Dispersal/Aggregation Mandate）**：
   - 同一洗钱阶段内的多支路资金流向（如黑客将资金同时分散转移到 4 个不同交易所或跨链桥），**必须聚合为单个统一的 1-to-N 扇出分流 DAG（Unified Fan-out/Split Motif）**，绝对禁止按去向切碎成多个 1 边的碎片；
   - 同样，多源入账必须聚合为统一的 N-to-1 星型汇聚 DAG（Consolidation Motif）；
3. **预期产出密度常识**：
   - 单篇长研报在每个活跃阶段（Phase A / Phase B）通常仅产出 **1 个（至多 2 个高度正交的）战役级 Motif**，整篇研报产出通常为 **2~3 个**；
4. **测试与基线红线**：
   - 自动化测试回归基线必须保持 **$\ge 380$ passed（0 failed / 0 errors）**；
   - 生产知识库必须彻底重置为干净的 18 基标白板。

---

## 三、 工程实施模块与具体任务

请下游 Agent 自主进行代码审计与增量重构，按以下模块推进：

### 1. 契约重构：升级 Prompt v2 为 Prompt v2.1（`prompt_v2.py`）

- **注入复杂度与聚合契约条款**：
  在系统提示词与任务说明中增加专门的宏观聚合红线章节（`### MACRO CAMPAIGN TOPOLOGY MANDATE`）：
  - 明确规定：`MINIMUM EDGE COUNT: Each motif MUST have at least 3 edges (len(edges) >= 3). Isolated 1-edge transfers or 2-edge simple hops are STRICTLY FORBIDDEN.`
  - 明确规定：`PARALLEL FLOW UNIFICATION: If the hacker disperses funds to multiple destinations/exchanges, UNIFY them into a single 1-to-N dispersal DAG with flow_share split. Do NOT emit separate 1-edge motifs for each branch.`
  - 明确预期：`Density Expectation: Extract 1 (at most 2) overarching campaign motif per phase. Quality over quantity.`
- **负向反例增强**：
  在既有拒绝虚构中继反例的基础上，补充（或明确标示）拒绝单笔 1-2 边碎片的拒识印记：`[REJECTED: Micro-fragment / Trivial Transfer]`。

### 2. 代码级硬守门员：解析端下界过滤（`PromptV2Distiller`）

- 在解析模型返回的 JSON Payload 时（例如在 `parse_v2_payload` 或提取循环中）：
  - 增加对 `len(motif.edges) < 3` 的程序级过滤；
  - 若模型依然吐出了边数 $< 3$ 的微观碎片，直接在解析层丢弃（或记录到 `quarantine_log`），严禁流入后续的公理验证与同构去重池。

### 3. 白板基准重置（Reset KB to Calibrated Baseline）

- 为了彻底清除历史增量与旧版 22 个有缺陷 Motif 的干扰，将 `data/distilled_kb.json` 初始化重置为与 `data/distilled_kb_v1.json`（18 个校准基标）完全一致；
- 确保 `batch_distill.py` 中的 `enforce_baseline_freeze` 门禁能天然验证通过。

### 4. 离线装配导出更新（`--dump-prompts`）

- 重新运行离线装配指令，将更新后的 Prompt v2.1 重新导出至 `data/staged_prompts_v2/`；
- 确保导出的 Markdown 提示词中包含最新的宏观聚合与边数 $\ge 3$ 约束。

---

## 四、 验收量化指标与汇报要求

下游 Agent 完成开发后，必须在终端自检并汇报以下数据：

1. **单测回归基线**：
   - 运行全量 `pytest`，必须保持 **$\ge 380$ passed，0 failed, 0 errors**；
   - 若新增了针对 `edge_count < 3` 过滤的单测，用例数应相应递增；
2. **基线对齐校验**：
   - 证明 `data/distilled_kb.json` 的条目数已重置为 **18**，且与 `distilled_kb_v1.json` 哈希完全一致；
3. **离线装配抽验展示**：
   - 截取 `data/staged_prompts_v2/rep_slowmist_002_prompt.md` 中关于“宏观聚合”与“边数 $\ge 3$”的最新提示词片段；
4. **交付成果清单**：
   - 修改文件列表与核心 `git diff` 片段。
