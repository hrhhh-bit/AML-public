1. 初始motif

- 【Motif 审查】Cross_Chain_Swap_Bridge
  判定：【类别 2: 局部校准】
  缺陷：冗余跳数与角色错位。S -> AC 为 Transfer，AC 未发生兑换却被标记为 ASSET_CONVERSION；全图将一次 Swap+Bridge 虚假膨胀为 4 跳。
  真实链上流向：Source (Chain A) -> [Swap] -> 换币后中继 -> [Bridge] -> 目标链中继 -> [Transfer] -> Target

- 【Motif 审查】DEX_Liquidity_Pool_Swap
  判定：【类别 2: 局部校准】
  缺陷：动作与角色时序倒置（与上一条同源病灶）。
  S -> AC 标为 Transfer，AC 持有的依然是原代币，却被命名为 Asset_Conversion；
  AC -> T 标为 Swap，说明兑换动作是在流向 T 时才发生的，真正接收新资产的实际上是 T；
  概念混淆：该 Motif 试图把“DEX 流动性池（Liquidity Pool）”具象化为一个节点 AC。但在框架中，SWAP 边已经把池子交互抽象化了，池子不应该作为接收转账的钱包节点出现。
  真实链上流向：黑客将赃币通过 DEX 换成新资产暂存，再转给目标；或直接将赃币转给中继代换。
  Patch 方案（对调边操作，保全 3 节点结构，推荐）：
  边 1 (S -> AC)：操作由 Transfer 改为 Swap（S 换币后资金流入 AC，AC 作为 Asset_Conversion 成立）；
  边 2 (AC -> T)：操作由 Swap 改为 Transfer（AC 将兑换后的干净代币转至 T）。

- 【Motif 审查】Mixer_Anonymization_Split_Merge
  判定：【类别 2: 局部校准】
  缺陷：
  描述与边动作严重脱节（缺少 SWAP）：description 明确写着“funds are swapped through an asset-conversion node”，但全图边只有 Transfer、Split、Merge，没有任何 SWAP 边，导致 AC 的 Asset_Conversion 角色完全沦为摆设；
  战术术语混淆（伪 Mixer）：命名和 Tag 带有 mixer，但拓扑是纯粹的**“菱形分流归集（Diamond Split-Merge Layering）”**。真实混币器（如 Tornado）是资金池沉淀与断链，而非确定性的链上分流再汇聚。
  Patch 方案（保全换币分流语义，推荐）：
  补齐换币动作：将边 1 (S -> AC) 的操作由 Transfer 改为 Swap（黑客换币后进入 AC，AC 再分流）；
  净化战术标签：在 tags 中剔除 "mixer"，改为 "layering"，避免顶会审稿人抓住“确定性 DAG 冒充混币器”进行学术质疑

-【Motif 审查】Single_Chain_Multi_Swap_Layering
判定：【类别 2: 局部校准】
缺陷：
首尾动作与描述完全倒置：description 明确声明是“连续换币以混淆资产路径，最终转账至目标（...before the final transfer）”。但实际边却是首跳转账（Transfer）、尾跳换币（Swap），首尾彻底反了；
角色不自洽：AC1 接收的是普通 Transfer（仍是原脏币），未发生任何形态转变，其 Asset_Conversion 角色不成立。
Patch 方案（对齐“两换一转”的因果时序，强烈推荐）：
边 1 (S -> AC1)：操作由 Transfer 改为 Swap（第 1 次换币，AC1 成为真正的第 1 个转换节点）；
边 2 (AC1 -> AC2)：保持 Swap（第 2 次连续换币，AC2 成为第 2 个转换节点）；
边 3 (AC2 -> T)：操作由 Swap 改为 Transfer（落实描述中的“最终转账提现至目标钱包”）。

- 【Motif 审查】Cross_Chain_Layered_Integration
  判定：【类别 2: 局部校准】
  金融因果评价：宏观逻辑极佳。真实反映了黑客多链、多入口攻击后，源链汇聚跨链、再与目标链本地资金二次归集提现的复杂洗钱战役（如 Nomad / Harmony 案）。
  缺陷：
  汇聚边操作不对称：汇聚节点 AGG2 接收 S3 和 CC 两股资金，但 S3 -> AGG2 标注为 Merge，CC -> AGG2 却被标注为 Transfer，破坏了汇聚算子的对称契约；
  前置条件元数据遗漏：preconditions.allowed_node_roles 仅写了 ["Source", "Intermediate", "Cross_Chain"]，漏掉了图中实际使用的 Aggregator 与 Target，会导致 Planner 约束检查器误报。
  Patch 方案：
  对齐汇聚边操作：将边 CC -> AGG2 的操作由 Transfer 改为 Merge；
  修正元数据契约：在 preconditions.allowed_node_roles 中补全 "Aggregator" 和 "Target"。

