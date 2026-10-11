"""四大安全厂商数据源注册表、检索词与采集规模常量定义。

架构边界：本模块为纯配置数据（dataclass），不发起网络请求、
不依赖任何 src/ 模块。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 采集规模常量（总目标 + 分层配额：各厂商保底 15、软上限 20）
# ---------------------------------------------------------------------------
DEFAULT_TOTAL_QUOTA = 80               # 全局默认目标规模（主停止条件，60~80 区间上限）
DEFAULT_MIN_PER_VENDOR = 15            # 单厂商保底篇数（保底 15~20 区间下限）
DEFAULT_MAX_PER_VENDOR = 20            # 防垄断软上限默认值（保底区间上限；None/0 = 不设上限）
RECOMMENDED_TOTAL_RANGE = (60, 80)     # 总规模建议区间（黄金研报池 60~80 篇）

# ---------------------------------------------------------------------------
# CertiK 页面发现规则（Incident Focus，任务 C）
# ---------------------------------------------------------------------------
# 约束抓取链接必须匹配真实黑客攻击专题路径；裸域名 "certik" 宽松匹配已剔除。
CERTIK_INCIDENT_PATH_FRAGMENTS: tuple[str, ...] = (
    "/resources/blog/incident-analysis/",
    "/resources/blog/hack/",
    "/resources/blog/security-incident/",
    "incident-analysis",
    "security-incident",
)

# ---------------------------------------------------------------------------
# 统一 AML 检索词（供 matched_kw 标注与页面链接过滤复用）
# ---------------------------------------------------------------------------
AML_KEYWORDS: tuple[str, ...] = (
    "AML",
    "anti-money laundering",
    "money laundering",
    "laundering",
    "洗钱",
    "洗币",
    "fund flow",
    "资金追踪",
    "fund tracing",
)


@dataclass(frozen=True)
class Source:
    """单个数据源定义。

    kind="feed"：RSS / Atom 订阅源；
    kind="page"：HTML 列表页（按 keywords 过滤 <a> 链接发现报告入口）；
    kind="github"：GitHub 仓库树 API（recursive=1）发现 Markdown 归档，
        按 fund_flow_tags 标签过滤深链（blob → raw 纯文本 CDN 直读）。

    可选约束字段：
    - required_path_fragments：页面源专属路径约束（如 CertiK 事故专题路径），
      非空时 URL 必须包含其中至少一个片段才放行，且不再使用厂商名宽松匹配；
    - title_keywords：标题硬过滤（事件词白名单，如 CertiK 的 incident/hack），
      非空时标题必须命中至少一个词才放行，用于 feed 源的信噪比收紧；
    - github_repo / github_branch：GitHub 归档源仓库与默认分支；
    - fund_flow_tags：资金流标签（Phalcon / BlockSec / Fund Flow / …），
      仅对 kind="github" 生效，用于高保真拓扑归档的定向增补。
    """

    name: str
    url: str
    kind: str = "feed"
    keywords: tuple[str, ...] = ()
    required_path_fragments: tuple[str, ...] = ()
    title_keywords: tuple[str, ...] = ()
    github_repo: str = ""
    github_branch: str = "main"
    fund_flow_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Vendor:
    """单个厂商：代码、名称、数据源列表与检索词。"""

    code: str
    name: str
    sources: tuple[Source, ...]
    keywords: tuple[str, ...] = AML_KEYWORDS


# ---------------------------------------------------------------------------
# 四大权威厂商注册表（顺序即调度顺序）
# ---------------------------------------------------------------------------
VENDORS: tuple[Vendor, ...] = (
    Vendor(
        code="slowmist",
        name="SlowMist",
        sources=(
            Source(
                "SlowMist Medium 官方 RSS",
                "https://medium.com/feed/@SlowMist",
                kind="feed",
            ),
            Source(
                "SlowMist GitHub Knowledge-Base 归档",
                "https://github.com/slowmist/Knowledge-Base",
                kind="page",
                keywords=("laundering", "AML", "hack", "phishing", "fund", "money"),
            ),
        ),
        keywords=AML_KEYWORDS + ("慢雾", "phishing", "fund tracking"),
    ),
    Vendor(
        code="blocksec",
        name="BlockSec",
        sources=(
            Source(
                "BlockSec Medium 官方 RSS",
                "https://medium.com/feed/@blocksecteam",
                kind="feed",
            ),
            Source(
                "BlockSec GitHub",
                "https://github.com/blocksecteam",
                kind="page",
                keywords=("post-mortem", "hack", "attack", "AML", "fund"),
            ),
            Source(
                "BlockSec 官网博客（Exploit 事故分析）",
                "https://blocksec.com/blog",
                kind="page",
                keywords=("exploit", "hack", "AML", "fund", "freeze", "forensics"),
            ),
            Source(
                "DeFiHackLabs 深度事故库（Phalcon / BlockSec / Fund Flow / Money Tracing / Tornado / Cross-chain）",
                "https://github.com/SunWeb3Sec/DeFiHackLabs",
                kind="github",
                github_repo="SunWeb3Sec/DeFiHackLabs",
                github_branch="main",
                fund_flow_tags=(
                    "phalcon", "blocksec", "fund flow", "money tracing",
                    "tornado", "cross-chain",
                ),
            ),
        ),
        keywords=AML_KEYWORDS + ("blocksec", "post-mortem", "attack", "exploit"),
    ),
    Vendor(
        code="peckshield",
        name="PeckShield",
        sources=(
            Source(
                "PeckShield Medium 官方 RSS",
                "https://medium.com/feed/@peckshield",
                kind="feed",
            ),
            Source(
                "PeckShield 官网事故归档",
                "https://peckshield.com/en/",
                kind="page",
                keywords=("hack", "incident", "alert", "AML", "fund"),
            ),
            Source(
                "CryptoVulhub 开源事故复盘归档库",
                "https://github.com/Rivaill/CryptoVulhub",
                kind="github",
                github_repo="Rivaill/CryptoVulhub",
                github_branch="master",
            ),
        ),
        keywords=AML_KEYWORDS + ("peckshield", "incident", "attack", "hack"),
    ),
    Vendor(
        code="certik",
        name="CertiK",
        sources=(
            Source(
                "CertiK Incident Analysis 事故专题页（路径精准过滤）",
                "https://www.certik.com/blog/research?tab=incident-analysis",
                kind="page",
                keywords=("incident", "hack", "exploit", "fund", "AML"),
                required_path_fragments=CERTIK_INCIDENT_PATH_FRAGMENTS,
            ),
            Source(
                "CertiK Medium 官方 RSS（事件词标题硬过滤）",
                "https://medium.com/feed/@certik",
                kind="feed",
                title_keywords=("incident", "hack", "exploit", "attack"),
            ),
        ),
        keywords=AML_KEYWORDS + ("certik", "skynet", "incident", "audit", "exploit"),
    ),
)

VENDOR_CODES: tuple[str, ...] = tuple(v.code for v in VENDORS)
_BY_CODE: dict[str, Vendor] = {v.code: v for v in VENDORS}


def get_vendor(code: str) -> Vendor:
    """按厂商代码（slowmist / blocksec / peckshield / certik）取注册项。"""
    try:
        return _BY_CODE[code]
    except KeyError:
        raise KeyError(f"unknown vendor code: {code!r} (available: {VENDOR_CODES})") from None
