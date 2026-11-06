# 【任务指令】Task 4：实施解析后处理代币符号脱敏清洗器（Token Scrubber）与零噪声自愈防线

## 一、 任务背景与核心根因

在刚才的真机全量蒸馏中，14 篇黄金研报的双阶段战役级抽取与全部图公理（无环、流量守恒、桥接闭环）已全部验证通过（`ledger_issues={}`）。但在最终的原子替换门禁处触发了拦截：

- **拦截现场**：`RuntimeError: 全库穿透审计或零噪声扫描未通过 ... violations: {'dex_swap_then_bridge_exit': ['token_symbol']}`；
- **根因诊断**：Check 3 扫描器（`zero_noise_audit`）对全库所有文本字段执行严格的正则扫描。大模型在抽取 `dex_swap_then_bridge_exit` 时，在其自然语言 `description`（或标签备注）中偶然提及了具体的代币字面量（如 `ETH`、`USDT` 等）；
- **架构裁决**：
  1. 坚决**不放宽** `zero_noise_audit` 既有的只读硬门禁（捍卫 Stage-1 零微观噪声公理）；
  2. 必须在解析后处理层（Post-processing Normalization）引入**代币符号脱敏清洗器（Token Scrubber）**，在进入审计与落盘前将自然语言中的代币字面量自动泛化抽象为无量纲代号，使系统具备对大模型自然语言微观噪声的自愈能力。

---

## 二、 架构红线与刚性约束

1. **零微观噪声物理绝缘（Check 3 必过）**：
   - 生产知识库与抽取产物中，绝对禁止残留任何具体代币符号（USDT, USDC, ETH, BTC, DAI, BNB, MATIC, SOL, TRX 等）或真实地址（`0x...` / `bc1...` / `T...`）；
   - 经脱敏后，`zero_noise_audit` 的扫描结果必须严格满足 `residue_count == 0`；
2. **纯函数无损抽象原则**：
   - 脱敏操作仅针对自然语言文本（如 `description`、`tags`、节点与边的备注说明），**绝对不得破坏图结构、节点 ID、边角色或 `flow_share` 权重**；
   - 替换映射应符合金融无量纲常识（例如：稳定币 $\to$ `stablecoin_asset` 或 `token`；公链原生币 $\to$ `native_asset` 或 `asset`；其余代币 $\to$ `token`）；
3. **单测回归红线**：
   - 全量自动化测试套件必须保持 **$\ge 384$ passed（0 failed / 0 errors）**；
4. **基线白板保持**：
   - 确保 `data/distilled_kb.json` 保持为 18 基标纯净状态（与 `distilled_kb_v1.json` 完全一致）。

---

## 三、 工程实施模块与具体任务

下游 Agent 请自主通读相关代码（重点审计 `scripts/batch_distill.py`、`src/aml_rag/invariants.py` 或 `sanitizer.py` 中 `zero_noise_audit` 的扫描词表与正则规则），完成以下三项手术：

### 1. 词典对齐与脱敏清洗器实现（`prompt_v2.py` 或解析管道）

- 提取 `zero_noise_audit` 所关注的全部代币符号与违规模式集合；
- 实现纯函数清洗器 `scrub_micro_noise(text: str) -> str`（以及针对 Motif 对象的脱敏函数 `scrub_motif_metadata(motif: Motif) -> Motif`）；
- 使用词边界正则匹配（如 `\b(USDT|USDC|ETH|BTC|WBTC|DAI|BNB|MATIC|SOL|TRX)\b` 等），将其安全、无损地替换为标准抽象词（如 `asset` / `token`）；
- 在 `parse_v2_response` 或 `PromptV2Distiller` 解析完模型返回的 JSON 对象后、返回 `ParsedV2Payload` 之前，**强制对每一个 Motif 的 `description`、`tags`、名称及属性执行该清洗规整**。

### 2. 认知层防御加固（`prompt_v2.py` 提示词微调）

- 在 `prompt_v2.py` 的系统契约中（如 `MACRO CAMPAIGN TOPOLOGY MANDATE`），增加一行警示红线：
  > `CRITICAL: Do NOT mention concrete token symbols (e.g., USDT, ETH, BTC) even in descriptions or tags. Always use generic terms like 'native_asset', 'stablecoin', or 'token'.`
- 同步执行离线装配指令刷新 `data/staged_prompts_v2/` 离线提示词。

### 3. Mock 单测覆盖

- 在 `test_prompt_v2.py` 中新增至少 1 项测试：
  - 构造一个包含 `description="Swaps ETH via DEX and transfers USDT to mixer"` 的 Mock JSON payload；
  - 断言解析器输出的 Motif 其 `description` 中的代币符号已被成功脱敏；
  - 将脱敏后的 Motif 送入 `zero_noise_audit`，断言其 `residue_count == 0` 且 `violations == {}`。

---

## 四、 验收量化指标与汇报要求

下游 Agent 完成开发后，必须在终端自检并汇报以下数据：

1. **单测回归结果**：
   - 运行全量 `pytest`，必须保持 **$\ge 385$ passed（0 failed / 0 errors）**；
2. **基线哈希确认**：
   - 证明 `data/distilled_kb.json` 依然与 `distilled_kb_v1.json` 保持哈希 100% 一致（18 个条目）；
3. **关键代码 Git Diff**：
   - 展示 `scrub_micro_noise` 的核心正则实现与解析器挂载点；
4. **汇报完毕后，明确提示研究者可以重新执行真机提取命令**。
