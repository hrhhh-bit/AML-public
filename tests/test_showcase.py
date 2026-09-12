"""展示脚本的可见性测试：验证每个阶段的产物都能被生成且内容完整。

本测试把 `demo/showcase_stage1.py` 当作可复用的产物生成器，
在临时目录中完整跑一遍六个阶段，并断言关键产物存在、内容合法。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = PROJECT_ROOT / "demo"
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

import showcase_stage1 as demo  # noqa: E402


def test_showcase_generates_all_stage_artifacts(tmp_path: Path) -> None:
    out_dir = tmp_path / "showcase"
    traj, files = demo.build_all_artifacts(out_dir)

    # --- 全部 6 个阶段的入口文件都应存在 --------------------------------
    names = {f.name for f in files}
    for expected in (
        "00_知识库总览.md",
        "02_双轨检索.md",
        "03_先验提示词压缩.md",
        "05_最终行为图.md",
        "README.md",
        "graph.json",
    ):
        assert expected in names, f"缺少产物: {expected}"

    # --- Stage 0: 12 个种子 Motif 全部渲染成 Mermaid --------------------
    overview = (out_dir / "00_知识库总览.md").read_text(encoding="utf-8")
    assert overview.count("flowchart LR") == 12
    assert "Peeling_Chain_Single_Chain" in overview

    # --- Stage 1: 蒸馏管线三件套 ----------------------------------------
    stage1 = out_dir / "01_蒸馏管线"
    assert (stage1 / "distillation_prompt.txt").exists()
    parsed = json.loads((stage1 / "parsed_motif.json").read_text(encoding="utf-8"))
    assert len(parsed) == 1
    motif = parsed[0]
    assert motif["pattern_type"] == "Peeling_Chain"
    # 零微观数字噪音：蒸馏产物中不允许出现地址/金额噪音
    prompt_text = (stage1 / "distillation_prompt.txt").read_text(encoding="utf-8")
    assert "0x7a2f" not in json.dumps(parsed, ensure_ascii=False)

    # --- Stage 2: 双轨检索报告含门控判决与打分 ---------------------------
    stage2 = (out_dir / "02_双轨检索.md").read_text(encoding="utf-8")
    assert "硬规则门" in stage2 and "PASS" in stage2
    assert "Score" in stage2 and "semantic" in stage2

    # --- Stage 3: 压缩先验块包含 MOT 三元组与 Mermaid --------------------
    stage3 = (out_dir / "03_先验提示词压缩.md").read_text(encoding="utf-8")
    assert "<MOTIFS>" in stage3 and "flowchart LR" in stage3

    # --- Stage 4: 逐步提示词与动作一一对应 -------------------------------
    stage4_dir = out_dir / "04_决策循环"
    step_prompts = sorted(stage4_dir.glob("step_*_prompt.txt"))
    step_actions = sorted(stage4_dir.glob("step_*_action.json"))
    assert len(step_prompts) == 6 and len(step_actions) == 6
    # 每个规划提示词都必须携带 RAG 先验块
    for p in step_prompts:
        text = p.read_text(encoding="utf-8")
        assert "<RAG_PRIOR>" in text and "<OUTPUT_FORMAT>" in text

    # --- 轨迹审计字段完整、决策成功 ---------------------------------------
    traj_json = json.loads((stage4_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert traj_json["success"] is True
    assert traj_json["terminated_by"] == "agent_terminate"
    assert traj_json["unmet_goals"] == []
    assert all(s["prior_motif_ids"] for s in traj_json["steps"])
    # 高分支压力下应有至少一步触发"先验保障软回退"
    assert any(s["prior_soft_fallback"] for s in traj_json["steps"])

    # --- Stage 5: 最终决策图合法 ------------------------------------------
    stage5 = (out_dir / "05_最终行为图.md").read_text(encoding="utf-8")
    assert "flowchart LR" in stage5 and "agent_terminate" in stage5
    graph = json.loads((out_dir / "graph.json").read_text(encoding="utf-8"))
    assert graph["meta"]["node_count"] == 7
    assert graph["meta"]["edge_count"] == 7
    assert traj.success is True
