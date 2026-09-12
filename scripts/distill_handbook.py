"""Stage-2: distill the Crypto-Asset-Tracing Handbook & run the four checks.

One-shot pipeline:
1. distill the handbook (format-agnostic chunking + reflection repair);
2. run the four empirical checks (topology validity, cross-source
   consistency, zero-noise audit, saturation analysis);
3. safely merge validated motifs into the knowledge base and persist.

Usage:
    python scripts/distill_handbook.py [--input resources/Crypto-Asset-Tracing-Handbook]
                                       [--out-dir output]

Environment:
    DEEPSEEK_API_KEY  (or OPENAI_API_KEY) — required
    DEEPSEEK_BASE_URL — optional
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aml_agent import LLMClient  # noqa: E402
from aml_rag import (  # noqa: E402
    MotifDistiller,
    build_default_knowledge_base,
    cross_source_consistency,
    saturation_analysis,
    topology_validity,
    zero_noise_audit,
)

# Two short, differently-worded descriptions of the SAME pattern (Peel Chain),
# used to demonstrate the cross-source consistency framework on a single
# handbook. In production these would be distinct vendor reports (e.g.
# Chainalysis vs. Elliptic) describing the same incident / typology.
SOURCE_A = (
    "Peel Chain: a dirty address sends the bulk of its balance onward through a "
    "long chain of small, rapid transfers, peeling off a tiny fraction at each "
    "hop so that the main value keeps moving to fresh addresses."
)
SOURCE_B = (
    "Peeling: funds flow linearly across many single-use intermediary wallets; "
    "at every step a small share is stripped off to a side wallet while the "
    "majority continues to the next hop, until the trail fades."
)


def _dump(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Distill handbook & run four checks")
    parser.add_argument(
        "--input", default=str(PROJECT_ROOT / "resources" / "Crypto-Asset-Tracing-Handbook"),
        help="Path to the report text (default: the SlowMist handbook)",
    )
    parser.add_argument("--out-dir", default="output_distill", help="Output directory")
    parser.add_argument("--model", default=None, help="Model name (default: deepseek-flash)")
    parser.add_argument("--base-url", default=None, help="API base URL override")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout (s)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report_text = Path(args.input).read_text(encoding="utf-8")
    client = LLMClient(model=args.model, base_url=args.base_url, timeout=args.timeout)
    distiller = MotifDistiller(client)

    print(f"== distilling {args.input} (model={client.model}) ==")
    result = distiller.distill(report_text)
    print(f"chunks={result.chunks} motifs={len(result.motifs)} "
          f"failures={len(result.failures)}")

    # ---- check 1: topology validity --------------------------------------
    validity = topology_validity(result.motifs)

    # ---- check 2: cross-source consistency (demo double source) -----------
    source_a = distiller.distill(SOURCE_A).motifs
    source_b = distiller.distill(SOURCE_B).motifs
    consistency = cross_source_consistency({"source_a": source_a, "source_b": source_b})

    # ---- check 3: zero-noise audit ----------------------------------------
    noise = zero_noise_audit(result.motifs)

    # ---- check 4: saturation analysis -------------------------------------
    saturation = saturation_analysis(result.chunk_motifs)

    # ---- safe ingest ------------------------------------------------------
    kb = build_default_knowledge_base()
    ingest = kb.merge_motifs(result.motifs)
    kb_path = out_dir / "distilled_kb.json"
    kb.save(kb_path)

    # ---- report -----------------------------------------------------------
    report: dict[str, Any] = {
        "input": args.input,
        "chunks": result.chunks,
        "motifs_distilled": len(result.motifs),
        "distillation_failures": [f.model_dump() for f in result.failures],
        "check1_topology_validity": validity.model_dump(),
        "check2_cross_source_consistency": consistency.model_dump(),
        "check3_zero_noise_audit": noise.model_dump(),
        "check4_saturation_analysis": [p.model_dump() for p in saturation],
        "ingest": ingest.model_dump(),
        "kb_size_after_ingest": len(kb),
    }
    report_path = out_dir / "distillation_report.json"
    _dump(report, report_path)

    # ---- console summary ---------------------------------------------------
    print("\n== empirical verification report ==")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nArtifacts: {report_path}  {kb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
