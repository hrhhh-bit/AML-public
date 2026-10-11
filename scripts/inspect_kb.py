"""
对新增的40个Motif知识库语义全景概览
"""

import json
from collections import Counter

raw = json.load(open("data/distilled_kb.json", encoding="utf-8"))
motifs = raw if isinstance(raw, list) else (raw.get("motifs") or [])
print(f"=== 知识库语义全景概览 (总数: {len(motifs)}) ===")

tactics = Counter((m.get("pattern_type") or "Unknown") for m in motifs)
tiers = Counter(t for m in motifs for t in (m.get("applicable_scale_tiers") or []))

def count_chains(m):
    nodes = m.get("nodes") or []
    chains = set(n.get("chain") for n in nodes if n.get("chain"))
    if chains:
        return len(chains)
    pre = m.get("preconditions") or {}
    req = pre.get("required_chains") or []
    return len(req)

chains = Counter(count_chains(m) for m in motifs)

print("【战术类型分布】:", dict(tactics))
print("【规模层级覆盖】:", dict(tiers))
print("【跨链复杂度 (跨链数: 频次)】:", dict(chains))
print("-" * 88)
print("%-38s | %-20s | %-11s | %s" % ("Motif ID", "Pattern Type", "Nodes/Edges", "Tiers"))
print("-" * 88)
for m in motifs:
    nodes = m.get("nodes") or []
    edges = m.get("edges") or []
    mid = (m.get("motif_id") or "")[:36]
    pt = (m.get("pattern_type") or "Unknown")[:18]
    ts = ",".join(m.get("applicable_scale_tiers") or [])
    print("%-38s | %-20s | %2dN / %2dE   | %s" % (mid, pt, len(nodes), len(edges), ts))
