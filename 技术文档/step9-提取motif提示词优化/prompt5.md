# 【任务指令】Task 5：实施 Prompt v2.2 去噪收敛、注意力脚手架微观剥离与非破坏性验证通道构建

## 一、 任务背景与核心技术目标

在前期的批量抽取实证中，通过对知识库（61 个 Motif）的深度图论审计发现，系统当前的主要矛盾是**“认知超载引发的局部因果/语义失真”**（如动作-角色错位、幽灵跳、同源出金支路的多尺度分形表达）。经系统架构委员会裁定，我们暂不引入复杂的外部图切片引擎，而是立即实施**纯提示词去噪与注意力脚手架净化（Prompt v2.2）**，展开低成本、可回滚的因果对比实验。

你的核心任务是：

1. **剥离微观诱导**：重构 `src/aml_rag/prompt_v2.py` 中的 `format_attention_anchor`，彻底剔除 `evidence_chain` 逐跳微观地址链路，仅保留宏观跳数数量级与语义标记；
2. **切除矛盾指令**：重构 `DISTILLATION_PROMPT_V2` 的宏观战役章节，剔除 `PARALLEL FLOW UNIFICATION`、`CONSOLIDATION UNIFICATION` 与 `DENSITY EXPECTATION` 散文切片指令，替换为高强度的 `CAUSAL FIDELITY`（因果保真）硬约束；
3. **构建非破坏性实验通道**：在 `scripts/batch_distill.py` 的 CLI 参数解析器（`main` argparse）中透传 `--kb-path` 与 `--backup-path`，确保后续真机验证可重定向至 Scratch 临时库，绝对绝缘生产知识库；
4. **刷新离线装配与回归单测**：更新离线装配提示词池（`data/staged_prompts_v2/`），确保全量自动化测试持续保持 **100% PASS（$\ge 385$ passed）**。

---

## 二、 顶层架构红线与公理约束

1. **零微观噪声与五大图公理不变**：
   - 维持 `MINIMUM EDGE COUNT >= 3`、Kahn DAG 无环性、$\Sigma_5$ 动作闭包、跨链仅限 `BRIDGE` 以及出边 `flow_share` 归一化（$\approx 1.0$）等公理校验 100% 运行；
2. **流向原型保真红线**：
   - 严禁修改 `classify_flow_prototype` 与 VF2 同构判定的任何逻辑；必须确保边上的无量纲 `flow_share` 保持为大模型的原生语义值（如 PEELING vs UNIFORM_SPLIT），绝不做人工抹平；
3. **生产真理源物理只读**：
   - 生产库 `data/distilled_kb.json` 与冻结基标 `data/distilled_kb_v1.json` 在开发与测试期间必须保持哈希不可变；
4. **自治排查与回归原则**：
   - 严禁因提示词变更破坏既有测试；若有单测硬编码断言了 `evidence_chain` 文本存在，必须做自洽的单测对齐调整。

---

## 三、 工程实施模块与具体任务

请下游 Agent 自主通读代码，按序完成以下四个模块的改造：

### 1. 净化注意力脚手架：剥离微观跳数链路（`src/aml_rag/prompt_v2.py`）

- 审计 `format_attention_anchor(...)` 函数：
  - **完全剔除**注入文本块中的 `evidence_chain: ...` 字段与其逻辑映射；
  - **保留** `hops_detected` 宏观跳数；
  - **保留** `flow_markers` 宏观语义关键词；
  - **修正早退守卫逻辑**：将原有的 `if not evidence and hops is None and not markers:` 调整为仅基于 `hops` 和 `markers` 的有效性判定（防止因 `evidence` 移除导致合法条目意外返回 `None`）。

### 2. 契约精简：收敛为因果保真（`src/aml_rag/prompt_v2.py`）

- 审计并修改 `DISTILLATION_PROMPT_V2`：
  - 定位 `## MACRO CAMPAIGN TOPOLOGY MANDATE` 章节；
  - **完全移除**：`PARALLEL FLOW UNIFICATION`、`CONSOLIDATION UNIFICATION` 以及 `DENSITY EXPECTATION` 三段散文式切片元指令；
  - **保留**：`MINIMUM EDGE COUNT: each motif MUST have at least 3 edges (len(edges) >= 3)...`；
  - **保留**：`CRITICAL: Do NOT mention concrete token symbols...`；
  - **新增注入**标准因果保真条款：
    ```text
    - CAUSAL FIDELITY: extract each actually-evidenced laundering stage as one
      motif that closes its causal loop (entry -> transformation -> exit).
      Never inflate hop counts, never insert ghost relay nodes or chains, and
      never split one logical flow into per-address fragments.
    ```
  - 提示词其他部分（`TWO-PHASE CONTRACT`、`BEHAVIOURAL NORMALISATION`、Few-shot、Negative examples）严禁做非必要变动。

### 3. 非破坏性实验通道支持（`scripts/batch_distill.py`）

- 审计 `scripts/batch_distill.py`：
  - 检查底层的 `run_pipeline(...)` 函数参数，确认其对自定义 `kb_path` 与 `backup_path` 的支持能力；
  - 在 `main()` 的 `argparse` 中，新增命令行参数暴露：
    - `--kb-path`：允许用户自定义输出知识库路径（默认仍为默认生产库路径）；
    - `--backup-path`：允许用户自定义基准冻结参考路径（默认仍为 `distilled_kb_v1.json`）；
  - 确保当用户指定非默认路径时，`enforce_baseline_freeze` 门禁与原子落盘只针对用户指定的 scratch 路径生效，完全不污染生产 `data/distilled_kb.json`。

### 4. 离线装配刷新与自动化单测回归

- **刷新离线 Prompt 池**：
  - 运行离线 dump 流程（如 `python scripts/batch_distill.py --dry-run --dump-dir data/staged_prompts_v2/`），将净化后的 Prompt v2.2 文本完整刷新至离线文件；
  - 自检 `data/staged_prompts_v2/rep_slowmist_002_prompt.md`，确认 `evidence_chain` 已彻底消失，`CAUSAL FIDELITY` 已正确生效；
- **全套单测回归**：
  - 运行全量 `pytest`；
  - 确保原有的两阶段解析、公理校验、Token Scrubber 脱敏单测全部通过；
  - 若有针对 `format_attention_anchor` 输出文本的既有单测（例如断言包含 `evidence_chain:`），在测试用例中同步更新断言，确保自动化套件达到 **100% PASS（$\ge 385$ passed, 0 failed）**。

---

## 四、 验收量化指标与汇报格式

下游 Agent 完成开发后，必须在终端自检并汇报以下成果：

1. **单测回归铁证**：
   - 输出 `pytest` 执行结果，展示通过用例总数（需 $\ge 385$ passed）及耗时；
2. **核心代码 Git Diff**：
   - 展示 `prompt_v2.py` 中 `format_attention_anchor` 与 `DISTILLATION_PROMPT_V2` 的精准 diff；
   - 展示 `batch_distill.py` 中 argparse 新增参数的实现；
3. **离线装配抽验展示**：
   - 截取 `data/staged_prompts_v2/rep_slowmist_002_prompt.md` 中 `=== VERIFIED FUND-FLOW TELEMETRY ===` 与 `MACRO CAMPAIGN TOPOLOGY MANDATE` 的最新内容片段；
4. **非破坏性真机验证一键指令**：
   - 明确给出研究者在本地配置好 API Key 后，**用于对 14 篇研报发起非破坏性验证的完整 CLI 命令**（将结果安全写入 `data/experiments/step1_denoise_kb.json`，带 `--live`）。
