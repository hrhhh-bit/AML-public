# Stage 4 · Agent 决策循环（perceive → retrieve → plan → act）

场景：`showcase-跨链分层归集` · 终止方式：`agent_terminate` · success=True · total_reward=1.0 · LLM 总调用 6 次

| step | 动作 | RAG 先验 Motif（分数） | 软回退 | LLM 调用 | 重试原因 | reward |
|---|---|---|---|---|---|---|
| 0 | `Transfer`(node_0) → Intermediate @ Chain_A | DEX_Liquidity_Pool_Swap(0.7307), Peeling_Chain_Single_Chain(0.6946) |  | 1 | — | 0.0 |
| 1 | `Split`(node_1) → Intermediate @ Chain_A {'num_children': 2} | Cross_Chain_Swap_Bridge(0.7489), Single_Chain_Multi_Swap_Layering(0.6728), Multi_Split_Obfuscation(0.6284) |  | 1 | — | 0.0 |
| 2 | `Merge`(node_2,node_3) → Aggregator @ Chain_A | Mixer_Anonymization_Split_Merge(0.6321), Multi_Split_Obfuscation(0.6284), Aggregation_Merge_To_Target(0.6223) |  | 1 | — | 0.0 |
| 3 | `Bridge`(node_4) → Cross_Chain @ Chain_B | Multi_Split_Cross_Chain_Bridge(0.6922), Cross_Chain_Layered_Integration(0.6616), Mixer_Anonymization_Split_Merge(0.6321) |  | 1 | — | 0.0 |
| 4 | `Transfer`(node_5) → Target @ Chain_B | Multi_Split_Cross_Chain_Bridge(0.6922), Cross_Chain_Layered_Integration(0.6616), Aggregation_Merge_To_Target(0.6223) |  | 1 | — | 0.0 |
| 5 | **Terminate**（控制动作） | Cross_Chain_Swap_Bridge(0.5823), Multi_Split_Cross_Chain_Bridge(0.5255), Single_Chain_Multi_Swap_Layering(0.5062) | ⚠️ soft | 1 | — | 1.0 |

## 逐步产物
- `step_00_prompt.txt` — 第 0 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_00_action.json` — 第 0 步 Agent 动作
- `step_01_prompt.txt` — 第 1 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_01_action.json` — 第 1 步 Agent 动作
- `step_02_prompt.txt` — 第 2 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_02_action.json` — 第 2 步 Agent 动作
- `step_03_prompt.txt` — 第 3 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_03_action.json` — 第 3 步 Agent 动作
- `step_04_prompt.txt` — 第 4 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_04_action.json` — 第 4 步 Agent 动作
- `step_05_prompt.txt` — 第 5 步完整规划提示词（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）
- `step_05_action.json` — 第 5 步 Agent 动作

- `trajectory.json` — 完整轨迹审计（prior_motif_ids / retry_reasons / llm_calls 留痕）
