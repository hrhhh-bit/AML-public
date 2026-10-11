【顶层架构任务令：阶段 3C —— 检索超参数集中解耦与 40-Motif 鲁棒性压力基准】

下游代码 Agent：
系统现已完成阶段 3 Part B 的全部实战扩容，40-Motif 知识库已就绪，存量测试已全面恢复至 339 项全绿（100% PASS）。
现正式下发阶段 3C 收尾任务包。本任务旨在完成超参数的集中外置解耦，并在 40 候选集的高密度场景下完成双轨检索鲁棒性对比评测，为阶段 4 消融实验建立无侵入参数插槽。

你必须严格恪守“自洽推导、自主通读源码、零破坏性重构、只读审计”的原则完成任务。

---

### 一、 核心架构任务与执行逻辑

#### Step 1：既有源码硬编码常量审计与自主抽取（重点）

在编写配置类之前，你必须首先通读以下核心模块的源码：

1. `aml_rag/retriever.py` 及相关检索模块（重点审计：双轨检索打分权重 α、粗筛剪枝窗口 coarse_k、Top-K 数量、默认向量模型名称、缓存开关等）；
2. `aml_env/` 下的状态机与 `hard_verifier.py`（重点审计：出度/分支度上限 d_max、最大图深度 L_max、流量守恒容差 tolerance 等）；
3. `aml_agent/` 下的规划器与客户端（重点审计：推理温度 temperature、反思重试上限 max_retries、默认模型名称等）。

【要求】：全面理清上述模块中实际使用的**变量命名、默认值及其在类构造函数中的传递方式**，将其按以下三大逻辑域归纳进统一配置体系，杜绝凭空捏造与既有代码冲突的字段名：

- `RetrievalConfig`（检索域）
- `TopologyConfig`（拓扑公理域）
- `AgentConfig`（规划代理域）

#### Step 2：集中化配置系统落地（方案 A：YAML + Dataclass）

1. 在 `aml_rag/config.py` 中实现强类型配置类 `AMLConfig`（及各子域 dataclass）；
2. 在工程根目录建立带清晰注释的标准模板 `config/default_config.yaml`，其默认值必须与你在 Step 1 审计出的**既有源码实际默认值 100% 逐位一致（Zero-Delta）**；
3. 支持从 YAML 文件无侵入加载并转换为 `AMLConfig` 对象。

#### Step 3：依赖注入与向前兼容重构（红线底线）

1. 重构相关类的构造函数（如 `HybridRetriever`、`HardVerifier`、`LLMPlanner` 等），增加可选配置形参（如 `config: Optional[AMLConfig] = None`）；
2. 【强向后兼容】：若调用方未显式传入 `config`，各组件内部必须透明加载默认配置，**严禁修改既有公开 API 的行为**；
3. 在 `tests/test_config.py` 中补充配置加载、动态覆盖与参数生效的单元测试；
4. 【硬性验收红线】：全量运行 `pytest`，确保原有的 **339 项存量测试无须修改任何既有断言，持续 100% 全绿**。

#### Step 4：40 候选集检索鲁棒性纵向对比评测

1. 升级 `scripts/eval_retrieval_correlation.py`：
   - 数据集扩展：构建“8 基础查询 + 4 新涌现查询（共 12 查询）”。8 基础查询严格沿用阶段 3A 定义（保障 1:1 纵向对比）；新增 4 查询需涵盖阶段 3B 涌现的复杂战术（如三链汇聚跳跃、合成资产跨链等）；
   - 候选集：动态加载当前的生产知识库 `data/distilled_kb.json`（40 个真实 Motif）；
   - 严守知识库只读安全红线：脚本运行前后必须比对知识库文件的 SHA-256 哈希，杜绝任何写盘污染；
2. 量化指标计算：
   - 计算 Dense vs. Discrete 的 Spearman 秩相关系数 (ρ) 与显著性 p-value；
   - 计算 Top-1 区分度裕量（Margin = Top1 - Top2 得分差值）；
   - 计算粗筛剪枝召回质量（coarse_k 剪枝是否无损覆盖精排 Top-3）；
   - 统计单次检索毫秒级延迟；
3. 输出与对比：
   - 结果写入 `experiments/phase3_dense_retrieval/dense_vs_discrete_correlation_40kb.json`；
   - 打印出“18 候选库 (Phase 3A) vs. 40 候选库 (Phase 3C)”的指标纵向对比表。

---

### 二、 交付验收汇报清单

执行完毕后，请向研究者汇报：

1. 审计出的核心常量清单（展示源码原名 $\to$ 配置类字段名的映射表）；
2. 单元测试回归状态（测试总数，确保 >= 339 且 0 failed）；
3. 40 候选集下的检索鲁棒性指标（平均 ρ、显著性达标率、Top-1 区分度裕量、延迟）；
4. 纵向对比核心结论（40 候选库相比 18 候选库，检索系统是否依然稳定）；
5. 交付物 `config/default_config.yaml` 与 `dense_vs_discrete_correlation_40kb.json` 的 SHA-256 哈希。
