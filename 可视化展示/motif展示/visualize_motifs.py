import os
import re
import json
import textwrap

# 1. 强制在无界面的后台模式 (Agg) 运行，大幅提升速度并防止内存泄漏卡死
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

# 节点角色对应颜色板
ROLE_COLORS = {
    "Source": "#4CAF50",           # 绿色
    "Aggregator": "#FF9800",       # 橙色
    "Target": "#2196F3",           # 蓝色
    "Mixer": "#9C27B0",            # 紫色
    "Intermediary": "#607D8B",     # 灰蓝
    "Cross_Chain": "#00BCD4",      # 青色
    "Asset_Conversion": "#E91E63", # 玫红
}
DEFAULT_NODE_COLOR = "#78909C"

def sanitize_filename(name):
    """去除文件名中不合法的字符"""
    return re.sub(r'[\\/*?:"<>|]', '_', str(name))

def load_all_motifs(json_input_path):
    """从单个 JSON 文件（或包含该文件的目录）读取所有 motif 数据"""
    if os.path.isdir(json_input_path):
        json_files = [f for f in os.listdir(json_input_path) if f.endswith('.json')]
        if not json_files:
            raise FileNotFoundError(f"目录 '{json_input_path}' 中未找到 .json 文件！")
        json_input_path = os.path.join(json_input_path, json_files[0])

    print(f"[*] 正在读取文件: {json_input_path}")
    with open(json_input_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    
    if content.endswith(","):
        content = content[:-1].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = json.loads(f"[{content}]")

    if isinstance(data, dict):
        for key in ["motifs", "patterns", "data", "items"]:
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return data

def draw_single_motif(data, output_path, index_num=1):
    """绘制单个 Motif 的拓扑网络图（增加离散坐标映射与尺寸钳制）"""
    motif_id = data.get("motif_id", f"pattern_{index_num}")
    pattern_type = data.get("pattern_type", "Unknown_Type")
    description = data.get("description", "")
    tags = data.get("tags", [])
    nodes_info = data.get("nodes", [])
    edges_info = data.get("edges", [])

    # 1. 建立有向图
    G = nx.DiGraph()
    node_role_map = {}
    node_chain_map = {}
    node_level_map = {}

    for n in nodes_info:
        nid = str(n.get("temp_id", ""))
        role = n.get("role", "Unknown")
        # 兼容 level 可能为字符串或非数字的情况
        raw_lvl = n.get("level", 0)
        try:
            level = int(raw_lvl)
        except (ValueError, TypeError):
            level = 0
            
        chain = str(n.get("chain", ""))
        
        G.add_node(nid, role=role, level=level, chain=chain)
        node_role_map[nid] = role
        node_chain_map[nid] = chain
        node_level_map[nid] = level

    edge_labels = {}
    for e in edges_info:
        src = str(e.get("source", ""))
        tgt = str(e.get("target", ""))
        op = str(e.get("operation", ""))
        flow = e.get("flow_share", None)
        
        if flow is not None:
            try:
                share_str = f"{int(float(flow) * 100)}%"
            except (ValueError, TypeError):
                share_str = str(flow)
            label_text = f"{op}\n({share_str})" if op else share_str
        else:
            label_text = op

        edge_labels[(src, tgt)] = label_text
        G.add_edge(src, tgt)

    # 2. 离散化重映射 Level（防止 level=1000 导致绘图坐标爆炸）
    levels = {}
    for nid, lvl in node_level_map.items():
        levels.setdefault(lvl, []).append(nid)

    sorted_distinct_lvls = sorted(levels.keys())
    lvl_to_rank = {lvl: idx for idx, lvl in enumerate(sorted_distinct_lvls)}

    pos = {}
    max_nodes_in_a_level = max([len(v) for v in levels.values()]) if levels else 1
    num_levels = max(len(sorted_distinct_lvls), 1)

    for lvl, node_list in levels.items():
        rank_x = lvl_to_rank[lvl] * 2.8
        k = len(node_list)
        for idx, nid in enumerate(node_list):
            y = (idx - (k - 1) / 2.0) * -1.6
            pos[nid] = (rank_x, y)

    # 兜底节点
    for n in G.nodes():
        if n not in pos:
            pos[n] = (0.0, 0.0)

    # 3. 动态且有上限约束的画布大小（防止图片过大导致编码卡死）
    fig_w = max(9.0, min(16.0, num_levels * 2.6))
    fig_h = max(6.0, min(12.0, max_nodes_in_a_level * 1.3))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=140)

    # 计算全局边界，防止自动排版越界
    all_x = [p[0] for p in pos.values()] if pos else [0]
    all_y = [p[1] for p in pos.values()] if pos else [0]
    ax.set_xlim(min(all_x) - 1.5, max(all_x) + 1.5)
    ax.set_ylim(min(all_y) - 1.5, max(all_y) + 1.5)

    # 4. 绘制连线
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        arrowstyle="-|>",
        arrowsize=16,
        edge_color="#78909C",
        width=1.8,
        node_size=2400,
        connectionstyle="arc3,rad=0.05"
    )

    # 绘制边标签
    nx.draw_networkx_edge_labels(
        G, pos, edge_labels=edge_labels, ax=ax,
        font_size=8,
        font_color="#263238",
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#ECEFF1", edgecolor="#CFD8DC", alpha=0.9)
    )

    # 5. 绘制节点
    node_colors = [ROLE_COLORS.get(node_role_map.get(n), DEFAULT_NODE_COLOR) for n in G.nodes()]
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_size=2300,
        node_color=node_colors,
        edgecolors="#263238",
        linewidths=1.5,
        alpha=0.95
    )

    labels = {n: f"{n}\n[{node_chain_map.get(n, '')}]" if node_chain_map.get(n) else str(n) for n in G.nodes()}
    nx.draw_networkx_labels(
        G, pos, labels=labels, ax=ax,
        font_size=8.5,
        font_weight="bold",
        font_color="#FFFFFF"
    )

    # 6. 顶部标题与描述
    title_text = f"[{index_num:02d}] {motif_id} ({pattern_type})"
    plt.suptitle(title_text, fontsize=12.5, fontweight="bold", y=0.98)

    wrapped_desc = "\n".join(textwrap.wrap(description, width=90))
    ax.set_title(wrapped_desc, fontsize=9.0, color="#546E7A", pad=12, style="italic")

    # 7. 图例
    present_roles = sorted(list(set(node_role_map.values())))
    legend_handles = [
        mpatches.Patch(color=ROLE_COLORS.get(r, DEFAULT_NODE_COLOR), label=r)
        for r in present_roles
    ]
    if legend_handles:
        ax.legend(
            handles=legend_handles,
            title="Node Roles",
            loc="upper right",
            bbox_to_anchor=(1.02, 1.05),
            frameon=True,
            facecolor="#FAFAFA",
            fontsize=8.0,
            title_fontsize=8.5
        )

    # 底部 Tags
    if tags:
        tag_str = "Tags:  " + "  •  ".join(f"#{t}" for t in tags)
        fig.text(0.5, 0.02, tag_str, ha="center", fontsize=8.0, color="#78909C")

    ax.axis("off")

    # 保存图片并立刻关闭图层释放内存
    plt.savefig(output_path, bbox_inches="tight", dpi=140)
    plt.close(fig)

