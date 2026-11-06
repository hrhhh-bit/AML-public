import argparse
import json
import os
import textwrap
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import networkx as nx

# 颜色与样式配置
ROLE_COLORS = {
    "Source": "#2ecc71",       # 绿色
    "Intermediate": "#3498db", # 蓝色
    "Aggregator": "#e67e22",   # 橙色
    "Cross_Chain": "#9b59b6",  # 紫色
    "Target": "#e74c3c",       # 红色
}

CHAIN_EDGE_COLORS = {
    "Chain_A": "#1f77b4",
    "Chain_B": "#ff7f0e",
    "Chain_C": "#2ca02c",
}

OPERATION_STYLES = {
    "Transfer": {"color": "#555555", "linestyle": "-", "width_mult": 1.5},
    "Split":    {"color": "#2980b9", "linestyle": "-", "width_mult": 1.5},
    "Merge":    {"color": "#d35400", "linestyle": "-", "width_mult": 1.5},
    "Bridge":   {"color": "#8e44ad", "linestyle": "--", "width_mult": 2.2},  # 跨链桥虚线突出显示
}


def parse_args():
    parser = argparse.ArgumentParser(description="绘制资金流转拓扑图")
    parser.add_argument(
        "-i", "--input", 
        type=str, 
        required=True, 
        help="输入的 JSON 文件路径，例如: data.json"
    )
    parser.add_argument(
        "-o", "--output_dir", 
        type=str, 
        default="img", 
        help="图表保存的目标文件夹，默认为 img/"
    )
    return parser.parse_args()


