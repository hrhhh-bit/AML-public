# 13 个净增 Motif 语义审计清单（HITL Cheat Sheet）

> 数据源：`data/distilled_kb_v2.json`（33 条）· 排除 18 金标 + 已裁决 `rep_certik_014`(#31) / `rep_slowmist_002`(#19)
> 审计法：「极简三看」——① 品类对齐（exploit vs 洗钱）② 中继保真（mules/跳步未吞）③ 动作物理自洽（Swap/Bridge 时序）
> 图例：🔴 品类预警 · 🟠 混币语义 · ⚪ 跨链 · ✅ 通过初筛

---

## 1. unified_illicit_mint_bridge_split_stream
- **report_id** `rep_slowmist_003` · **事件** Liquid Network Cache Key Collision（近 4,000 L-BTC 伪造铸造）
- **pattern** Multi_Layering_Split · **边/节点** 7/8 · **ScaleTier（建议）** State_Sponsored · **stage_boundary** 无
- **Ground-truth**：攻击者利用缓存键碰撞凭空铸造 L-BTC，归集后经 federated peg-out 跨链兑换为 BTC，随后在区块间大量自转账（OP_RETURN 附言）混淆去向。
- **ASCII flow**
  ```
  [S1]─Merge 1.0─▶[AGG]─Bridge 1.0─▶[CC]─Transfer 1.0─▶[I_PAYOUT]
  [S2]─Merge 1.0─┘                    │
                     ├──Split 0.8──▶[T_RETURN]
                     └──Split 0.2──▶[I_SELF]─Transfer 1.0─▶[T_REMAIN]
  ```
- **旗标** ⚪ BRIDGE（peg-out 属实）· 🔴 **品类预警**：`mint`（凭空铸 L-BTC）是漏洞利用手段，作为 Source 混入洗钱拓扑，与已裁决的 `initial_funding_liquidity_seed` 同类，需裁定 Source 语义。

---

## 2. unauthorized_issuance_bridge_split_cashout
- **report_id** `rep_certik_001` · **事件** Liquid Network Incident（未授权发行）
- **pattern** Chain_Hopping · **边/节点** 6/7 · **ScaleTier（建议）** State_Sponsored · **stage_boundary** 无
- **Ground-truth**：未授权发行资产后，经中继地址两笔 peg-out 跨链至 BTC 主链：3,400 BTC 被返还给 federated 钱包，598.5 BTC 被攻击者留存。
- **ASCII flow**
  ```
  [S]─Transfer 1.0─▶[I1]─Transfer 1.0─▶[I2]
                                        ├──Bridge 0.5──▶[CC1]─Transfer 1.0─▶[T1]
                                        └──Bridge 0.5──▶[CC2]─Transfer 1.0─▶[T2]
  ```
- **旗标** ⚪ BRIDGE（两笔 peg-out 属实）· 🔴 **品类预警**：`unauthorized issuance` 是 exploit 源；两笔 peg-out 中「返还」分支非洗钱，与 #32 同源，需裁定是否应只保留留存支路。

---

## 3. cross_chain_bridge_to_mixer_exit
- **report_id** `rep_certik_002` · **事件** Verus Incident
- **pattern** Chain_Hopping · **边/节点** 4/5 · **ScaleTier（建议）** Whale · **stage_boundary** 无
- **Ground-truth**：被盗资产经 Relay 跨链兑换为 2,778.8662 ETH，最终全部存入 Tornado Cash。
- **ASCII flow**
  ```
  [S]─Bridge 1.0─▶[CC]─Transfer 1.0─▶[AC]─Swap 1.0─▶[I]─Transfer 1.0─▶[T (mixer)]
  ```
- **旗标** ⚪ BRIDGE · 🟠 **混币语义**：`T` 为 Tornado 沉淀（描述称 mixing sink）· ⚠️ **时序待核**：evidence 为「swap via Relay → ETH → Tornado」，即换币先于/伴随跨链；本图把 `Swap` 置于 `Bridge` 之后，需对照原文确认 Relay 的 swap/bridge 先后。

---

## 4. cross_chain_swap_bridge_split_outflow
- **report_id** `rep_certik_003` · **事件** DefiTuna Incident
- **pattern** Chain_Hopping · **边/节点** 7/7 · **ScaleTier（建议）** Medium · **stage_boundary** ✅ `CC`
- **Ground-truth**：Solana 攻击地址经 Mayan 桥跨入 Ethereum，140 ETH 存入隐私协议 Railgun，291,696 DAI + 5 ETH 留存在钱包。
- **ASCII flow**
  ```
  [S]─Swap 1.0─▶[AC]─┬──Split 0.5──▶[I1]─Bridge 1.0─▶┐
                     └──Split 0.5──▶[I2]─Bridge 1.0─▶[CC]
                                          ├──Split 0.5──▶[T1 (privacy)]
                                          └──Split 0.5──▶[T2 (residual)]
  ```
- **旗标** ⚪ BRIDGE（Mayan 属实）· 🟠 **混币语义**：`T1` 为 Railgun 隐私池，非 Tornado 但同属匿名集注入，需确认命名/标签是否应补 `privacy` · ✅ 割点 `CC` 已自动标注（in=2/out=2 跨链枢纽）。

---

## 5. drain_convert_split_mixer_cashout_campaign
- **report_id** `rep_certik_004` · **事件** JaredFromSubway MEV Bot Incident
- **pattern** Multi_Layering_Split · **边/节点** 13/11 · **ScaleTier（建议）** Whale · **stage_boundary** 无
- **Ground-truth**：攻击者 drain 后经 DEX 将 USDC/USDT 换为 ETH，分发至 5 个地址，其中 3,000 ETH 存 Tornado Cash，1,422 ETH 换为 ~$2.44M DAI 留存在钱包。
- **ASCII flow**
  ```
  [S]─Transfer 1.0─▶[AC1]─Swap 1.0─▶[I]
      ├─Split 0.23─▶[M1]─Merge 1.0─▶┐
      ├─Split 0.23─▶[M2]─Merge 1.0─▶[AGG (mixer)]
      ├─Split 0.22─▶[M3]─Merge 1.0─▶┘
      ├─Split 0.16─▶[M4]─Merge 1.0─▶[AC2]─Swap 1.0─▶[DEST (DAI)]
      └─Split 0.16─▶[M5]─Merge 1.0─▶┘
  ```
- **旗标** 🟠 **混币语义**：`AGG` 描述为「mixer aggregator」但角色是普通 Aggregator（非显式 mixer 节点），需裁定 3,000 ETH Tornado 是否应显式建模 · ✅ 5 mules 中继保真（对应 5 个地址）。

---

## 6. bridge_swap_split_outflow
- **report_id** `rep_certik_005` · **事件** GnosisPay Incident
- **pattern** Multi_Layering_Split · **边/节点** 8/9 · **ScaleTier（建议）** Medium · **stage_boundary** 无
- **Ground-truth**：资金从 Ethereum 桥接 USDT 至 Hyperliquid，换为 XMR 后拆分至 4 个地址。
- **ASCII flow**
  ```
  [S]─Bridge 1.0─▶[CC]─Transfer 1.0─▶[I1]─Transfer 1.0─▶[AC]─Swap 1.0─▶[I2]
      ├─Split 0.25─▶[T1]   ├─Split 0.25─▶[T2]
      ├─Split 0.25─▶[T3]   └─Split 0.25─▶[T4]
  ```
- **旗标** ⚪ BRIDGE（Ethereum→Hyperliquid 属实）· ✅ **动作自洽**：`AC` 入 Transfer 出 Swap，符合 Asset_Conversion 契约；换 XMR 为隐私币，建议补 `privacy` 标签（当前 tags 空）。

---

## 7. cross_chain_exploit_exit_loop
- **report_id** `rep_certik_007` · **事件** Movie Token Incident
- **pattern** Chain_Hopping · **边/节点** 6/7 · **ScaleTier（建议）** Medium · **stage_boundary** 无
- **Ground-truth**：381.7468 WBNB → ~242k USDC，桥接 BSC→Ethereum → ~242k DAI → Railgun 匿名化。
- **ASCII flow**
  ```
  [S]─Swap 1.0─▶[AC1]─Transfer 1.0─▶[I1]─Bridge 1.0─▶[CC]─Transfer 1.0─▶[AC2]─Swap 1.0─▶[I2]─Transfer 1.0─▶[T (privacy)]
  ```
- **旗标** ⚪ BRIDGE（BSC→Ethereum 属实）· 🟠 **混币语义**：`T` 为 Railgun shield（描述未显式提及 privacy，仅「shielded target sink」）· ✅ 双 Swap（WBNB→USDC→DAI）与 evidence 一致。

---

## 8. flash_loan_swap_manipulation_cashout
- **report_id** `rep_certik_008` · **事件** SOF/LAXO Incident
- **pattern** Multi_Layering_Split · **边/节点** 6/7 · **ScaleTier（建议）** Medium · **stage_boundary** 无
- **Ground-truth**：SOF 攻击者 → FixedFloat ~$213,617 BSC-USD（10 笔）；另 → Tornado Cash 20 BNB（2×10 BNB）。
- **ASCII flow**
  ```
  [S]─Swap 1.0─▶[AC1]─Transfer 1.0─▶[I1]─Swap 1.0─▶[AC2]─Transfer 1.0─▶[I2]
      ├──Split 0.9──▶[T1 (exchange/CEX)]
      └──Split 0.1──▶[T2 (mixer)]
  ```
- **旗标** 🟠 **混币语义**：`T2` 对应 Tornado 20 BNB · 🔴 **品类预警**：描述含 `flash-loan` 与 `manipulated token`，属漏洞利用步骤；需裁定 flash-loan 是否应降级为「资金来源说明」而非拓扑节点（当前未建模 flash-loan 节点，仅描述提及，风险较低）。

---

## 9. exploit_mint_swap_split_mixer_exit
- **report_id** `rep_certik_011` · **事件** Truebit Incident
- **pattern** Multi_Layering_Split · **边/节点** 6/7 · **ScaleTier（建议）** Whale · **stage_boundary** 无
- **Ground-truth**：4,267.09 ETH → 0xD12f…；4,001 ETH → 0x2735…；71.03 ETH → Tornado Cash。
- **ASCII flow**
  ```
  [S]─Swap 1.0─▶[AC]─┬──Split 0.8──▶[I1]─┬──Split 0.5──▶[T1]
                     │                  └──Split 0.5──▶[T2]
                     └──Split 0.2──▶[I2]─Transfer 1.0─▶[M (mixer)]
  ```
- **旗标** 🟠 **混币语义**：`M` 对应 Tornado 71 ETH · 🔴 **品类预警**：描述含 `mint token without cost`（exploit 源），但 evidence 无 mint 环节、纯大额 ETH 转移，mint 表述存疑，需对照原文。

---

## 10. swap_inflation_batched_mixer_exit
- **report_id** `rep_certik_012` · **事件** Balancer Incident
- **pattern** Multi_Layering_Split · **边/节点** 8/7 · **ScaleTier（建议）** Whale · **stage_boundary** 无
- **Ground-truth**：漏洞钱包分批 → Tornado Cash 3,711 ETH（39 笔）；Sonic 链资金规避冻结后换为 ~$3.3M ETH。
- **ASCII flow**
  ```
  [S]─Swap 1.0─▶[I]─Transfer 1.0─▶[AGG]─┬──Split 0.34──▶[B1]─Transfer 1.0─▶┐
                                        ├──Split 0.33──▶[B2]─Transfer 1.0─▶[T (mixer)]
                                        └──Split 0.33──▶[B3]─Transfer 1.0─▶┘
  ```
- **旗标** 🟠 **混币语义**：`T` 为 Tornado 沉淀（39 笔分批对应 3 批 B1-B3）· ✅ 分批中继保真（batch 结构吻合 39 txs）· ⚠️ 无 BRIDGE（Sonic→Ethereum 换币未建模跨链，需核对原文是否漏桥）。

---

## 11. full_loop_mixer_funding_exploit_batch_cashout
- **report_id** `rep_certik_013` · **事件** Cyrus Finance Incident
- **pattern** Multi_Layering_Split · **边/节点** 5/6 · **ScaleTier（建议）** Whale · **stage_boundary** 无
- **Ground-truth**：攻击者 EOA → Tornado Cash 存款：8 批×100 BNB + 1 批×10 BNB（首笔 0x3fb71a…）。
- **ASCII flow**
  ```
  [S]─Transfer 1.0─▶[I1]─Swap 1.0─▶[AC]─Transfer 1.0─▶[AGG]─┬──Split 0.99──▶[T1 (major batch)]
                                                             └──Split 0.01──▶[T2 (minor batch)]
  ```
- **旗标** 🟠 **混币语义**：`T1/T2` 为 Tornado 分批存款（0.99/0.01 对应 800 vs 10 BNB）· 🔴 **品类预警**：描述含「pool manipulation / liquidity extraction」（exploit），与洗钱 loop 合图，需裁定 exploit 段是否应剥离 · ✅ 0.99/0.01 非对称剥皮吻合实际比例。

---

## 12. cross_chain_pegout_split
- **report_id** `rep_blocksec_009` · **事件** Liquid Network（$320M 综合安全洞察中的 Liquid 段）
- **pattern** Chain_Hopping · **边/节点** 4/5 · **ScaleTier（建议）** State_Sponsored · **stage_boundary** 无
- **Ground-truth**：Liquid 链 peg-out 至 BTC，3,400 BTC 返还 federated 钱包，598.5 BTC 留存（BlockSec 明确「peg-out 返还不计入 ≥2 跳洗钱」）。
- **ASCII flow**
  ```
  [S]─Transfer 1.0─▶[I1]─Bridge 1.0─▶[CC]─┬──Split 0.8──▶[T_return]
                                           └──Split 0.2──▶[T_keep]
  ```
- **旗标** ⚪ BRIDGE（peg-out 属实）· 🔴 **重大品类预警**：evidence 明示「返还部分不计入洗钱」；本图将「返还」与「留存」并列建模为 cash-out 分流，**返还支路（0.8）非洗钱拓扑**，强烈建议裁定仅保留 `T_keep` 支路或将 `T_return` 移出 AML 语义。

---

## 13. cross_chain_mint_swap_bridge
- **report_id** `rep_blocksec_009` · **事件** Symbiosis（$320M 综合安全洞察中的 Symbiosis 段）
- **pattern** Chain_Hopping · **边/节点** 6/7 · **ScaleTier（建议）** Medium · **stage_boundary** 无
- **Ground-truth**：Symbiosis 伪造 mint 至 0x0251…（BlockSec 已排除 exploit mint），经 Uniswap v4 syBTC/WBTC 池换为 4.38897292 WBTC，收益随后流转至 ~137 ETH。
- **ASCII flow**
  ```
  [S]─Transfer 1.0─▶[I_portal]─Bridge 1.0─▶[CC1]─Transfer 1.0─▶[AC]─Swap 1.0─▶[I2]─Bridge 1.0─▶[CC2]─Transfer 1.0─▶[T]
  ```
- **旗标** ⚪ BRIDGE×2（跨 B→C→D 三链属实）· 🔴 **品类预警**：`forged mint` 是 exploit 源（BlockSec 已标注「excluded as exploit mint」），本图将 mint 归入 Source，与 #1/#2/#9 同类；需裁定是否应显式剥离 mint 节点。

---

## 汇总速览（供导师一页纸决策）

| # | Motif ID | 跨链 | 混币 | 品类预警 | 备注 |
|---|---|---|---|---|---|
| 1 | unified_illicit_mint_bridge_split_stream | ⚪ | — | 🔴 mint 混入 | slowmist_003 |
| 2 | unauthorized_issuance_bridge_split_cashout | ⚪ | — | 🔴 返还支路非洗钱 | certik_001 |
| 3 | cross_chain_bridge_to_mixer_exit | ⚪ | 🟠 | ⚠️ swap/bridge 时序 | certik_002 |
| 4 | cross_chain_swap_bridge_split_outflow | ⚪ | 🟠 | ✅ 割点 CC 已标 | certik_003 |
| 5 | drain_convert_split_mixer_cashout_campaign | — | 🟠 | ⚠️ AGG 语义 | certik_004 |
| 6 | bridge_swap_split_outflow | ⚪ | — | ✅ | certik_005 |
| 7 | cross_chain_exploit_exit_loop | ⚪ | 🟠 | ✅ | certik_007 |
| 8 | flash_loan_swap_manipulation_cashout | — | 🟠 | 🔴 flashloan 描述 | certik_008 |
| 9 | exploit_mint_swap_split_mixer_exit | — | 🟠 | 🔴 mint 表述存疑 | certik_011 |
| 10 | swap_inflation_batched_mixer_exit | — | 🟠 | ⚠️ 疑漏 Bridge | certik_012 |
| 11 | full_loop_mixer_funding_exploit_batch_cashout | — | 🟠 | 🔴 exploit 合图 | certik_013 |
| 12 | cross_chain_pegout_split | ⚪ | — | 🔴 返还支路非洗钱 | blocksec_009 |
| 13 | cross_chain_mint_swap_bridge | ⚪ | — | 🔴 mint 混入 | blocksec_009 |
