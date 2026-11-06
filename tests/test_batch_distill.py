"""Stage-3 Part B：批量蒸馏调度器离线集成测试（零网络、零 Token）。

覆盖：
- PRISMA 定标：黄金研报必须恰好 14 篇；
- 基准防线冻结：备份缺失 / 哈希不一致时拒绝执行；
- API 安全契约：live 客户端严禁硬编码，严格经 DEEPSEEK_API_KEY 读取；
- dry-run 全流程：调度、流向原型分桶、Schema 反序列化、同构去重、
  隔离日志与四类交付产物落盘，且生产知识库零触碰。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import batch_distill as bd  # noqa: E402

PRODUCTION_KB = PROJECT_ROOT / "data" / "distilled_kb.json"
BASELINE_BACKUP = PROJECT_ROOT / "data" / "distilled_kb_v1.json"


# ---------------------------------------------------------------------------
# 定标与安全契约
# ---------------------------------------------------------------------------
def test_golden_reports_are_exactly_14() -> None:
    golden = bd.load_golden_reports(bd.DEFAULT_MANIFEST)
    assert len(golden) == 14
    ids = [r["report_id"] for r in golden]
    assert len(set(ids)) == 14


def test_live_client_requires_env_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        bd._build_live_client(None, 0.1, None, 30.0)


def test_baseline_freeze_rejects_missing_backup(tmp_path) -> None:
    kb = tmp_path / "kb.json"
    missing = tmp_path / "no_backup.json"
    with pytest.raises(RuntimeError, match="基准备份缺失"):
        bd.enforce_baseline_freeze(kb, missing)


def test_baseline_freeze_rejects_modified_baseline_motif(tmp_path) -> None:
    kb = tmp_path / "kb.json"
    backup = tmp_path / "backup.json"
    baseline = json.loads(BASELINE_BACKUP.read_text(encoding="utf-8"))
    backup.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    # 篡改一个基线 Motif：生产库不再是基线的忠实超集
    drifted = json.loads(json.dumps(baseline))
    drifted[0]["description"] = "TAMPERED BASELINE MOTIF"
    kb.write_text(json.dumps(drifted, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="被篡改"):
        bd.enforce_baseline_freeze(kb, backup)


def test_baseline_freeze_accepts_live_expanded_superset(tmp_path) -> None:
    kb = tmp_path / "kb.json"
    backup = tmp_path / "backup.json"
    baseline = json.loads(BASELINE_BACKUP.read_text(encoding="utf-8"))
    backup.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    extra = {
        "motif_id": "extra_after_live",
        "pattern_type": "Peeling_Chain",
        "description": "extra motif added by --live",
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 1},
        ],
        "edges": [{"source": "S", "target": "T", "operation": "Transfer"}],
    }
    kb.write_text(json.dumps(baseline + [extra], ensure_ascii=False), encoding="utf-8")
    # 生产库是基线的合法超集：冻结校验应放行
    assert bd.enforce_baseline_freeze(kb, backup)


# ---------------------------------------------------------------------------
# dry-run 端到端
# ---------------------------------------------------------------------------
@pytest.fixture()
def isolated_kb(tmp_path):
    """隔离沙箱：工作库与基准备份均以 distilled_kb_v1.json（18 Motif 基准）

    初始化，保证两者哈希一致，可合规通过 ``enforce_baseline_freeze`` 门禁。
    生产知识库经 --live 扩容后（40 Motif）哈希已变，若沙箱工作库直接拷贝
    生产库而备份拷贝 v1，将因哈希不一致触发冻结门禁误伤。
    """
    kb = tmp_path / "distilled_kb.json"
    backup = tmp_path / "distilled_kb_v1.json"
    shutil.copyfile(BASELINE_BACKUP, kb)
    shutil.copyfile(BASELINE_BACKUP, backup)
    assert bd.sha256_hex(kb) == bd.sha256_hex(backup)
    return kb, backup


def _run_dry_run(isolated_kb, out_dir, **overrides) -> dict:
    kb, backup = isolated_kb
    return bd.run_pipeline(
        "dry-run",
        kb_path=kb,
        backup_path=backup,
        out_dir=out_dir,
        **overrides,
    )


def test_dry_run_end_to_end(isolated_kb, tmp_path) -> None:
    kb, backup = isolated_kb
    prod_hash_before = bd.sha256_hex(PRODUCTION_KB)
    out_dir = tmp_path / "phase3_batch_distillation" / "dry_run"

    report = _run_dry_run(isolated_kb, out_dir)

    # ---- 四类交付产物 + 隔离日志齐备 -----------------------------------
    for name in (
        "meta_config.txt",
        "distillation_report.json",
        "saturation_curve.json",
        "sample_extracted_motifs.json",
        "quarantine_log.json",
    ):
        assert (out_dir / name).exists(), name

    # ---- 生产知识库零触碰 ------------------------------------------------
    assert bd.sha256_hex(PRODUCTION_KB) == prod_hash_before
    assert not report["production_kb_updated"]

    # ---- Check 1 合法率 >= 90% ------------------------------------------
    assert report["check1_legality"]["passed"]
    assert report["check1_legality"]["pass_rate"] >= bd.MIN_CHECK1_RATE

    # ---- Check 3 零噪声扫描必须为 0 --------------------------------------
    assert report["check3_zero_noise"]["passed"]
    assert report["check3_zero_noise"]["extracted_residues"] == 0

    # ---- Check 4 饱和度曲线：14 篇时序数据点 -----------------------------
    curve = json.loads((out_dir / "saturation_curve.json").read_text("utf-8"))
    assert len(curve) == 14
    first, last = curve[0], curve[-1]
    assert set(first) == {
        "report_id", "extracted", "deduplicated", "net_added", "cumulative_total",
    }
    assert last["cumulative_total"] == report["final_motif_count"]

    # ---- 扩容 + 隔离 -----------------------------------------------------
    assert report["final_motif_count"] > 18
    assert report["net_added"] >= 1
    assert report["quarantine_count"] == 2

    # ---- 账本公理穿透审计 -------------------------------------------------
    assert report["ledger_audit"]["clean"]

    # ---- 样例 Motif：必须沉淀且零噪声 -------------------------------------
    samples = json.loads(
        (out_dir / "sample_extracted_motifs.json").read_text("utf-8")
    )
    assert 1 <= len(samples) <= 3
    for sample in samples:
        assert "motif_id" in sample
        assert "flow_prototype_profile" in sample
        assert "edge_action_basis" in sample

    # ---- meta_config 关键字段 --------------------------------------------
    meta = (out_dir / "meta_config.txt").read_text(encoding="utf-8")
    assert "model=deepseek-flash" in meta
    assert "temperature=0.1" in meta
    assert "report_ids=" in meta
    assert "baseline_sha256=" in meta


def test_dry_run_needs_no_api_key(isolated_kb, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = _run_dry_run(isolated_kb, tmp_path / "out")
    assert report["mode"] == "dry-run"
    # 零 Token：dry-run 不产生任何真实 API 调用账单
    assert report["token_and_latency"]["prompt_tokens"] == 0
    assert report["token_and_latency"]["completion_tokens"] == 0


# ---------------------------------------------------------------------------
# Prompt v2 离线装配导出（--dump-prompts）
# ---------------------------------------------------------------------------
def test_dump_prompts_exports_14_assembled_files(tmp_path) -> None:
    files = bd.dump_prompts(tmp_path)
    assert len(files) == 14
    names = {f.name for f in files}
    assert "rep_slowmist_002_prompt.md" in names

    content = (tmp_path / "rep_slowmist_002_prompt.md").read_text(encoding="utf-8")
    # 资金链遥测注意力锚点已注入（v2.2：仅宏观跳数 + 语义标记）
    assert "ATTENTION ANCHOR" in content
    assert "hops_detected" in content
    assert "evidence_chain" not in content
    assert "CAUSAL FIDELITY" in content
    # 双阶段 Schema 约束与实体接地边界
    assert "phase_a_inflow_motifs" in content
    assert "phase_b_outflow_motifs" in content
    assert "grounded_chains" in content
    # 负向防幻觉反例
    assert "REJECTED: Hallucinated Intermediate Relay Chain/Node" in content


def test_dump_prompts_needs_no_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    files = bd.dump_prompts(tmp_path)
    assert len(files) == 14
