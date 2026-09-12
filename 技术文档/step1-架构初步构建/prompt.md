这里为你量身定制了一套**生产级、系统化的 VS Code Copilot 提示词（Copilot Prompt）**。

你可以直接将其**完整复制**并粘贴到 VS Code 的 Copilot Chat（建议开启 `@workspace` 或 Agent 模式）中。该提示词采用了严格的认知分块（Cognitive Chunking）、角色锚定、结构化契约与分步交付机制，能够最大化激发 Copilot 的代码生成与架构能力，避免幻觉并直接生成可运行的工程代码。

---

```markdown
# Role & Global Context

You are a Senior AI Architect and Principal Python Engineer specializing in Graph Neural Systems, GraphRAG, and Anti-Money Laundering (AML) topology generation.

We are developing **Module 1: AML Topological Prior Knowledge Base & Dual-Track RAG System** for a two-stage Cross-Chain AML Behavioral Graph Generation framework.

### System Paradigm (Stage 1 vs. Stage 2)

- **Stage 1 (Macro Behavioral Decision):** RAG-enhanced LLM Agent interacts iteratively with a lightweight Environment to generate an abstract money laundering Behavioral Graph ($G_b$) adhering to Directed Acyclic Graph (DAG) constraints.
- **Stage 2 (Micro-distribution Diffusion - Out of Scope for now):** Conditional Graph Diffusion model fills continuous/discrete features (exact amounts, timestamps, gas, addresses) onto $G_b$.

---

# Module 1 Objective & Core Philosophy

Module 1 serves as the **Prior Knowledge Engine** for the Stage 1 Agent. It provides topology-level sub-graph motifs and state-transition priors extracted from real-world security reports (e.g., Chainalysis, Elliptic).

### Crucial Design Rules:

1. **Zero Micro-Numerical Noise:** Completely strip out specific wallet addresses (e.g., `0x71C...`), exact amounts ($50k), gas fees, and timestamps.
2. **Pure Topological Abstraction:** Only model abstract roles, cross-chain states, DAG step levels, and abstract actions.
3. **No Over-engineered GNNs for Retrieval:** Use lightweight **Rule-based Precondition Filtering + Dense Semantic Vector Search** (Cosine Similarity) instead of heavy Graph Neural Networks.

---

# Data Contract & Schema Specifications

### 1. Abstract Node Roles & Edge Actions

- **Node Types ($V_{abstract}$):** `Source`, `Intermediate`, `Asset_Conversion`, `Cross_Chain`, `Aggregator`, `Target`
- **Edge Operations ($E_{abstract}$):** `Transfer`, `Swap`, `Bridge`, `Split`, `Merge`

### 2. Tri-Layer Knowledge Schema

- **Tactic Layer:** High-level AML strategy (`Peeling_Chain`, `Chain_Hopping`, `Multi_Layering_Split`, `Token_Obfuscation`, `Integration_Merge`).
- **Motif Subgraph Layer:** Canonical DAG pattern with preconditions, local node/edge structure, and post-state transition expectations.
- **Constraint Layer:** Hard limits on maximum branching factor ($d_{max}$), DAG acyclicity checks, and step intervals $[L_{min}, L_{max}]$.

---

# Target Codebase Architecture to Implement

Please construct the complete Python package for Module 1 under `src/aml_rag/`:
```

src/aml_rag/
├── **init**.py
├── schema.py # Pydantic models for Nodes, Edges, MotifSubgraphs, State, QueryContext
├── storage.py # In-memory / JSON / Vector-ready Motif Knowledge Base
├── extractor.py # LLM-based Distillation Prompt & Parser (Converts raw case text into Motifs)
├── retriever.py # Dual-Track Retriever (Hard Precondition Filter + Dense Semantic Match)
├── context_builder.py # Formats retrieved Motifs into compact Agent Prompts (JSON/Mermaid DAG)
└── mock_data.py # 10+ standard production-grade AML topological motifs (Peeling, Bridge Swap, etc.)

```

---

# Step-by-Step Implementation Requirements

Please execute the implementation sequentially. Follow strict type hints (`typing`), `pydantic v2`, and production-grade software engineering standards.

### Step 1: `schema.py`
Define robust Pydantic schemas:
- `NodeRole` (Enum), `OperationType` (Enum), `PatternType` (Enum)
- `AbstractNode` (`temp_id`, `role`, `chain`, `level`)
- `AbstractEdge` (`source`, `target`, `operation`)
- `Preconditions` (`min_level`, `allowed_node_roles`, `required_chains`, `max_active_branches`)
- `PostStateEffect` (`branch_increment`, `chain_transition`, `next_recommended_roles`)
- `TopologicalMotif` (`motif_id`, `pattern_type`, `description`, `preconditions`, `nodes`, `edges`, `post_state_effect`)
- `CurrentState` (`current_level`, `current_chain`, `active_nodes`, `graph_history`)

### Step 2: `mock_data.py`
Provide a curated seed database containing at least **6 diverse, representative AML motifs**:
1. `Peeling_Chain_Single_Chain` (Fast linear peeled transfers)
2. `Cross_Chain_Swap_Bridge` (Swap to stablecoin -> Bridge to target chain)
3. `Multi_Split_Obfuscation` (1-to-N splitting across intermediate nodes)
4. `Multi_Chain_Hop_Layering` (Hop across 3 distinct chains A -> B -> C)
5. `Aggregation_Merge_To_Target` (N-to-1 merge into Aggregator -> Target)
6. `DEX_Liquidity_Pool_Swap` (Asset conversion via decentralized pool)

### Step 3: `retriever.py`
Implement `DualTrackMotifRetriever`:
- **Track 1 (Hard Rule/Precondition Gate):** Filters candidate motifs where current `State` violates `min_level`, active node roles, or chain compatibility.
- **Track 2 (Semantic Matching):** Uses OpenAI/Sentence-Transformer text embeddings (or mock vector embeddings) to rank remaining candidates based on cosine similarity with `Scenario` + `Tactic Goal`.
- Include parameter $\alpha$ balancing score weights and top-$K$ selection.

### Step 4: `context_builder.py`
Implement `PromptContextCompressor`:
- Serialize retrieved Motifs into token-efficient JSON and optional **Mermaid DAG syntax** so LLM Agent can clearly read the topological direction.
- Compress redundant paths and order by execution sequence.

### Step 5: Unit Tests & Verification
Provide `test_rag_pipeline.py` testing:
1. Pydantic validation on all seed motifs.
2. Dual-track retrieval accuracy under specific mock `CurrentState` queries.
3. Successful generation of the Agent-ready prompt string.

---

# Execution Instruction
Start by outputting **Step 1 (`schema.py`)** and **Step 2 (`mock_data.py`)**. Ensure all code is copy-paste ready, fully typed, and robust. 以后的对话用中文进行。
```

---

### 💡 Copilot 交互使用建议：

1. **第一轮对话**：把上面的整段 Prompt 发给 Copilot，它会先为你创建数据结构骨架（`schema.py`）和标准的洗钱模式种子库（`mock_data.py`）。
2. **后续推进**：当 Copilot 输出完 Step 1 和 Step 2 后，你只需回复：
   > _"Approved. Now proceed with Step 3 (`retriever.py`) and Step 4 (`context_builder.py`), ensuring the dual-track filter logic matches the Pydantic schema precisely."_
3. **完成闭环**：最后让 Copilot 生成 Step 5 的测试用例，即可快速在本地 VS Code 运行并验证检索闭环。
