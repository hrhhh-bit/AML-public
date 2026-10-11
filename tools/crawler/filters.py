"""全局负向主题词硬拦截与存量剪枝黑名单（tools/crawler 专用）。

两套独立规则，职责不同、互不耦合：

1. **运行时负向硬拦截（调度器漏斗）**
   `NEGATIVE_KEYWORDS` —— 即使命中 AML 关键词，只要标题/正文显著落入
   上述负向区间，调度器一律直接抛弃、不落盘。大小写不敏感、子串匹配。

2. **存量精细化剪枝黑名单（Surgical Pruning）**
   `is_prunable_record(title, url)` —— 对历史 manifest 记录的标题 / URL
   特征做硬淘汰，剔除商业/审计废纸与宏观合规、社工通报两类噪音。

本模块严格遵守架构隔离红线：不导入 src/ 下任何模块，不发网络请求。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. 全局负向主题词硬拦截名单（任务 B）
# ---------------------------------------------------------------------------
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "FATF",
    "compliance guideline",
    "job-seeking",
    "recruitment phishing",
    "audit report summary",
    "kyc verification",
)


def _contains_any(text: str, keywords) -> bool:
    lowered = (text or "").lower()
    return any(kw.lower() in lowered for kw in keywords if kw)


def is_negative_title(title: str, keywords=NEGATIVE_KEYWORDS) -> bool:
    """标题显著落入负向区间：直接抛弃，不落盘、不发二次请求。"""
    return _contains_any(title, keywords)


def is_negative_text(text: str, keywords=NEGATIVE_KEYWORDS) -> bool:
    """正文关键词落入负向区间：提取后抛弃，不落盘。"""
    return _contains_any(text, keywords)


# ---------------------------------------------------------------------------
# 2. 存量剪枝黑名单（任务 A）：标题 / URL 特征硬淘汰
# ---------------------------------------------------------------------------
# 商业 / 审计废纸（产品页、审计服务、导航列表页、合作公告）
_TITLE_COMMERCIAL_PATTERNS = (
    r"smart[- ]?contract audit",
    r"kyc",
    r"penetration[- ]?test",
    r"bug[- ]?bounty",
    r"proof of reserves",
    r"formal verification",
    r"validator service",
    r"skyinsights",
    r"skynet",
    r"red team",
    r"security explained",
    r"audit considerations",
    r"guide for institutions",
    r"independent security research",
    r"certik report",
    r"^blog$",
    r"view all",
    r"announcements",
    r"products\s*&?\s*(amp;)?\s*services",
    r"educational",
    r"technology analysis",
    r"ecosystem analysis",
    r"company updates",
    r"policy pulse",
    r"^readme(\.md)?$",
    r"eos bp nodes security audit",
    r"joins (forces|lf)\b",
    r"partner (program|on)\b",
    r"chain scan",
    r"dlt security solutions",
    r"vara compliance",
    r"dora\b",
    r"\bmica\b",
    r"security audit report",
    r"how to be evil",
    r"virtual asset services act",
    r"known attack vectors",
)

# 宏观合规 / 政策 / 社工通报
_TITLE_POLICY_PATTERNS = (
    r"FATF",
    r"regulatory",
    r"regulation",
    r"compliance",
    r"\bpolicy\b",
    r"job[- ]?seeking",
    r"recruitment",
    r"\bphishing\b",
    r"global scrutiny",
)

# 无链上资金流的市场综述 / 产品能力文
_TITLE_EXTRA_PATTERNS = (
    r"cex h1",
    r"stablecoin regulatory",
    r"a discussion with",
    r"^what is ",
    r"everyday finance app",
    r"wall street",
    r"eip-7702",
    r"convergence research",
    r"employee verification",
    r"^disclaimer",
    r"web3 security audits",
    r"infrastructure audits",
    r"crypto crime report",
    r"^newsroom",
    r"sar form",
)

_TITLE_BLACKLIST_RE = re.compile(
    "|".join(_TITLE_COMMERCIAL_PATTERNS + _TITLE_POLICY_PATTERNS + _TITLE_EXTRA_PATTERNS),
    re.I,
)

_URL_BLACKLIST_PATTERNS = (
    r"(^|/)products(/|$)",
    r"(^|/)certik-report(/|$)",
    r"(^|/)blog/?$",
    r"(^|/)blog/research",
    r"\?tab=",
    r"policy-pulse",
    r"smart-contract-audit",
    r"proof-of-reserves",
    r"formal-verification",
    r"penetration-testing",
    r"\bpentest\b",
    r"bug-bounty",
    r"skyinsights",
    r"skynet",
    r"skynode",
    r"kyc",
    r"chain-scan",
    r"dlt-security",
    r"vara",
    r"dora",
    r"mica",
    r"cex-h1-2026",
    r"circle-arc-mainnet",
    r"wallets-storage-execution",
    r"tolk-security-explained",
    r"besu",
    r"where-cip-56",
    r"eos-bp-nodes-security-checklist",
    r"tradingview-xss",
    r"attack-surface",
    r"known-attack-vectors",
    r"evil_blockchain",
    r"\.(png|jpe?g|gif|svg|webp|pdf|zip)(\?|$)",
    r"^https?://(www\.)?certik\.com/?$",
    # BlockSec 官网产品页 / 导航页（非 blog 事故文）
    r"blocksec\.com/(chain-audit|phalcon|safe-wallet-monitor|stop|trace-ai)",
    r"blocksec\.com/(web3-companion|metasuites|usdt-freeze-checker|solutions)",
    r"blocksec\.com/(research|stablecoin-freeze-risk|newsroom|employee-verification|disclaimer)",
    r"metasleuth\.io",
    r"^https?://blocksec\.com/?$",
    # BlockSec blog 合规/表单文（无链上资金流）
    r"blog/(aml-banking|aml-finance|sar-form|ofac-sanctions-monitoring)",
    r"blog/(stablecoin-regulation|usdt-freeze-stablecoin-compliance-guide)",
)

_URL_BLACKLIST_RE = re.compile("|".join(_URL_BLACKLIST_PATTERNS), re.I)

# 根级导航 README（GitHub 仓库首页说明），与子目录事故索引 README 区分
_ROOT_README_URL_RE = re.compile(
    r"raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/README\.md$", re.I
)


def is_root_readme_url(url: str) -> bool:
    """GitHub 仓库根级 README.md 导航页判定（非子目录归档）。"""
    return bool((url or "").strip() and _ROOT_README_URL_RE.search((url or "").strip()))


def is_prunable_title(title: str) -> bool:
    """标题黑名单硬淘汰判定（不含 URL 特征）。"""
    normalized_title = re.sub(r"\s+", " ", (title or "")).strip()
    return bool(normalized_title and _TITLE_BLACKLIST_RE.search(normalized_title))


def is_prunable_url(url: str) -> bool:
    """URL 黑名单硬淘汰判定（不含标题特征）。"""
    normalized_url = (url or "").strip()
    return bool(normalized_url and _URL_BLACKLIST_RE.search(normalized_url))


def is_prunable_record(title: str, url: str) -> bool:
    """历史台账记录硬淘汰判定：标题或 URL 命中任一黑名单特征即剔除。"""
    return is_prunable_title(title) or is_prunable_url(url)