def load_data(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"未找到输入文件: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_layout(nodes_data):
    """
    根据节点的 level 和 chain 分配坐标：
    X 轴表示 Level（资金流动推进），Y 轴根据链和节点数量垂直均匀分布。
    """
    level_groups = defaultdict(list)
    for node in nodes_data:
        level_groups[node.get("level", 0)].append(node)

    pos = {}
    x_scale = 3.5
    y_scale = 2.0

    for level, nodes in level_groups.items():
        # 同一层内按 chain 排序，避免跨链混杂
        nodes.sort(key=lambda n: (n.get("chain", ""), n.get("id", "")))
        k = len(nodes)
        for idx, node in enumerate(nodes):
            # 将同 level 的节点垂直居中排布
            y = (idx - (k - 1) / 2.0) * y_scale
            x = level * x_scale
            pos[node["id"]] = (x, y)

    return pos


def draw_graph(data, output_path):
    meta = data.get("meta", {})
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    node_dict = {n["id"]: n for n in nodes}
    pos = calculate_layout(nodes)

    fig, ax = plt.subplots(figsize=(20, 11), dpi=300)

    # 1. 绘制边（带箭头和标签）
    for edge in edges:
        u, v = edge["source"], edge["target"]
        if u not in pos or v not in pos:
            continue

        p1, p2 = pos[u], pos[v]
        op = edge.get("operation", "Transfer")
        share = edge.get("flow_share", 1.0)
        style = OPERATION_STYLES.get(op, {"color": "#666666", "linestyle": "-", "width_mult": 1.0})

        # 连线宽度与 flow_share 关联，最小 1.0
        line_width = max(1.0, share * 2.8 * style["width_mult"])

        # 绘制带弧度与箭头的连线
        arrow = FancyArrowPatch(
            p1, p2,
            arrowstyle="-|>",
            mutation_scale=14,
            connectionstyle="arc3,rad=0.08",
            color=style["color"],
            linestyle=style["linestyle"],
            linewidth=line_width,
            alpha=0.85,
            zorder=2
        )
        ax.add_patch(arrow)

        # 边标签：显示操作类型及比例
        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0
        # 适当抬高标签位置避免盖住连线
        label_y_offset = 0.12 if p1[1] <= p2[1] else -0.12
        share_text = f"{int(share * 100)}%" if share < 1.0 else "100%"
        ax.text(
            mid_x, mid_y + label_y_offset,
            f"{op}\n({share_text})",
            fontsize=7,
            color=style["color"],
            ha="center", va="center",
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.85),
            zorder=3
        )

    # 2. 绘制节点
    for node in nodes:
        nid = node["id"]
        role = node.get("role", "Intermediate")
        chain = node.get("chain", "Unknown")
        x, y = pos[nid]

        fill_color = ROLE_COLORS.get(role, "#95a5a6")
        border_color = CHAIN_EDGE_COLORS.get(chain, "#333333")

        # 绘制节点外框与填充（用粗边框颜色表示 Chain，填充色表示 Role）
        bbox_props = dict(
            boxstyle="round,pad=0.4",
            facecolor=fill_color,
            edgecolor=border_color,
            linewidth=2.5,
            alpha=0.95
        )
        label_text = f"{nid}\n[{role}]\n({chain})"
        ax.text(
            x, y,
            label_text,
            ha="center", va="center",
            fontsize=8,
            fontweight="bold",
            color="white" if role in ["Aggregator", "Target", "Cross_Chain"] else "#222222",
            bbox=bbox_props,
            zorder=4
        )

    # 3. 顶部信息面板（Meta 信息）
    val_usd = meta.get("estimated_value_usd", 0)
    meta_summary = (
        f"Tier: {meta.get('scale_tier', 'N/A')}  |  "
        f"Est. Value: ${val_usd:,.2f} USD  |  "
        f"Nodes: {meta.get('node_count', len(nodes))}  |  "
        f"Edges: {meta.get('edge_count', len(edges))}  |  "
        f"Steps: {meta.get('steps', 'N/A')}  |  "
        f"Seed: {meta.get('seed_chain', 'N/A')}  |  "
        f"Terminated By: {meta.get('terminated_by', 'N/A')}"
    )

    narrative = meta.get("strategy_narrative", "")
    wrapped_narrative = "\n".join(textwrap.wrap(f"Narrative: {narrative}", width=135))

    # 添加主标题与信息盒
    plt.title(
        "Transaction Flow & Strategy Topology",
        fontsize=16, fontweight="bold", pad=40, loc="left", color="#2c3e50"
    )
    fig.text(
        0.05, 0.94, meta_summary,
        fontsize=9, fontweight="bold", color="#34495e"
    )
    if narrative:
        fig.text(
            0.05, 0.90, wrapped_narrative,
            fontsize=8, color="#555555", style="italic"
        )

    # 4. 图例 (Legends)
    legend_elements = []
    # Role 图例
    legend_elements.append(mpatches.Patch(color="none", label="-- Role (Fill) --"))
    for r, c in ROLE_COLORS.items():
        legend_elements.append(mpatches.Patch(facecolor=c, edgecolor="none", label=r))

    # Chain 图例
    legend_elements.append(mpatches.Patch(color="none", label="-- Chain (Border) --"))
    for ch, c in CHAIN_EDGE_COLORS.items():
        legend_elements.append(mpatches.Patch(facecolor="white", edgecolor=c, linewidth=2, label=ch))

    # Operation 图例
    legend_elements.append(mpatches.Patch(color="none", label="-- Operation --"))
    for op, sty in OPERATION_STYLES.items():
        legend_elements.append(
            plt.Line2D([0], [0], color=sty["color"], linestyle=sty["linestyle"], lw=2, label=op)
        )

    ax.legend(
        handles=legend_elements,
        loc="upper right",
        bbox_to_anchor=(1.0, 1.02),
        fontsize=7,
        framealpha=0.9,
        ncol=3
    )

    # 坐标范围调整
    all_x = [p[0] for p in pos.values()]
    all_y = [p[1] for p in pos.values()]
    ax.set_xlim(min(all_x) - 1.5, max(all_x) + 1.5)
    ax.set_ylim(min(all_y) - 1.5, max(all_y) + 1.5)
    ax.axis("off")

    plt.tight_layout(rect=[0, 0, 1, 0.88])
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"✅ 图表已生成并保存在: {output_path}")


def main():
    args = parse_args()

    # 自动创建目标 img 文件夹
    os.makedirs(args.output_dir, exist_ok=True)

    # 读取 JSON 数据
    data = load_data(args.input)

    # 决定输出文件名
    base_name = os.path.splitext(os.path.basename(args.input))[0]
    output_filename = f"{base_name}_topology.png"
    output_path = os.path.join(args.output_dir, output_filename)

    # 绘图
    draw_graph(data, output_path)


if __name__ == "__main__":
    main()

# 输入示例: python visualize_flow.py -i "D:\projects\crypto_data\2024_whale.json"