def main(json_input_path, output_dir="./img"):
    os.makedirs(output_dir, exist_ok=True)
    
    motifs = load_all_motifs(json_input_path)
    print(f"[*] 共发现 {len(motifs)} 个 Motif 实例，开始绘制...")

    success_count = 0
    for idx, motif in enumerate(motifs, start=1):
        raw_id = motif.get("motif_id", f"pattern_{idx}")
        safe_id = sanitize_filename(raw_id)
        filename = f"{idx:02d}_{safe_id}.png"
        out_path = os.path.join(output_dir, filename)

        try:
            draw_single_motif(motif, out_path, index_num=idx)
            print(f"  [{idx:02d}/{len(motifs):02d}] 已生成: {out_path}")
            success_count += 1
        except Exception as e:
            print(f"  [{idx:02d}/{len(motifs):02d}] 绘制失败 '{safe_id}': {e}")
            plt.close('all')  # 出错时强制释放内存

    print(f"\n[√] 处理完成！成功生成 {success_count}/{len(motifs)} 张拓扑图至 '{output_dir}'")

if __name__ == "__main__":
    # 使用原始字符串 r"..." 彻底消除 Windows 路径反斜杠转义警告
    JSON_PATH = r"D:\projects\AML\data\distilled_kb.json"
    OUTPUT_DIR = r"D:\projects\AML\可视化展示\motif展示\img"

    main(JSON_PATH, OUTPUT_DIR)