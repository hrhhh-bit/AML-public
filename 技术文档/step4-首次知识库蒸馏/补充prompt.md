# 任务：基于真实跨源实证结果优化 AML 拓扑提取与一致性比对算法

## 1. 上下文与现状诊断

我们针对 2022 Nomad Bridge 事件引入了两份真实工业界研报进行了跨源一致性实验（Check 2）：

- 源 A：`resources/cross_source_test/nomad_certik.txt`（CertiK 安全博客，充斥 0x 地址与合约变量）
- 源 B：`resources/cross_source_test/nomad_zerion.txt`（Zerion 资金追踪分析，含商业广告与口语化描述）
- 评测脚本：`scripts/eval_cross_source.py`
- 运行产物：`experiments/phase2_distillation_empirical/cross_source_consistency_nomad.json`

### 现状分析

1. **极限纯净度与合法率已满分**：CertiK 与 Zerion 均实现 `valid_rate: 1.0` 且 `residue_count: 0`（零微观噪声），证明底层门禁绝对鲁棒；
2. **瓶颈暴露**：`overall_consistency` 为 0.0。
   - 现象：CertiK 识别为 `["Chain_Hopping", "Multi_Layering_Split"]`，而 Zerion 被文本中的白帽退款或口语化描述稀释，提取出的 `pattern_type` 或边算子签名无法与 CertiK 形成同类型交集，导致 Jaccard 分母非空但分子交集为 0。

## 2. 改进目标

请协同优化 `src/aml_rag/distiller.py` 与 `src/aml_rag/evaluation.py`，使跨源一致性提升至合理收敛区间（目标 Jaccard $\ge 0.50$）：

### 改进点 A：Distiller 模式归一化约束（`distiller.py`）

- 在 Distillation 的 Prompt 中，加强对核心反洗钱行为的本体聚焦，强化对以下高频洗钱模式类型的标准对齐：
  - `Bridge_Evasion` / `Chain_Hopping`（跨链跳跃）
  - `Multi_Layering_Split`（多层扇出分流）
  - `Consolidation_Merge`（聚合归集/退款归结）
- 增加语义锚定指令：若文本涉及“将多币种通过 DEX 换成同一种代币”，明确引导归一为包含 `Swap` 算子的拓扑；若涉及多地址分流，引导归一为 `Split` 算子。

### 改进点 B：CrossSourceConsistencyEvaluator 鲁棒性对齐（`evaluation.py`）

- 检查当前计算 Jaccard 的粒度：是严格绑定 `pattern_type` 还是支持图拓扑的全局边算子签名（Global Edge Operator Set）重合度计算？
- 实现双轨一致性评估指标：
  1. `pattern_strict_jaccard`：同 Pattern 类别下的边签名 Jaccard（既有逻辑）；
  2. `global_topology_jaccard`：忽略局部模式标签差异，直接对比两份报告提炼出的整体行为算子序列（如 `[Bridge, Swap, Split]` 的边签名集合 Jaccard）。

## 3. 约束红线

- 严格遵循 Stage-1 原则，严禁引入具体地址、微观金额、Gas 或代币符号；
- 保持所有修改向前兼容，确保全系统已有单元测试（`pytest`）全绿，不得破坏原有 18-Motif 的纯净度。
- 给出清晰的文件修改 diff，并执行 `scripts/eval_cross_source.py` 验证修复后的得分。