- 【Motif 审查】Multi_Split_Cross_Chain_Bridge
  判定：【类别 2: 局部校准】
  缺陷：
  支路落地因果不对称：
  支路 1 与支路 3：Chain_A -> Chain_B (CC1/CC3) -> [Transfer] -> T (Chain_B)；
  支路 2：Chain_A -> Chain_C (CC2) -> [Bridge] -> T (Chain_B)。
  支路 2 在 Chain_C 的跨链桥直接以 T 为目标收款人穿透跨链，而支路 1/3 却在目标链额外多了一跳本地中转转账，结构不对称；
  描述与链配置冲突：description 声明每条支路跨往“不同目标链（different destination chain）”，但实际拓扑中支路 1 和支路 3 全都跨到了相同的 Chain_B；
  前置条件元数据遗漏：preconditions.allowed_node_roles 漏掉了 "Target"。
  Patch 方案（对齐三路并行跨链语义，推荐）：
  方案 1（纯三路跨到 B 链规避限额，最简）：将 CC2 的链改为 Chain_B，CC2 -> T 操作改为 Transfer，使三条支路呈现完美的 3 重并行分流跨链（Symmetric Multi-Bridge）；
  方案 2（真·三链穿透）：若确实要走 Chain_C，将 CC2 定位为跳板，补上目标链落地的 Intermediate 或统一将三路入 T 标注为汇聚；
  补齐契约：在 preconditions.allowed_node_roles 补入 "Target"。

2. handbook审查

- 【Motif 审查】mixer_pooling_obfuscation
  判定：【类别 2: 局部校准】
  金融因果评价：拓扑建模非常经典。通过双源归集（S1, S2 -> Merge -> M）表达混币池的匿名集注入（Pooling），再通过分流（M -> Split -> T1, T2）表达碎片化提现（Fragmented Withdrawals），在确定性 DAG 内完美拟合了 Tornado Cash 等混币器的交互骨架。
  缺陷：
  末端角色与后续状态转移冲突（Role-State Paradox）：
  图中提现节点 T1, T2 被直接赋予了终极结算角色 Target；
  但 post_state_effect.next_recommended_roles 却推荐后续接入 ["Cross_Chain", "Asset_Conversion"]。
  因果矛盾：在 AML 真实战役中，若混币后还要继续跨链或换币，提现出来的地址只能是中继钱包（Intermediate）；若已经是最终沉淀钱包（Target），图便已终结，不应再推荐扩展。
  前置条件元数据遗漏：preconditions.allowed_node_roles 仅包含 ["Source"]，遗漏了可能作为上游接入的 Intermediate（黑客通常先转账至中继再入混币池）。
  Patch 方案：
  方案 A（作为中途混币离析跳板，推荐）：
  将 T1, T2 的角色由 Target 改为 Intermediate（保持 post_state_effect 推荐后续跨链/换币不变，形成“混币后继续逃逸”的长链）；
  方案 B（作为最终洗钱落袋）：
  保持 T1, T2 为 Target，将 post_state_effect.next_recommended_roles 改为空列表 [] 或仅保留 ["Target"]；
  补齐前置条件：在 preconditions.allowed_node_roles 补入 "Intermediate"。

- 【Motif 审查】motif_chain_hopping_bridge_evasion
  判定：【类别 2: 局部校准】
  缺陷：
  Asset_Conversion 角色虚设（无 SWAP 边）：研报强调“可能涉及资产代币变化”，AC 节点的角色也设为了 Asset_Conversion，但它的入边（S -> AC）和出边（AC -> CC）全都是普通 Transfer。没有任何换币动作，违反了资产转换节点的契约；
  源链跳数冗余（Hop Inflation）：在执行跨链桥操作前，连续在源链执行了两次无状态改变的同币种转账（S -> AC -> CC），若不换币，AC 沦为纯粹的冗余幽灵节点。
  Patch 方案：
  方案 1（落实研报的“代币变化”，强烈推荐）：
  将边 1 (S -> AC) 的操作由 Transfer 改为 Swap（黑客先将赃币换成 THORChain/Across 支持的主流币/稳定币打入 AC，再准备跨链），彻底盘活 AC 节点的因果合理性；

- 【Motif 审查】otc_p2p_integration_merge
  判定：【类别 2: 局部校准】
  缺陷：
  链下承兑（Off-chain Off-ramp）与链上 SWAP 范畴混淆：
  研报明确指出 P2P/OTC 是通过电报中介、汇旺担保或银行卡进行**“链下法币/现金出金”**；
  但 Motif 尾部却画了一条 AC --[Swap]--> T。在区块链上，根本不存在能直接把代币 Swap 成法币或线下现金的智能合约！资金一旦打入 OTC 承兑商/中介的充值地址，链上因果链条就已宣告终止（Sink）；
  中介节点因果矛盾：
  描述称“资金归集到 OTC/P2P 中介 AG”；若 AG 已经是 OTC 承兑商，资金在 AG 就应出金下链，怎么可能还由 AG 在链上继续发起 Bridge 跨到 Chain_B？
  真实链上资金流：黑客在以太坊（Chain A）将赃款多路归集，跨链转移至监管薄弱且 OTC 活跃的网络（如波场 TRON / Chain B），最后转账存入 OTC 承兑商提供的充币地址离线套现。
  Patch 方案（对齐真实跨链 OTC 出金事实，强烈推荐）：
  纠偏尾部动作与角色：
  将 AC 的角色改为 Intermediate（目标链接收中继钱包）；
  将最后一条边 AC -> T 的操作由 Swap 改为 Transfer（转入承兑商入金地址 T，T 作为最终链上沉淀 Target）；
  修正描述语义：将描述中“AG 是 OTC 中介”修正为“AG 是攻击者源链归集钱包，T 是目标链 OTC/P2P 承兑入金地址”。

