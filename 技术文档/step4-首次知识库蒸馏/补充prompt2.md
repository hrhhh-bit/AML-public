任务：解决跨源一致性中“算子子阶段割裂”问题，实现 Nomad 事件一致性收敛

1. 现状量化审查
   运行 eval_cross_source.py 后，合法率与纯净度达 100%（residue_count: 0, valid_rate: 1.0），但一致性依然为 0.0：

- CertiK 提取算子：["Bridge", "Transfer"] (Chain_Hopping, motifs: 1)
- Zerion 提取算子：["Split"] (Multi_Layering_Split, motifs: 1)
- 根因：LLM 对两份报告都只提取了极局部的单步 Motif，CertiK 漏掉了分流分发（Split），Zerion 漏掉了资金来源是跨链桥（Bridge），导致双方算子集合无交集（Jaccard = 0.0）。

2. 具体改进目标（协同解决）

改进点 A：增强 Distiller 的“复合事件拓扑感知与完整性”（src/aml_rag/distiller.py）

- 在 DISTILLATION_SYSTEM_PROMPT_V2 中明确补充指导：
  1. 复合链条提取（Composite Multi-hop Awareness）：真实安全事件通常包含“入口/跨链 -> 分流/混币 -> 转移归集”的复合流程。若文本同时包含漏洞利用/跨链逃逸（Bridge）及后续资金分流到多个地址/黑客复制行为（Split/Transfer），应将其抽象为包含完整流向的复合 Motif（如包含 Bridge -> Split -> Transfer 的拓扑图），而非仅截取孤立的单一步骤。
  2. 允许多 Motif 产出：若一段文本包含多个明确的洗钱行为环节，允许且鼓励输出 1-3 个核心行为 Motif，避免信息单点丢失。

改进点 B：拓扑一致性计算的边界与容错（src/aml_rag/evaluation.py）

- 审查 `CrossSourceConsistencyEvaluator`：
  - 确认算子提取是否包含了边算子（Edge Operator: Bridge, Swap, Split, Merge, Transfer）以及节点类型；
  - 确保集合交集比较基于大小写统一的标准枚举字符串。

3. 验证与回归要求

- 保持 Stage-1 红线：严禁引入 0x 地址、具体代币与金额；
- 跑通 pytest，确保已有的 123 个单测全部通过；
- 重新运行 `scripts/eval_cross_source.py`，验收 CertiK 与 Zerion 提取出的全局算子是否形成交集（例如双方均覆盖 Bridge 或 Split，使得 `global_topology_jaccard >= 0.50`）。
