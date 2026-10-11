"""高保真正文提取与降噪封装（tools/crawler 专用）。

主引擎：`trafilatura`（可选依赖，运行时惰性导入；缺失或失败时静默回退）。
回退引擎：标准库 `html.parser` 实现的 DOM 降噪抽取器，自动剥离
header / footer / nav / 侧边栏 / 广告 / 脚本等噪声节点。

字符数准入过滤：[500, 50000]。

本模块严格遵守架构隔离红线：不导入 src/ 下任何模块。
"""

from __future__ import annotations

import html as _html_lib
import re
import unicodedata
from datetime import date as _date
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

MIN_CHARS = 500
MAX_CHARS = 50000

# 直接丢弃的噪声标签
_NOISE_TAGS = frozenset({
    "script", "style", "noscript", "iframe", "svg", "form", "button",
    "nav", "header", "footer", "aside", "menu", "dialog", "template",
})

# 命中 class / id 等属性即丢弃（广告、导航、侧边推荐等）
_NOISE_ATTR_RE = re.compile(
    r"(^|[\s\"'])(ad|adsbygoogle|ads|advert|advertisement|banner|sidebar|"
    r"widget|menu|nav|footer|header|share|social|comment|recommend|"
    r"related|promo|cookie|popup|modal|subscribe|newsletter)(?:[\s\"'_-]|$)",
    re.I,
)

# 逐行清洗时剔除的页脚 / 站务类样板行
_BOILERPLATE_RE = re.compile(
    r"(cookie|privacy policy|terms of service|all rights reserved|subscribe|"
    r"newsletter|advertisement|^©|copyright)",
    re.I,
)

# 块级标签：前后各补一个换行，保证段落边界
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "blockquote", "pre", "br", "td", "th", "ul", "ol", "table",
    "figure", "figcaption",
})