3. rep_slowmist_002

- 【Motif 审查】motif_cross_chain_merge_consolidation
  判定：【类别 3: 致命伪阳性 (Reject)】
  建议：直接从知识库中剔除，存证至 quarantine_motifs.json 存在大模型臆造跳数（幽灵节点 CC_A/B），违背真实研报证据链。

- 【Motif 审查】motif_chain_hopping_multichain_consolidation
  判定：【类别 2: 局部校准 (Minor Patch)】
  诊断与缺陷：
  拓扑逻辑合理：3 链换币后直穿入账，完全符合研报中“BNB/Arbitrum 换 USDT 后跨入以太坊”的事实；
  致命红线瑕疵（微观名称泄露）：图中出现了 "chain": "Chain_Ethereum"！
  Stage-1 严格遵循零微观噪声铁律，严禁绑定具体链名（如 Ethereum、BSC、TRON），必须全部抽象为离散代号。
  Patch 方案：
  将所有节点的 "chain": "Chain_Ethereum" 批量替换为抽象名称 "Chain_D"（或 "Chain_Target"）；
  preconditions.required_chains 中同步规范，保持全图抽象纯净。

4. rep_certik_014（专家一票否决裁决 · 宏观行业综述体裁错位）

- 【体裁诊断】"Evil in the Shadows: Unveiling the Chaos in Ethereum's Token
  Ecosystem" 是 CertiK 宏观行业综述（93,930 个新代币的全景调查），非单一案件溯源。
  现有 TextChunker 对其逐段分块、逐块独立蒸馏，导致 14 个 Motif 恶性膨胀
  （satellite 遥测：extracted=14 / deduplicated=0 / net_added=14）。

- 【采纳金标（保留 3 个战役级骨架）】
  1. infrastructure_split_for_volume_fabrication（Motif 7）：multiSend 基础设施
     批量拆分 + DEX Swap 伪装交易量，结构纵深完整（8 节点 / 7 边）。
  2. fund_holding_dispersal_cashout（Motif 5）：资金池再生产闭环——70% 回流注水、
     30% 经 DEX Swap 换稳定币转 CEX 变现（6 节点 / 5 边）。
  3. multi_source_rug_pull_profit_consolidation（Motif 6）：多案欺诈收益 Swap 归集
     至核心蓄水池（7 节点 / 6 边）。

- 【物理剔除（11 个）· 判定类别】
  - fund_holding_cashout_and_recycle（Motif 8）：【同义克隆】Motif 5 的
    Swap→Transfer 粗化有损克隆（0.7/0.3 权重与 Motif 5 完全一致）。
  - fabricated_volume_split_to_liquidity（Motif 2）/ shared_splitter_fanout_swap
    （Motif 10）：【同义克隆】与 Motif 7 同源（分发合约刷量机制）的粒度变体。
  - cex_operational_funding_merge（Motif 9）/ cex_swap_funding_consolidation
    （Motif 12）/ multi_source_exchange_consolidation（Motif 14）：【卡线碎片】
    交易所热钱包注资三胞胎（Table 6 同源），3 边星型 / 多对一直通，无战役纵深。
  - approval_drain_swap_exit（Motif 3）/ direct_dex_swap_obfuscation（Motif 11）：
    【卡线碎片】纯线性单链 3 跳，无分支/汇聚。
  - liquidity_removal_split_cashout（Motif 13）：【卡线碎片】1 分 2，恰好 3 边。
  - rug_pull_inflow_consolidation（Motif 4）：【重复冗余】与 Motif 5/6 构成同一战役
    的流入阶段，其 7 边结构虽完整但语义被 5/6 覆盖，归并吸收。
  - initial_funding_liquidity_seed（Motif 1）：【品类错位】mint + 加 LP + 烧 LP
    （BURN 作 Target）属发币欺诈/攻击利用机制，非资金离析，移出 AML 拓扑。

- 【裁决生效方式】上述 11 个 Motif 自 step1_denoise_kb.json 的晋升路径中物理剔除，
  存证至 quarantine_motifs.json；本裁决为 HITL 因果标杆，供补丁③（TextChunker
  综述聚焦）与后续 embedding 去重验证的 ground-truth 使用。
