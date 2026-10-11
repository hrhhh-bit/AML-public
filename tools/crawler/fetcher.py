"""HTTP 采集器与离线 Mock 采集器。

- `HttpFetcher`：基于标准库 urllib 的真实采集器（UA / 超时 / 退避重试 /
  速率限制 / gzip 解压），支持 RSS / Atom 订阅解析与 HTML 链接发现。
- `MockFetcher` + `build_mock_world`：完全离线的内存夹具采集器，供
  `--dry-run`、`--mock` 与单元测试使用，杜绝测试发起真实外网请求。

本模块严格遵守架构隔离红线：不导入 src/ 下任何模块。
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from tools.crawler.extractor import normalize_iso_date
from tools.crawler.vendor_registry import VENDORS, Source, Vendor

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 15      # 秒
DEFAULT_RETRIES = 2
DEFAULT_DELAY = 1.0       # 请求间速率限制间隔（秒）
DISCOVER_LINK_CAP = 60    # 单页面链接发现上限


class FetchError(RuntimeError):
    """抓取失败（网络错误 / HTTP 错误 / 数据损坏）。"""


@dataclass(frozen=True)
class FeedItem:
    """从订阅源 / 列表页发现的一条候选报告。

    content_html：RSS `<content:encoded>` / `<description>` / Atom `<content>`
    的原地正文 HTML；非空时调度器直接提取正文，严禁再对 url 发起二次 HTTP 请求。
    """

    url: str
    title: str = ""
    publish_date: str = ""
    summary: str = ""
    content_html: str = ""


# ---------------------------------------------------------------------------
# 强健 URL 过滤器（反爬规避 + 降噪）
# ---------------------------------------------------------------------------
URL_BLACKLIST_KEYWORDS: tuple[str, ...] = (
    "signup", "login", "signin", "auth", "pricing", "feature",
    "settings", "terms", "privacy", "about", "contact", "/tag/",
)

_GITHUB_DOC_SUFFIX_RE = re.compile(r"\.(md|markdown|txt)$", re.I)


def is_github_host(url: str) -> bool:
    """目标源是否位于 GitHub 域（github.com / *.github.com / raw.githubusercontent.com）。"""
    host = (urlsplit(url).netloc or "").lower()
    return (
        host == "github.com"
        or host.endswith(".github.com")
        or host == "raw.githubusercontent.com"
    )


def is_noise_url(url: str) -> bool:
    """黑名单拦截：命中注册/登录/定价/标签页等非文章关键字的 URL 一律过滤。"""
    lowered = url.lower()
    return any(keyword in lowered for keyword in URL_BLACKLIST_KEYWORDS)


def is_github_file_url(url: str) -> bool:
    """GitHub 专用规则：仅允许 Markdown / 纯文本文档（图片、代码、目录页一律拒绝）。"""
    path = (urlsplit(url).path or "").lower()
    return bool(_GITHUB_DOC_SUFFIX_RE.search(path))


_GITHUB_BLOB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<path>.+)$",
    re.I,
)


def to_raw_github_url(url: str) -> str:
    """将 github.com 的 blob 页面 URL 转换为 raw.githubusercontent.com 纯文本链接。

    raw 域名是静态纯文本 CDN，无网页反爬，可直接快速读取；
    不匹配 blob 结构时原样返回。
    """
    clean = url.strip().split("#", 1)[0].split("?", 1)[0]
    match = _GITHUB_BLOB_RE.match(clean)
    if not match:
        return url
    return (
        f"https://raw.githubusercontent.com/{match.group('owner')}/"
        f"{match.group('repo')}/{match.group('path')}"
    )


class BaseFetcher:
    """采集器统一协议：discover 发现候选，fetch 抓取正文。"""

    def discover(self, source: Source, vendor: Vendor | None = None) -> list[FeedItem]:
        raise NotImplementedError

    def fetch(self, url: str) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _child_text(node, localname: str) -> str:
    for child in node:
        if _local_name(child.tag) == localname:
            return "".join(child.itertext()).strip()
    return ""


def _rss_item(node) -> FeedItem:
    title = _child_text(node, "title")
    link = _child_text(node, "link")
    guid = _child_text(node, "guid")
    if not link and guid and guid.lower().startswith("http"):
        link = guid
    published = _child_text(node, "pubdate") or _child_text(node, "date")
    description = _child_text(node, "description")
    summary = description or _child_text(node, "summary")
    # 原地正文：优先 content:encoded（CDATA 完整 HTML），回退 description / summary
    content_html = _child_text(node, "encoded") or description or summary
    return FeedItem(
        url=link,
        title=title,
        publish_date=normalize_iso_date(published),
        summary=summary,
        content_html=content_html,
    )


def _atom_item(entry) -> FeedItem:
    link = ""
    for child in entry:
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href", "")
            if href:
                link = href
                break
    title = _child_text(entry, "title")
    published = _child_text(entry, "published") or _child_text(entry, "updated")
    content = _child_text(entry, "content")
    summary = _child_text(entry, "summary")
    content_html = content or summary
    return FeedItem(
        url=link,
        title=title,
        publish_date=normalize_iso_date(published),
        summary=summary,
        content_html=content_html,
    )


_CHARSET_RE = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", re.I)


def _decode_body(body: bytes, content_type: str) -> str:
    match = _CHARSET_RE.search(content_type.encode("ascii", "ignore"))
    if match:
        try:
            return body.decode(match.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    match = _CHARSET_RE.search(body[:2048])
    if match:
        try:
            return body.decode(match.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    return body.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 真实 HTTP 采集器
# ---------------------------------------------------------------------------
class HttpFetcher(BaseFetcher):
    """基于标准库 urllib 的健壮采集器：UA、超时、退避重试、速率限制。"""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        delay: float = DEFAULT_DELAY,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.delay = max(0.0, delay)
        self.user_agent = user_agent
        # 进程内响应缓存：保底补扫轮次 / 多厂商共享源复用同一份响应
        self._cache: dict[str, tuple[bytes, str]] = {}

    # -- 抓取 ------------------------------------------------------------
    def fetch(self, url: str) -> str:
        last_error: FetchError | None = None
        for attempt in range(self.retries + 1):
            if attempt and self.delay:
                time.sleep(self.delay * attempt)  # 退避式速率限制
            try:
                body, content_type = self._fetch_once(url)
                return _decode_body(body, content_type)
            except FetchError as exc:
                last_error = exc
            except Exception as exc:  # 兜底：任何异常统一封装
                last_error = FetchError(f"{url}: {exc}")
        raise FetchError(f"{url}: failed after {self.retries + 1} attempt(s): {last_error}")

    def fetch_bytes(self, url: str) -> bytes:
        """二进制抓取（codeload tarball 等）：返回原始字节，不做文本解码。"""
        last_error: FetchError | None = None
        for attempt in range(self.retries + 1):
            if attempt and self.delay:
                time.sleep(self.delay * attempt)  # 退避式速率限制
            try:
                body, _content_type = self._fetch_once(url)
                return body
            except FetchError as exc:
                last_error = exc
            except Exception as exc:  # 兜底：任何异常统一封装
                last_error = FetchError(f"{url}: {exc}")
        raise FetchError(f"{url}: failed after {self.retries + 1} attempt(s): {last_error}")

    def _fetch_once(self, url: str) -> tuple[bytes, str]:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip",
                "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.6",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
                content_type = resp.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as exc:
            raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise FetchError(f"{url}: {exc.reason}") from exc
        except Exception as exc:
            raise FetchError(f"{url}: {exc}") from exc
        if encoding == "gzip":
            try:
                body = gzip.decompress(body)
            except OSError as exc:
                raise FetchError(f"{url}: bad gzip payload: {exc}") from exc
        result = (body, content_type)
        self._cache[url] = result
        return result

    # -- 发现 ------------------------------------------------------------
    def discover(self, source: Source, vendor: Vendor | None = None) -> list[FeedItem]:
        if source.kind == "feed":
            return self.parse_feed(self.fetch(source.url))
        if source.kind == "github":
            return self.discover_github_archive(source)
        if source.kind == "page":
            return self.discover_links(
                self.fetch(source.url),
                source.url,
                source.keywords,
                vendor,
                required_path_fragments=source.required_path_fragments,
            )
        return []

    # -- GitHub 深度事故库（任务 D）-------------------------------------
    def discover_github_archive(self, source: Source) -> list[FeedItem]:
        """激活开源深度事故追踪库：发现 Markdown 归档（多级回退）。

        1. GitHub 仓库树 API（recursive=1，最快、最省流量）；
        2. codeload tarball 整仓归档（免 API 限流，正文原地直提）；
        3. 仓库 HTML 页面链接发现（最后兜底）。
        """
        items = self._discover_github_tree(source)
        if items:
            return items
        try:
            items = self._discover_github_tarball(source)
        except FetchError:
            items = []
        if items:
            return items
        # 最后兜底：HTML 页面链接发现（复用 page 逻辑 + GitHub 专用文件规则）
        return self.discover_links(
            self.fetch(source.url),
            source.url,
            source.keywords,
            vendor=None,
        )

    def _discover_github_tree(self, source: Source) -> list[FeedItem]:
        api_url = (
            f"https://api.github.com/repos/{source.github_repo}/"
            f"git/trees/{source.github_branch}?recursive=1"
        )
        try:
            raw_json = self.fetch(api_url)
        except FetchError:
            return []
        return parse_github_tree(
            raw_json,
            repo=source.github_repo,
            branch=source.github_branch,
            tags=source.fund_flow_tags,
        )

    def _discover_github_tarball(self, source: Source) -> list[FeedItem]:
        tarball_url = (
            f"https://codeload.github.com/{source.github_repo}/tar.gz/"
            f"refs/heads/{source.github_branch}"
        )
        payload = self.fetch_bytes(tarball_url)
        return parse_github_tarball(
            payload,
            repo=source.github_repo,
            branch=source.github_branch,
            tags=source.fund_flow_tags,
        )

    def parse_feed(self, xml_text: str) -> list[FeedItem]:
        """解析 RSS 2.0 / Atom 订阅文本为候选条目。"""
        text = (xml_text or "").strip()
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            start = re.search(r"<(rss|feed|atom)", text, re.I)
            if not start:
                return []
            try:
                root = ET.fromstring(text[start.start():])
            except ET.ParseError:
                return []
        items: list[FeedItem] = []
        if _local_name(root.tag) == "rss":
            for node in root.iter():
                if _local_name(node.tag) != "item":
                    continue
                item = _rss_item(node)
                if item and item.url:
                    items.append(item)
        else:  # Atom
            for node in root.iter():
                if _local_name(node.tag) != "entry":
                    continue
                item = _atom_item(node)
                if item and item.url:
                    items.append(item)
        return items

    _LINK_RE = re.compile(
        r"<a\s+[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S
    )

    def discover_links(
        self,
        html: str,
        base_url: str,
        keywords=(),
        vendor: Vendor | None = None,
        required_path_fragments: tuple[str, ...] = (),
    ) -> list[FeedItem]:
        """HTML 列表页链接发现：按关键词（+ 厂商名）过滤候选链接。

        required_path_fragments 非空时（如 CertiK 事故专题路径）：
        - URL 必须包含其中至少一个片段，否则直接丢弃；
        - 不再使用厂商名（如裸域名 "certik"）做宽松匹配，杜绝商业页穿透。
        """
        terms = [t for t in keywords if t]
        if vendor is not None and not required_path_fragments:
            terms = terms + [vendor.name.lower(), vendor.code.lower()]
        fragments = tuple(f.lower() for f in required_path_fragments)
        found: list[FeedItem] = []
        seen: set[str] = set()
        github_source = is_github_host(base_url)
        for href, inner in self._LINK_RE.findall(html or ""):
            url = urljoin(base_url, href.strip())
            if not url or url in seen:
                continue
            # 强健 URL 过滤：黑名单拦截（signup/login/...）+ GitHub 专用文件规则
            if is_noise_url(url):
                continue
            if github_source and not is_github_file_url(url):
                continue
            # GitHub blob 页面 → raw 纯文本 CDN，彻底绕过网页反爬
            url = to_raw_github_url(url)
            if fragments and not any(fragment in url.lower() for fragment in fragments):
                continue  # 路径精准过滤：非事故专题路径一律拦截
            label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
            haystack = f"{url} {label}".lower()
            if terms and not any(term.lower() in haystack for term in terms):
                continue
            seen.add(url)
            found.append(FeedItem(url=url, title=label))
            if len(found) >= DISCOVER_LINK_CAP:
                break
        return found


# ---------------------------------------------------------------------------
# GitHub 仓库树解析（DeFiHackLabs 深度事故库）
# ---------------------------------------------------------------------------
_MD_SUFFIX_RE = re.compile(r"\.md$", re.I)


def parse_github_tree(
    json_text: str,
    *,
    repo: str,
    branch: str = "main",
    tags: tuple[str, ...] = (),
    cap: int = DISCOVER_LINK_CAP,
) -> list[FeedItem]:
    """解析 GitHub git/trees API（recursive=1）JSON，产出标签过滤后的归档清单。

    - 仅保留 Markdown 文档（.md blob）；
    - 按资金流标签（Phalcon / BlockSec / Fund Flow / Money Tracing /
      Tornado / Cross-chain）过滤文件路径；
    - 直接产出 raw.githubusercontent.com 纯文本 CDN 链接（无网页反爬）。
    """
    try:
        payload = json.loads(json_text or "")
        tree = payload.get("tree") or []
    except (ValueError, AttributeError):
        return []
    lowered_tags = [tag.lower() for tag in tags if tag]
    items: list[FeedItem] = []
    seen: set[str] = set()
    for entry in tree:
        if not isinstance(entry, dict):
            continue
        path = (entry.get("path") or "").strip()
        if entry.get("type") != "blob" or not _MD_SUFFIX_RE.search(path):
            continue
        if path in seen:
            continue
        lowered_path = path.lower()
        if lowered_tags and not any(tag in lowered_path for tag in lowered_tags):
            continue
        seen.add(path)
        title = path.rsplit("/", 1)[-1]
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        items.append(FeedItem(url=url, title=title))
        if len(items) >= cap:
            break
    return items


def parse_github_tarball(
    payload: bytes,
    *,
    repo: str,
    branch: str = "main",
    tags: tuple[str, ...] = (),
    cap: int = DISCOVER_LINK_CAP,
) -> list[FeedItem]:
    """解析 codeload tar.gz 整仓归档，产出标签过滤后的 Markdown 归档清单。

    - 排除教程 / 模板目录（academy、.github、CONTRIBUTING、根 README）；
    - 标签匹配 = 文件路径命中 **或** 正文命中（历史事故索引的路径通常
      不带标签词，但正文原生携带 Phalcon / BlockSec / Fund Flow 等资金流说明）；
    - 正文原地直提（content_html 非空）：调度器直接清洗落盘，严禁再对
      raw CDN 发起二次 HTTP 请求。
    """
    import io
    import tarfile

    from tools.crawler.extractor import FUND_FLOW_MARKERS

    try:
        tar = tarfile.open(fileobj=io.BytesIO(payload or b""), mode="r:gz")
    except (tarfile.TarError, OSError):
        return []
    repo_name = repo.rsplit("/", 1)[-1]
    prefix = f"{repo_name}-{branch}/"
    lowered_tags = [tag.lower() for tag in tags if tag]
    # 正文匹配词集：资金流标签 ∪ 通用资金流标记词（桥 / 混币 / 洗钱 / 追踪…）
    content_words = [w.lower() for w in set(tags) | set(FUND_FLOW_MARKERS) if w]
    _EXCLUDED_PATH_PARTS = ("academy/", "/.github/", "contributing.md")
    items: list[FeedItem] = []
    try:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            path = member.name
            if path.startswith(prefix):
                path = path[len(prefix):]
            if not _MD_SUFFIX_RE.search(path):
                continue
            lowered_path = path.lower()
            if any(part in lowered_path for part in _EXCLUDED_PATH_PARTS):
                continue
            if lowered_path == "readme.md":
                continue  # 根导航页不入池
            try:
                raw_content = tar.extractfile(member)
                content = (
                    raw_content.read().decode("utf-8", errors="replace")
                    if raw_content else ""
                )
            except OSError:
                continue
            lowered_content = content.lower()
            hit = any(tag in lowered_path for tag in lowered_tags) or any(
                word in lowered_content for word in content_words
            )
            if lowered_tags and not hit:
                continue
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
            title = path.rsplit("/", 1)[-1]
            items.append(FeedItem(url=url, title=title, content_html=content))
            if len(items) >= cap:
                break
    finally:
        tar.close()
    return items


# ---------------------------------------------------------------------------
# 离线 Mock 采集器（--dry-run / --mock / 单元测试）
# ---------------------------------------------------------------------------
class MockFetcher(BaseFetcher):
    """完全离线的内存夹具采集器：不发任何网络请求。"""

    def __init__(self, *, items=None, pages=None) -> None:
        self._items: dict[str, list[FeedItem]] = {
            key: list(value) for key, value in (items or {}).items()
        }
        self._pages: dict[str, str] = dict(pages or {})
        self.fetch_log: list[str] = []
        self.discover_log: list[str] = []

    def discover(self, source: Source, vendor: Vendor | None = None) -> list[FeedItem]:
        self.discover_log.append(source.url)
        # 同名共享源（如 DeFiHackLabs）按 "url|vendor.code" 键分流；
        # 无厂商区分键时回退 URL 键（兼容既有夹具）。
        if vendor is not None:
            scoped_key = f"{source.url}|{vendor.code}"
            if scoped_key in self._items:
                return list(self._items[scoped_key])
        return list(self._items.get(source.url, ()))

    def fetch(self, url: str) -> str:
        self.fetch_log.append(url)
        page = self._pages.get(url)
        if page is None:
            raise FetchError(f"mock page not found: {url}")
        return page


_MOCK_SENTENCES = (
    "The attacker moved the stolen assets across two EVM chains using a custodial bridge within the first six hours.",
    "On-chain fund flow analysis shows the laundering process split the proceeds into forty-seven intermediate wallets.",
    "Tracing teams correlated the deposit pattern with a known money laundering cluster previously flagged by AML screening.",
    "A significant share of the funds was later funneled through a non-custodial mixer in four tranches of unequal size.",
    "The post-mortem reconstructs the complete fund flow graph, including bridge, mixer and cash-out endpoints.",
    "Investigators identified the laundering pipeline through temporal clustering of transaction nonces and gas price signatures.",
    "Freeze requests were issued against nine exchange deposit addresses within hours of the first alert.",
    "The report documents the laundering typology of split, bridge, mix and re-aggregate, matching known AML patterns.",
    "Cross-chain tracing required correlating wrapped asset mint events with their upstream collateral burns.",
    "The conclusion outlines early-warning detection heuristics for similar cross-chain money laundering schemes.",
)


def build_mock_page(vendor: Vendor, title: str, index: int) -> str:
    """构造一篇含 Header / Nav / 广告 / 侧边栏 / 脚本噪声的合成研报页。"""
    paragraphs = []
    for p in range(6):
        sentences = [_MOCK_SENTENCES[(p * 2 + k) % len(_MOCK_SENTENCES)] for k in range(2)]
        paragraphs.append(f"<p>{' '.join(sentences)} AML {vendor.name} case {index}.</p>")
    body = "\n".join(paragraphs)
    month = ((index - 1) % 12) + 1
    return f"""<!DOCTYPE html>