class _BodyTextParser(HTMLParser):
    """仅保留正文文本的降噪解析器（不依赖任何第三方库）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._buffer: list[str] = []

    # -- 工具 ------------------------------------------------------------
    @staticmethod
    def _attrs_repr(attrs) -> str:
        return " ".join(f'{key}="{value}"' for key, value in attrs)

    @classmethod
    def _is_noise(cls, tag: str, attrs) -> bool:
        if tag in _NOISE_TAGS:
            return True
        return bool(_NOISE_ATTR_RE.search(cls._attrs_repr(attrs)))

    # -- 事件 ------------------------------------------------------------
    def handle_starttag(self, tag, attrs) -> None:
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if self._is_noise(tag, attrs):
            self._skip_depth = 1
            return
        if tag in _BLOCK_TAGS:
            self._buffer.append("\n")

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag) -> None:
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in _BLOCK_TAGS:
            self._buffer.append("\n")

    def handle_data(self, data) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            return
        self._buffer.append(data)

    @property
    def text(self) -> str:
        return "".join(self._buffer)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _trafilatura_extract(raw_html: str, url: str) -> str | None:
    """trafilatura 主引擎（可选依赖）。不可用 / 失败均返回 None 触发回退。"""
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        text = trafilatura.extract(
            raw_html,
            url=url or None,
            include_comments=False,
            include_tables=False,
            include_links=False,
            include_images=False,
        )
    except Exception:
        return None
    return text or None


def clean_text(text: str) -> str:
    """逐行规范化空白并剔除样板行。"""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if _BOILERPLATE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def extract_main_text(raw_html: str, url: str = "") -> str:
    """高保真正文提取：trafilatura 优先，标准库降噪解析器回退。"""
    if not raw_html:
        return ""
    text = _trafilatura_extract(raw_html, url)
    if text is None:
        parser = _BodyTextParser()
        try:
            parser.feed(raw_html)
        except Exception:
            pass
        text = parser.text
    return clean_text(text)


# ---------------------------------------------------------------------------
# 标题 / 日期 / 规范化
# ---------------------------------------------------------------------------
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)


def extract_title(raw_html: str) -> str:
    if not raw_html:
        return ""
    match = _TITLE_RE.search(raw_html) or _H1_RE.search(raw_html)
    if not match:
        return ""
    title = re.sub(r"<[^>]+>", "", match.group(1))
    return re.sub(r"\s+", " ", _html_lib.unescape(title)).strip()


_META_TIME_PATTERNS = (
    re.compile(
        r'<meta[^>]+(?:property|name)\s*=\s*["\']article:published_time["\'][^>]+'
        r'content\s*=\s*["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]+'
        r'(?:property|name)\s*=\s*["\']article:published_time["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+(?:name|property)\s*=\s*["\'](?:date|pubdate|publish-date|'
        r'dc\.date|dcterms\.created)["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]+'
        r'(?:name|property)\s*=\s*["\'](?:date|pubdate|publish-date|dc\.date|dcterms\.created)["\']',
        re.I,
    ),
    re.compile(r'<time[^>]+datetime\s*=\s*["\']([^"\']+)["\']', re.I),
)


def extract_publish_date(raw_html: str, url: str = "") -> str:
    """从 meta / time 标签或 URL 日期段提取 YYYY-MM-DD，未知返回空串。"""
    for pattern in _META_TIME_PATTERNS:
        match = pattern.search(raw_html or "")
        if match:
            normalized = normalize_iso_date(match.group(1))
            if normalized:
                return normalized
    match = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url or "")
    if match:
        return normalize_iso_date(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    return ""


def normalize_iso_date(value: str) -> str:
    """把 ISO / RFC 822 / 斜杠日期统一为 YYYY-MM-DD；非法输入返回空串。"""
    if not value:
        return ""
    value = value.strip()
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return ""
        if dt is None:
            return ""
        year, month, day = dt.year, dt.month, dt.day
    if not (1990 <= year <= 2100):
        return ""
    try:
        _date(year, month, day)
    except ValueError:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# Slug / 关键词 / 长度准入
# ---------------------------------------------------------------------------
def slugify(text: str, max_len: int = 64) -> str:
    """ASCII slug 化（用于文件名回退）。"""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    slug = slug[:max_len].rstrip("-")
    return slug or "report"


def slugify_from_url(url: str) -> str:
    path = url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    stem = re.sub(r"\.(html?|md|txt|php|aspx?)$", "", path, flags=re.I)
    return slugify(stem)


def match_keywords(text: str, keywords) -> list[str]:
    """返回在文本中出现过的检索关键词（保持注册顺序，大小写不敏感）。"""
    lowered = (text or "").lower()
    return [kw for kw in keywords if kw and kw.lower() in lowered]


# ---------------------------------------------------------------------------
# 资金流证据抽取（DeFiHackLabs 事故复盘归档）
# ---------------------------------------------------------------------------
FUND_FLOW_MARKERS: tuple[str, ...] = (
    "fund flow",
    "money tracing",
    "money laundering",
    "laundering",
    "laundered",
    "tornado",
    "mixer",
    "cross-chain",
    "bridge",
    "cash out",
    "cash-out",
    "phalcon",
)

_FLOW_NODE_PATTERN = (
    r"(?:0x[0-9a-fA-F]{8,}|\[[^\]]{2,64}\]|[A-Z][\w.'-]{3,63}"
    r"|attacker|victim|hacker|exchange)"
)
_ASCII_FLOW_RE = re.compile(
    rf"({_FLOW_NODE_PATTERN})\s*(?:->|→|=>|-->)"
    rf"\s*({_FLOW_NODE_PATTERN})"
)


def _extract_hop_edges(text: str) -> list[tuple[str, str]]:
    """抽取 ASCII 资金流链路单跳边；链式共享节点（A -> B -> C）正确切分。"""
    edges: list[tuple[str, str]] = []
    pos = 0
    while True:
        match = _ASCII_FLOW_RE.search(text or "", pos)
        if not match:
            break
        edges.append((match.group(1).strip(), match.group(2).strip()))
        # 下一跳从上一条边的 dst 起点继续，允许节点被两条相邻边共享
        pos = match.start(2)
    return edges


def analyze_fund_flow_evidence(text: str) -> dict:
    """抽取 Markdown 事故复盘中的链上资金流证据。

    返回:
        has_flow   是否检出任何资金流标记或 ASCII 链路
        markers    命中的资金流标记词（去重、保持声明顺序）
        hop_edges  抽取到的 ASCII 单跳边（src -> dst 节点列表）
        hop_count  唯一节点去重后的跳数（0 = 无链路）
    """
    lowered = (text or "").lower()
    markers = [m for m in FUND_FLOW_MARKERS if m in lowered]
    edges = _extract_hop_edges(text)
    nodes: set[str] = set()
    for src, dst in edges:
        nodes.add(src.lower())
        nodes.add(dst.lower())
    hop_count = max(0, len(nodes) - 1) if edges else 0
    return {
        "has_flow": bool(markers or edges),
        "markers": markers,
        "hop_edges": edges,
        "hop_count": hop_count,
    }


def passes_length_filter(
    text: str,
    min_chars: int = MIN_CHARS,
    max_chars: int = MAX_CHARS,
) -> bool:
    """字符数准入过滤：[min_chars, max_chars]。"""
    length = len(text or "")
    return min_chars <= length <= max_chars
