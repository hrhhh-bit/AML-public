# 【任务指令】Task 2（无 API Key 离线重构版）：实施 Prompt v2 重构、资金链注意力脚手架对接与提示词离线装配

## 一、 任务背景与执行环境约束

由于当前执行环境中**未配置 LLM API Key**，本任务严格执行**“离线工程重构 + Mock 校验 + 提示词物理装配”**的工作范式。

你**不需要**也**严禁**发起任何在线 LLM API 网络调用。你的核心任务是：

1. 完成 **Prompt v2** 代码重构（实体接地闭包、Inflow/Outflow 双阶段契约、负向反例、3 个校准金标 Few-Shot）；
2. 修改批量调度流水线，从 `data/raw_reports/eligibility_audit.json` 读取资金链遥测线索并作为注意力脚手架动态注入；
3. 更新/增强解析与公理验证器（支持 Phase A/B 槽位展平与 `grounded_chains` 边界校验）；
4. 提供 **`--dump-prompts` / `--dry-run`** 功能，将 14 篇黄金研报最终装配出的 Prompt v2 文本完整导出到指定离线目录，供研究者后续挂载密钥自行提取；
5. 编写/更新 Mock 单测，确保全量自动化测试持续保持 **$\ge 364$ 项全绿通过**。

---

## 二、 五大顶层架构红线与公理约束

1. **零微观噪声铁律**：Prompt 输出契约与拓扑抽象中严禁包含真实/伪造地址（`0x...` / `bc1...` / `T...`）、具体代币符号或 Gas 费用；
2. **因果实体封闭性（Entity Grounding Invariant）**：
   - 输出契约中必须包含 `grounded_chains: list[str]`；
   - 拓扑中所有节点的 `chain` 映射代号数量，**严禁超过 `grounded_chains` 实际声明的实体链数量**，彻底杜绝虚构过渡中继；
3. **两阶段显式分槽（Two-Phase Contract）**：
   - 契约必须显式区分 `phase_a_inflow_motifs`（Fan-in/归集/首跳）与 `phase_b_outflow_motifs`（Fan-out/离析/DEX闪兑/OTC变现）；
4. **注意力脚手架“双轨注入”**：
   - `eligibility_audit.json` 中的 `evidence_chain` 与 `hops_detected` 仅作为引导注意力的辅助锚点（Signpost），正文全文依然是唯一真理源；
5. **资产只读审计**：
   - `data/raw_reports/` 下的文件及 `SHA256SUMS` 保持绝对只读。

---

## 三、 工程实施模块与具体任务

请下游 Agent 自主进行代码审计（检查 `scripts/batch_distill.py`、`src/aml_rag/` 等对应模块），完成以下改造：

### 1. 契约重构：升级 Prompt v2 模板（离线静态定义）

- 在提示词定义模块中实现 Prompt v2：
  - **Schema 约束**：要求输出 JSON 包含 `grounded_chains`、`phase_a_inflow_motifs`、`phase_b_outflow_motifs`；
  - **反中继负向反例**：植入直穿归集 vs 凭空捏造 `CC_A/B` 中继的对比反例，并打上 `[REJECTED: Hallucinated Intermediate Relay Chain/Node]` 拒识印记；
  - **正向金标 Few-Shot**：从刚刚校准完毕的 18 个金标库中，提取 3 个正交 Motif 作为正例示范（单链多层 Peeling 分流、标准跨链 Swap-Bridge、多链汇聚与 OTC 变现）。

### 2. 调度器对接：双轨资金链注意力脚手架注入

- 在批量蒸馏调度脚本（如 `scripts/batch_distill.py`）中：
  - 增加对 `data/raw_reports/eligibility_audit.json` 的自动索引逻辑；
  - 提取对应研报的 `evidence_chain` 和 `hops_detected`；
  - 将其格式化为 `=== VERIFIED FUND-FLOW TELEMETRY (ATTENTION ANCHOR) ===` 文本块，动态拼装入 Prompt 的上下文头部。

### 3. 解析器与公理守门员升级

- 针对两阶段 JSON Schema 编写或升级解析函数：
  - 校验 `len(grounded_chains)` 是否大于等于拓扑所使用的链种类数；
  - 展平 `phase_a_inflow_motifs` 与 `phase_b_outflow_motifs`，同时保留阶段标记元数据；
  - 将解析后的 Motif 对象接入既有的 Kahn DAG 无环、流量守恒（$\approx 1.0$）、跨链动作仅 `BRIDGE` 等五大公理守门员。

### 4. 离线导出功能（`--dump-prompts`）与一键执行命令封装

- 在调度脚本中提供离线导出模式（例如支持 `--dry-run --dump-dir data/staged_prompts_v2/`）：
  - 无需任何 LLM API Key，该模式能够遍历 14 篇黄金研报，读取全文并注入脚手架，将装配好的完整 Prompt v2 逐一输出为独立的 Markdown / 文本文件（如 `rep_slowmist_002_prompt.md`）；
- 在交付说明中，清晰注明后续研究者在本地配置 API Key 后，**用于一键发起真机提取的标准 CLI 命令**。

---

## 四、 验收量化指标与汇报要求

下游 Agent 完成开发后，必须在终端自检并汇报以下数据：

1. **单测回归基线**：
   - 运行全量测试套件 `pytest`，必须保持 **$\ge 364$ passed，0 failed, 0 errors**；
   - 必须包含针对两阶段输出解析、`grounded_chains` 边界校验的 Mock 单测（使用静态 Mock JSON 测试，无需联网）；
2. **离线装配产物验证**：
   - 成功执行离线 dump 指令，输出 14 篇黄金研报的完整装配提示词；
   - 重点展示 `rep_slowmist_002` 的装配片段：证明其已成功注入 `evidence_chain` 锚点、包含双阶段 Schema 约束与负向防幻觉反例；
3. **交付成果清单**：
   - 修改文件列表与核心 `git diff`；
   - 研究者后续启动真机提取的一键执行命令与环境变量规范。

【既有参考资产定位指引】
历史批量蒸馏脚本位于：scripts/batch_distill.py（请优先自主阅读该脚本既有的研报遍历、知识库入库和保存逻辑，在此基础上重构支持 --dump-prompts / --dry-run 及 Prompt v2 调用）；
研报元数据与资金链遥测台账位于：data/raw_reports/eligibility_audit.json；
研报正文目录位于：data/raw_reports/（由 manifest.csv 驱动，仅处理 14 篇黄金集）；
既有提示词与模型定义：请你优先阅读 src 相关模块，理解原有prompt的调用与解析逻辑，并在此基础上进行 v2 重构。