<html>
<head>
<title>{title}</title>
<meta name="article:published_time" content="2024-{month:02d}-15T08:00:00+00:00">
<style>body{{font-family:serif}}</style>
</head>
<body>
<header><nav><a href="/">Home</a><a href="/about">About</a><a href="/pricing">Pricing</a></nav></header>
<div class="ad-banner">Sponsored: BUY NOW — guaranteed 100x returns!</div>
<div class="sidebar recommend">Related ads: click here for free tokens.</div>
<article><h1>{title}</h1>{body}</article>
<footer>© {vendor.name}. All rights reserved. Privacy Policy. Cookies.</footer>
<script>window.__tracker = 1;</script>
</body>
</html>"""


def build_mock_world(per_vendor: int = 3) -> MockFetcher:
    """构造四厂商合成采集世界（每厂商 per_vendor 篇，键为各自首个数据源）。"""
    items: dict[str, list[FeedItem]] = {}
    pages: dict[str, str] = {}
    for vendor in VENDORS:
        source_url = vendor.sources[0].url
        vendor_items: list[FeedItem] = []
        for i in range(1, per_vendor + 1):
            url = f"https://mock.local/{vendor.code}/case-{i}"
            title = (
                f"{vendor.name} Incident Report #{i}: Cross-Chain Money Laundering "
                "and Fund Flow Tracing Post-Mortem"
            )
            publish_date = f"2024-{((i - 1) % 12) + 1:02d}-15"
            vendor_items.append(FeedItem(url=url, title=title, publish_date=publish_date))
            pages[url] = build_mock_page(vendor, title, i)
        items[source_url] = vendor_items
    return MockFetcher(items=items, pages=pages)
