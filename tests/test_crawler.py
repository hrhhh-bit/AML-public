"""tools/crawler 数据采集子系统的离线测试套件。

全部用例均通过 unittest.mock / 内存 MockFetcher 模拟 HTTP 响应，
不发起任何真实外网请求。覆盖四大验收维度：

1. 总目标驱动调度、厂商不均等分布健康退出与防垄断软上限；
2. 正文高保真提取与 DOM 降噪（含字符数准入过滤）；
3. Manifest 幂等性、增量写入与 RFC 4180 Schema 合规（字段与 .txt 一一对应）；
4. 物理隔离防御（不触碰 src/ 任何模块与 data/ 生产物理知识库）。
"""

from __future__ import annotations

import csv
import re
import urllib.error
from collections import Counter
from pathlib import Path
from unittest import mock

import pytest

from tools.crawler.crawl_reports import Crawler, main
from tools.crawler.extractor import (
    MAX_CHARS,
    MIN_CHARS,
    analyze_fund_flow_evidence,
    extract_main_text,
    extract_publish_date,
    extract_title,
    normalize_iso_date,
    passes_length_filter,
    slugify,
)
from tools.crawler.fetcher import (
    DEFAULT_USER_AGENT,
    FeedItem,
    FetchError,
    HttpFetcher,
    MockFetcher,
    build_mock_page,
    build_mock_world,
    is_github_file_url,
    is_github_host,
    is_noise_url,
    parse_github_tarball,
    parse_github_tree,
    to_raw_github_url,
)
from tools.crawler.filters import (
    NEGATIVE_KEYWORDS,
    is_negative_text,
    is_negative_title,
    is_prunable_record,
)
from tools.crawler.manifest import MANIFEST_HEADERS, ManifestStore
from tools.crawler.prune_reports import (
    backup_raw_reports,
    prune_records,
    renumber_records,
    run_prune,
)
from tools.crawler.vendor_registry import (
    AML_KEYWORDS,
    CERTIK_INCIDENT_PATH_FRAGMENTS,
    VENDORS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_KB = PROJECT_ROOT / "data" / "distilled_kb.json"
PRODUCTION_OUT = PROJECT_ROOT / "data" / "raw_reports"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _snapshot(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    return {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}


def _make_headers(content_type: str):
    from email.message import Message

    message = Message()
    message["Content-Type"] = content_type
    return message


def _flood_world(n: int = 30) -> MockFetcher:
    """每厂商 n 篇候选的"洪泛"夹具，用于验证配额熔断。"""
    items: dict[str, list[FeedItem]] = {}
    pages: dict[str, str] = {}
    for vendor in VENDORS:
        source_url = vendor.sources[0].url
        vendor_items: list[FeedItem] = []
        for i in range(1, n + 1):
            url = f"https://mock.local/{vendor.code}/flood-{i}"
            title = f"{vendor.name} flood report {i}"
            vendor_items.append(FeedItem(url=url, title=title, publish_date="2024-01-01"))
            pages[url] = build_mock_page(vendor, title, i)
        items[source_url] = vendor_items
    return MockFetcher(items=items, pages=pages)


def _uneven_world() -> MockFetcher:
    """厂商数量不均等的世界：SlowMist 10 / BlockSec 5 / PeckShield 0 / CertiK 12。"""
    counts = {"slowmist": 10, "blocksec": 5, "peckshield": 0, "certik": 12}
    items: dict[str, list[FeedItem]] = {}
    pages: dict[str, str] = {}
    for vendor in VENDORS:
        source_url = vendor.sources[0].url
        vendor_items: list[FeedItem] = []
        for i in range(1, counts[vendor.code] + 1):
            url = f"https://mock.local/{vendor.code}/uneven-{i}"
            title = f"{vendor.name} uneven report {i}"
            vendor_items.append(FeedItem(url=url, title=title, publish_date="2024-01-01"))
            pages[url] = build_mock_page(vendor, title, i)
        items[source_url] = vendor_items
    return MockFetcher(items=items, pages=pages)


def _plain_page(title: str) -> str:
    """无日期元信息的干净页面：用于验证未知日期放行与 manifest 留空标注。"""
    body = "On-chain fund flow analysis and money laundering tracing across EVM chains. " * 10
    return (
        f"<html><head><title>{title}</title></head><body><article>"
        f"<h1>{title}</h1><p>{body}</p></article></body></html>"
    )


def _sample_record(report_id: str, url: str, title: str = "") -> dict:
    return {
        "report_id": report_id,
        "vendor": "SlowMist",
        "title": title or f"Sample report {report_id}",
        "publish_date": "2024-01-15",
        "matched_kw": "AML, fund flow",
        "url": url,
        "filename": f"{report_id}_2024-01-15.txt",
        "has_fund_flow": "",
    }


# ---------------------------------------------------------------------------
# 检索词无偏性：剔除具体实体与行政制裁噪声
# ---------------------------------------------------------------------------
def test_aml_keywords_are_unbiased_entity_free():
    assert AML_KEYWORDS == (
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
    banned_entities = {"Tornado Cash", "mixer", "sanctions", "OFAC", "freeze"}
    assert not (set(AML_KEYWORDS) & banned_entities)


# ---------------------------------------------------------------------------
# 维度 1：总目标驱动调度与防垄断软上限
# ---------------------------------------------------------------------------
def test_uneven_vendor_distribution_healthy_exit(tmp_path):
    """厂商可采报告数量不均（10/5/0/12）：采尽即自然切换，健康退出并保留真实分布。"""
    world = _uneven_world()
    crawler = Crawler(fetcher=world, data_dir=tmp_path, total_quota=100, max_per_vendor=None)
    report = crawler.run()
    assert {code: stats.saved for code, stats in report.items()} == {
        "slowmist": 10, "blocksec": 5, "peckshield": 0, "certik": 12,
    }
    assert sum(s.saved for s in report.values()) == 27
    assert all(s.errors == 0 for s in report.values())
    # 每个厂商的首个数据源只被检索一次（单遍扫描，不回头凑数）
    for vendor in VENDORS:
        assert world.discover_log.count(vendor.sources[0].url) == 1
    # 落盘与真实分布一一对应
    rows = list(crawler.manifest.iter_rows())
    assert len(rows) == 27
    assert len(list(tmp_path.glob("*.txt"))) == 27


def test_total_quota_is_primary_stop_condition(tmp_path):
    """总目标 --total 为主停止条件：达标即优雅退出，后续厂商零抓取。"""
    world = _flood_world(n=30)
    crawler = Crawler(fetcher=world, data_dir=tmp_path, total_quota=15, max_per_vendor=None)
    report = crawler.run()
    assert sum(s.saved for s in report.values()) == 15
    assert report["slowmist"].saved == 15
    assert report["blocksec"].saved == 0
    assert report["peckshield"].saved == 0
    assert report["certik"].saved == 0
    # 达标后立即停止：不产生任何多余抓取，后续厂商数据源不被检索
    assert len(world.fetch_log) == 15
    assert world.discover_log.count(VENDORS[1].sources[0].url) == 0


def test_max_per_vendor_soft_cap_prevents_monopoly(tmp_path):
    """防垄断软上限：单厂商采入封顶，但绝不阻断其他厂商。"""
    world = _flood_world(n=30)
    crawler = Crawler(fetcher=world, data_dir=tmp_path, total_quota=30, max_per_vendor=5)
    report = crawler.run()
    assert {code: stats.saved for code, stats in report.items()} == {
        "slowmist": 5, "blocksec": 5, "peckshield": 5, "certik": 5,
    }
    # 未达总目标，但四大厂商均已采尽（单遍扫描自然结束）
    assert sum(s.saved for s in report.values()) == 20
    fetch_by_vendor = Counter(url.split("/")[3] for url in world.fetch_log)
    assert all(fetch_by_vendor[code] == 5 for code in ("slowmist", "blocksec", "peckshield", "certik"))


def test_max_per_vendor_cap_accumulates_across_reruns(tmp_path):
    """防垄断软上限跨轮累计：台账存量 + 本轮采入封顶，不因重跑突破。"""
    world = _flood_world(n=30)
    c1 = Crawler(fetcher=world, data_dir=tmp_path, total_quota=100, max_per_vendor=18)
    c1.run()
    assert c1.manifest.vendor_count("slowmist") == 18

    # 换一批全新的候选源（模拟新一轮采集），软上限应按台账存量收紧
    items: dict[str, list[FeedItem]] = {}
    pages: dict[str, str] = {}
    vendor = VENDORS[0]
    items[vendor.sources[0].url] = []
    for i in range(30, 60):
        url = f"https://mock.local/slowmist/round2-{i}"
        title = f"SlowMist round2 report {i}"
        items[vendor.sources[0].url].append(FeedItem(url=url, title=title, publish_date="2024-02-01"))
        pages[url] = build_mock_page(vendor, title, i)
    world2 = MockFetcher(items=items, pages=pages)
    c2 = Crawler(fetcher=world2, data_dir=tmp_path, total_quota=100, max_per_vendor=20)
    report2 = c2.run()
    assert report2["slowmist"].saved == 2            # 20 - 18 = 2，封顶后自然切换
    assert c2.manifest.vendor_count("slowmist") == 20
    assert len(list(tmp_path.glob("rep_slowmist_*.txt"))) == 20  # 磁盘与台账一致


# ---------------------------------------------------------------------------
# 时间窗口过滤（--since）
# ---------------------------------------------------------------------------
def test_since_time_window_filters_stale_reports(tmp_path):
    """早于 --since 的旧报告跳过；边界与未知日期放行（未知日期 manifest 留空标注）。"""
    vendor = VENDORS[0]
    source_url = vendor.sources[0].url
    urls = {
        "old": "https://mock.local/slowmist/old-1",
        "new": "https://mock.local/slowmist/new-1",
        "boundary": "https://mock.local/slowmist/boundary-1",
        "undated": "https://mock.local/slowmist/undated-1",
    }
    items = {
        source_url: [
            FeedItem(url=urls["old"], title="SlowMist old report", publish_date="2020-06-01"),
            FeedItem(url=urls["new"], title="SlowMist new report", publish_date="2024-06-01"),
            FeedItem(url=urls["boundary"], title="SlowMist boundary report", publish_date="2021-01-01"),
            FeedItem(url=urls["undated"], title="SlowMist undated report", publish_date=""),
        ]
    }
    pages = {url: _plain_page(title) for url, title in (
        (urls["old"], "SlowMist old report"),
        (urls["new"], "SlowMist new report"),
        (urls["boundary"], "SlowMist boundary report"),
        (urls["undated"], "SlowMist undated report"),
    )}
    crawler = Crawler(
        fetcher=MockFetcher(items=items, pages=pages),
        data_dir=tmp_path,
        total_quota=40,
        since="2021-01-01",
    )
    report = crawler.run()
    stats = report["slowmist"]
    assert stats.skipped_before_since == 1  # 仅 2020-06-01 被时间窗过滤
    assert stats.saved == 3

    rows = list(crawler.manifest.iter_rows())
    by_url = {row["url"]: row for row in rows}
    assert urls["old"] not in by_url
    assert by_url[urls["new"]]["publish_date"] == "2024-06-01"
    assert by_url[urls["boundary"]]["publish_date"] == "2021-01-01"  # 边界日期放行
    assert by_url[urls["undated"]]["publish_date"] == ""  # 未知日期放行并留空标注


# ---------------------------------------------------------------------------
# 维度 2：正文高保真提取与 DOM 降噪
# ---------------------------------------------------------------------------
NOISY_HTML = """<!DOCTYPE html>
<html>
<head>
<title>AML Incident Post-Mortem: Fund Flow Tracing</title>
<meta name="article:published_time" content="2024-03-15T10:00:00+00:00">
</head>
<body>
<header><nav><a href="/">Home</a><a href="/about">About Us</a><a href="/pricing">Pricing</a></nav></header>
<div class="ad-banner">Sponsored: BUY NOW — guaranteed 100x returns!</div>
<div class="sidebar recommend">Related ads: click here for free tokens.</div>
<aside class="related-articles">More stories you may like</aside>
<script>window.__tracker = 1; var ad = "sneaky ad text";</script>
<article>
<h1>AML Incident Post-Mortem: Fund Flow Tracing</h1>
<p>The attacker moved the stolen assets across two EVM chains using a custodial bridge within the first six hours.</p>
<p>On-chain fund flow analysis shows the laundering process split the proceeds into forty-seven intermediate wallets.</p>
<p>Tracing teams correlated the deposit pattern with a known money laundering cluster previously flagged by AML screening.</p>
<p>A significant share of the funds was later funneled through a non-custodial mixer in four tranches of unequal size.</p>
<p>The post-mortem reconstructs the complete fund flow graph, including bridge, mixer and cash-out endpoints.</p>
</article>
<footer>© 2024 Vendor Inc. All rights reserved. Privacy Policy. Cookies.</footer>
</body>
</html>"""


def test_extraction_denoising_and_length_filter():
    text = extract_main_text(NOISY_HTML, "https://example.com/reports/1")
    lowered = text.lower()
    # 正文主体完整保留
    assert "fund flow analysis" in lowered
    assert "money laundering" in lowered
    assert "post-mortem" in lowered
    # 广告 / 导航 / 侧边推荐 / 脚本 / 页脚样板全部剥离
    assert "buy now" not in lowered
    assert "free tokens" not in lowered
    assert "sneaky ad text" not in lowered
    assert "about us" not in lowered
    assert "all rights reserved" not in lowered
    # 字符数准入：落在 [500, 50000] 区间
    assert passes_length_filter(text)
    assert MIN_CHARS <= len(text) <= MAX_CHARS


def test_title_and_publish_date_extraction():
    assert extract_title(NOISY_HTML) == "AML Incident Post-Mortem: Fund Flow Tracing"
    assert extract_publish_date(NOISY_HTML, "https://example.com/reports/1") == "2024-03-15"
    assert extract_publish_date("<html></html>", "https://x.com/blog/2024/07/09/a") == "2024-07-09"


def test_length_filter_boundaries():
    assert passes_length_filter("x" * (MIN_CHARS - 1)) is False
    assert passes_length_filter("x" * MIN_CHARS) is True
    assert passes_length_filter("x" * MAX_CHARS) is True
    assert passes_length_filter("x" * (MAX_CHARS + 1)) is False
    assert passes_length_filter(extract_main_text("<html><body><p>tiny page</p></body></html>")) is False


def test_date_normalization_and_slugify():
    assert normalize_iso_date("Wed, 12 Feb 2025 10:00:00 +0000") == "2025-02-12"
    assert normalize_iso_date("2024/3/5") == "2024-03-05"
    assert normalize_iso_date("2024-02-30") == ""  # 非法日期
    assert normalize_iso_date("garbage") == ""
    assert slugify("SlowMist: AML Report #1（洗钱资金追踪）") == "slowmist-aml-report-1"


# ---------------------------------------------------------------------------
# 维度 3：Manifest 幂等性、增量写入与 RFC 4180 合规
# ---------------------------------------------------------------------------
def test_manifest_schema_idempotency_and_incremental_append(tmp_path):
    csv_path = tmp_path / "manifest.csv"
    store = ManifestStore(csv_path)
    rec = _sample_record("rep_slowmist_001", "https://x.com/a", "Sample report 001")
    assert store.add(rec) is True
    assert store.add(rec) is False  # 同 URL 重复 → 拒绝
    assert store.has_url("https://x.com/a")
    assert store.has_title("Sample Report 001")  # 标题去重大小写不敏感

    # 新实例重载：去重集合与自增编号均从磁盘恢复
    store2 = ManifestStore(csv_path)
    assert store2.has_url("https://x.com/a")
    assert store2.next_report_id("slowmist") == "rep_slowmist_002"
    assert store2.add(rec) is False
    assert store2.add(_sample_record("rep_slowmist_002", "https://x.com/b")) is True
    assert store2.next_report_id("slowmist") == "rep_slowmist_003"

    # CSV 结构合规：表头 / 行数 / CRLF（RFC 4180）
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    raw = csv_path.read_bytes()
    assert rows[0] == list(MANIFEST_HEADERS)
    assert len(rows) == 3
    assert raw.count(b"\r\n") == len(rows)

    # 字段规范：report_id 格式 / 人工审核列留空
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    assert all(re.fullmatch(r"rep_[a-z0-9]+_\d{3}", r["report_id"]) for r in records)
    assert all(r["has_fund_flow"] == "" for r in records)


def test_manifest_rfc4180_quoting_roundtrip(tmp_path):
    store = ManifestStore(tmp_path / "manifest.csv")
    tricky_title = 'He said "AML is key", money laundering & fund flow'
    store.add(_sample_record("rep_certik_001", "https://x.com/q", tricky_title))
    reloaded = list(ManifestStore(tmp_path / "manifest.csv").iter_rows())
    assert reloaded[0]["title"] == tricky_title


def test_manifest_fields_match_disk_artifacts_and_rerun_idempotent(tmp_path):
    world = build_mock_world(per_vendor=2)
    c1 = Crawler(fetcher=world, data_dir=tmp_path, total_quota=8)
    report = c1.run()
    assert sum(s.saved for s in report.values()) == 8

    manifest_path = tmp_path / "manifest.csv"
    assert manifest_path.exists()
    manifest_before = manifest_path.read_bytes()

    rows = list(ManifestStore(manifest_path).iter_rows())
    assert len(rows) == 8
    for row in rows:
        # manifest 字段与实际落盘的 .txt 文本严格一一对应
        fp = tmp_path / row["filename"]
        assert fp.exists()
        body = fp.read_text(encoding="utf-8")
        assert MIN_CHARS <= len(body) <= MAX_CHARS
        assert fp.name.startswith(row["report_id"])  # {report_id}_{date_or_slug}.txt
        assert row["has_fund_flow"] == ""
        assert row["vendor"] in {"SlowMist", "BlockSec", "PeckShield", "CertiK"}
        assert row["publish_date"].startswith("2024-")
        assert row["matched_kw"]

    # 幂等重跑：第二次运行 0 新增、manifest 字节级不变、txt 文件不重复
    c2 = Crawler(fetcher=world, data_dir=tmp_path, total_quota=8)
    report2 = c2.run()
    assert sum(s.saved for s in report2.values()) == 0
    assert all(s.skipped_duplicate > 0 for s in report2.values())
    assert manifest_path.read_bytes() == manifest_before
    assert len(list(tmp_path.glob("*.txt"))) == 8


# ---------------------------------------------------------------------------
# 维度 4：物理隔离防御
# ---------------------------------------------------------------------------
def test_physical_isolation_static_no_src_imports():
    crawler_dir = PROJECT_ROOT / "tools" / "crawler"
    files = sorted(crawler_dir.rglob("*.py"))
    assert files
    combined = "\n".join(f.read_text(encoding="utf-8") for f in files)
    # 严禁 import src/ 任何模块（状态机 / RAG / Agent 决策）
    assert not re.search(
        r"^\s*(from|import)\s+(src|aml_rag|aml_agent|aml_env)\b", combined, re.M
    )
    # 严禁引用生产物理知识库
    assert "distilled_kb" not in combined


def test_physical_isolation_runtime_does_not_touch_production_artifacts(tmp_path):
    assert PRODUCTION_KB.exists()
    kb_before = PRODUCTION_KB.read_bytes()
    out_before = _snapshot(PRODUCTION_OUT)
    crawler = Crawler(
        fetcher=build_mock_world(per_vendor=1),
        data_dir=tmp_path,
        total_quota=4,
    )
    crawler.run()
    assert PRODUCTION_KB.read_bytes() == kb_before  # 生产知识库字节级不变
    assert _snapshot(PRODUCTION_OUT) == out_before  # 生产采集目录零写入
    assert len(list(tmp_path.glob("*.txt"))) == 4   # 产物只落在指定 data_dir


# ---------------------------------------------------------------------------
# HTTP 采集器（unittest.mock 模拟响应，杜绝真实外网请求）
# ---------------------------------------------------------------------------
def test_http_fetcher_fetch_with_mocked_urlopen():
    payload = b"<html><body><p>hello</p></body></html>"
    response = mock.MagicMock()
    response.read.return_value = payload
    response.headers = _make_headers("text/html; charset=utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
        fetcher = HttpFetcher(delay=0, retries=0)
        assert fetcher.fetch("https://example.com/x") == "<html><body><p>hello</p></body></html>"
    assert urlopen.call_count == 1


def test_http_fetcher_retries_then_raises():
    with mock.patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("boom")
    ) as urlopen:
        fetcher = HttpFetcher(delay=0, retries=2)
        with pytest.raises(FetchError):
            fetcher.fetch("https://example.com/x")
    assert urlopen.call_count == 3  # 1 次原始请求 + 2 次重试


# ---------------------------------------------------------------------------
# URL 过滤器：黑名单拦截 + GitHub 专用文件规则
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "noise_url",
    [
        "https://github.com/signup?source=login",
        "https://github.com/login",
        "https://github.com/signup",
        "https://medium.com/tag/defi",
        "https://example.com/pricing",
        "https://example.com/terms",
        "https://example.com/privacy",
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/settings",
        "https://example.com/auth/signin",
        "https://example.com/features",
    ],
)
def test_noise_url_blacklist_blocks_non_article_links(noise_url):
    assert is_noise_url(noise_url)


def test_noise_url_blacklist_spares_article_links():
    for ok_url in (
        "https://github.com/SunWeb3Sec/DeFiHackLabs/blob/main/README.md",
        "https://medium.com/@SlowMist/cross-chain-aml-tracing-abc123",
        "https://www.slowmist.com/articles/aml-fund-flow.html",
    ):
        assert not is_noise_url(ok_url)


def test_github_host_detection():
    assert is_github_host("https://github.com/slowmist/Knowledge-Base")
    assert is_github_host("https://raw.githubusercontent.com/x/y/main/a.md")
    assert not is_github_host("https://medium.com/feed/@SlowMist")
    assert not is_github_host("https://www.slowmist.com/articles/x.html")


@pytest.mark.parametrize(
    "file_url",
    [
        "https://github.com/a/b/blob/main/README.md",
        "https://github.com/a/b/blob/main/docs/post-mortem.markdown",
        "https://github.com/a/b/blob/main/reports/2024.md?raw=true",
        "https://github.com/a/b/raw/main/report.md",
        "https://raw.githubusercontent.com/a/b/main/report.md",
    ],
)
def test_github_file_url_rules_accept_documents(file_url):
    assert is_github_file_url(file_url)


@pytest.mark.parametrize(
    "non_file_url",
    [
        "https://github.com/signup",
        "https://github.com/login",
        "https://github.com/slowmist/Knowledge-Base",
        "https://github.com/slowmist/Knowledge-Base/tree/main",
        "https://github.com/slowmist/Knowledge-Base/issues",
        "https://github.com/marketplace",
    ],
)
def test_github_file_url_rules_reject_non_documents(non_file_url):
    assert not is_github_file_url(non_file_url)


@pytest.mark.parametrize(
    "binary_url",
    [
        "https://github.com/slowmist/Knowledge-Base/blob/master/mindmaps/evil_blockchain.png",
        "https://github.com/a/b/blob/main/poc/exploit.sol",
        "https://raw.githubusercontent.com/a/b/main/img/flow.jpg",
    ],
)
def test_github_file_url_rules_reject_binary_assets(binary_url):
    """GitHub 文件规则收紧：图片 / 代码 / 二进制资产一律拒绝（研报纯文本池）。"""
    assert not is_github_file_url(binary_url)


def test_discover_links_filters_github_signup_and_noise():
    """GitHub 页面链接发现：拦截 signup/login 等噪音，只保留具体文档文件。"""
    html = """
    <html><body>
    <a href="https://github.com/signup?source=login">Sign up</a>
    <a href="https://github.com/login">Sign in</a>
    <a href="/SunWeb3Sec/DeFiHackLabs/blob/main/README.md">README.md</a>
    <a href="/SunWeb3Sec/DeFiHackLabs/blob/main/blocksec_postmortem.md">blocksec_postmortem.md</a>
    <a href="/SunWeb3Sec/DeFiHackLabs/tree/main">repository root</a>
    <a href="/about">About</a>
    <a href="/settings/profile">Settings</a>
    </body></html>
    """
    items = HttpFetcher(delay=0).discover_links(
        html, "https://github.com/SunWeb3Sec/DeFiHackLabs"
    )
    urls = [item.url for item in items]
    # blob 页面链接自动转换为 raw 纯文本 CDN
    assert urls == [
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/README.md",
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/blocksec_postmortem.md",
    ]
    assert not any("signup" in u or "login" in u for u in urls)


def test_discover_links_non_github_keeps_article_pages():
    """非 GitHub 页面：黑名单仍生效，但普通文章页链接不被误伤。"""
    html = (
        '<a href="/@SlowMist/aml-fund-flow-report">AML report</a>'
        '<a href="/pricing">Pricing</a>'
        '<a href="/tag/defi">Defi tag page</a>'
    )
    items = HttpFetcher(delay=0).discover_links(html, "https://medium.com/")
    urls = [item.url for item in items]
    assert urls == ["https://medium.com/@SlowMist/aml-fund-flow-report"]


# ---------------------------------------------------------------------------
# RSS 原地正文直提（In-line Extraction）与 GitHub raw 转换
# ---------------------------------------------------------------------------
def test_default_user_agent_is_browser_style():
    """HttpFetcher 必须标配浏览器 UA，绝不用 Python 默认 urllib UA。"""
    assert "Python-urllib" not in DEFAULT_USER_AGENT
    assert DEFAULT_USER_AGENT.startswith("Mozilla/5.0")
    assert "AppleWebKit" in DEFAULT_USER_AGENT
    assert "Chrome/" in DEFAULT_USER_AGENT


def test_github_blob_url_converted_to_raw():
    assert (
        to_raw_github_url("https://github.com/a/b/blob/main/docs/report.md")
        == "https://raw.githubusercontent.com/a/b/main/docs/report.md"
    )
    # 带查询参数 / 锚点的 blob 链接同样转换（剥除后改写）
    assert (
        to_raw_github_url("https://github.com/a/b/blob/main/report.md?raw=true#readme")
        == "https://raw.githubusercontent.com/a/b/main/report.md"
    )
    # 非 blob 结构原样返回
    assert to_raw_github_url("https://example.com/x") == "https://example.com/x"
    assert (
        to_raw_github_url("https://github.com/a/b/tree/main")
        == "https://github.com/a/b/tree/main"
    )


RSS_INLINE_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>SlowMist Medium Feed</title>
<item>
<title>FATF AML Inline Report</title>
<link>https://slowmist.medium.com/fatf-report-abc123</link>
<pubDate>Wed, 15 Mar 2024 08:00:00 +0000</pubDate>
<description><![CDATA[<p>SHORT EXCERPT ONLY</p>]]></description>
<content:encoded><![CDATA[<article><h1>FATF AML Inline Report</h1><p>FULL BODY MARKER: fund flow analysis across EVM chains.</p></article>]]></content:encoded>
</item>
</channel></rss>"""


def test_rss_parse_extracts_content_encoded_inline_html():
    """RSS 解析升级：优先提取 content:encoded 完整正文，summary 保留 description。"""
    items = HttpFetcher(delay=0).parse_feed(RSS_INLINE_SAMPLE)
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://slowmist.medium.com/fatf-report-abc123"
    assert item.publish_date == "2024-03-15"
    assert "FULL BODY MARKER" in item.content_html  # 优先 content:encoded
    assert "SHORT EXCERPT ONLY" in item.summary


def test_rss_description_fallback_without_content_encoded():
    """无 content:encoded 时回退 description 作为原地正文。"""
    xml = (
        "<rss><channel><item><title>T</title><link>https://x.com/t</link>"
        "<description><![CDATA[<p>fallback body</p>]]></description>"
        "</item></channel></rss>"
    )
    items = HttpFetcher(delay=0).parse_feed(xml)
    assert items[0].content_html == "<p>fallback body</p>"


def test_scheduler_extracts_rss_inline_without_second_fetch(tmp_path):
    """携带 content_html 的条目直接清洗落盘，严禁二次 HTTP 请求（Medium 403 规避）。"""
    vendor = VENDORS[0]
    source_url = vendor.sources[0].url
    paragraphs = " ".join(
        f"<p>On-chain fund flow analysis paragraph {i} about money laundering tracing.</p>"
        for i in range(10)
    )
    item = FeedItem(
        url="https://slowmist.medium.com/fatf-report-abc123",
        title="AML Inline Report",
        publish_date="2024-03-15",
        content_html=f"<article><h1>AML Inline Report</h1>{paragraphs}</article>",
    )
    fetcher = MockFetcher(items={source_url: [item]}, pages={})
    crawler = Crawler(fetcher=fetcher, data_dir=tmp_path, total_quota=10, max_per_vendor=None)
    report = crawler.run()
    stats = report["slowmist"]
    assert stats.saved == 1
    assert stats.inline == 1
    assert stats.fetched == 0
    assert fetcher.fetch_log == []  # 零二次请求
    rows = list(crawler.manifest.iter_rows())
    assert len(rows) == 1
    assert rows[0]["url"] == "https://slowmist.medium.com/fatf-report-abc123"
    body = (tmp_path / rows[0]["filename"]).read_text(encoding="utf-8")
    assert "money laundering" in body
    assert "paragraph 9" in body


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>SlowMist Feed</title>
<item><title>Case A</title><link>https://x.com/a</link><pubDate>Wed, 12 Feb 2025 10:00:00 +0000</pubDate><description>fund flow</description></item>
<item><title>Case B</title><link>https://x.com/b</link></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>BlockSec</title>
<entry><title>Entry A</title><link href="https://x.com/e1"/><published>2025-02-13T08:30:00Z</published></entry>
<entry><title>Entry B</title><link href="https://x.com/e2"/><updated>2025-02-14T00:00:00Z</updated></entry>
</feed>"""


@pytest.mark.parametrize(
    "xml_text,expected",
    [
        (RSS_SAMPLE, [("Case A", "https://x.com/a", "2025-02-12"), ("Case B", "https://x.com/b", "")]),
        (ATOM_SAMPLE, [("Entry A", "https://x.com/e1", "2025-02-13"), ("Entry B", "https://x.com/e2", "2025-02-14")]),
    ],
)
def test_feed_parsing_rss_and_atom(xml_text, expected):
    items = HttpFetcher(delay=0).parse_feed(xml_text)
    assert [(i.title, i.url, i.publish_date) for i in items] == expected


# ---------------------------------------------------------------------------
# CLI 验收：--dry-run / --mock 全流程平稳跑通
# ---------------------------------------------------------------------------
def test_cli_since_invalid_date_exits_2(capsys):
    """--since 非法日期：argparse 校验失败并以退出码 2 终止。"""
    with pytest.raises(SystemExit) as excinfo:
        main(["--mock", "--since", "not-a-date"])
    assert excinfo.value.code == 2
    assert "invalid" in capsys.readouterr().err.lower()


def test_cli_dry_run_end_to_end(capsys):
    assert PRODUCTION_KB.exists()
    kb_before = PRODUCTION_KB.read_bytes()
    out_before = _snapshot(PRODUCTION_OUT)

    assert main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "TELEMETRY" in out
    assert "[WINDOW]" in out
    assert "since 2021-01-01" in out

    # 干跑产物落在临时目录：manifest 与 .txt 一一对应
    match = re.search(r"staged output directory:\s*(.+?)\s*\(production data untouched\)", out)
    assert match
    staged = Path(match.group(1).strip())
    manifest = staged / "manifest.csv"
    assert manifest.exists()
    rows = list(ManifestStore(manifest).iter_rows())
    assert len(rows) == 12
    for row in rows:
        assert (staged / row["filename"]).exists()

    # 生产数据零写入
    assert PRODUCTION_KB.read_bytes() == kb_before
    assert _snapshot(PRODUCTION_OUT) == out_before


def test_cli_mock_with_explicit_data_dir(tmp_path):
    assert main(["--mock", "--total", "8", "--data-dir", str(tmp_path)]) == 0
    assert (tmp_path / "manifest.csv").exists()
    assert len(list(tmp_path.glob("*.txt"))) == 8
    rows = list(ManifestStore(tmp_path / "manifest.csv").iter_rows())
    assert len(rows) == 8


# ---------------------------------------------------------------------------
# v2 验收维度 5：全局负向主题词硬拦截（任务 B）
# ---------------------------------------------------------------------------
def test_negative_keyword_title_blocks_hard(tmp_path):
    """标题显著落入负向区间（FATF / Job-Seeking Phishing）：
    即使命中 AML 关键词也 100% 直接抛弃，不落盘、不发二次请求。"""
    vendor = VENDORS[0]
    source_url = vendor.sources[0].url
    items = {
        source_url: [
            FeedItem(
                url="https://slowmist.medium.com/fatf-report-gaming-risks",
                title="FATF Report | How to Understand and Address Risks in Gaming",
                publish_date="2026-09-23",
            ),
            FeedItem(
                url="https://slowmist.medium.com/job-seeking-phishing-joint-report",
                title=(
                    "Analysis | Joint Report: Job-Seeking Phishing and Laptop "
                    "Breaches with money laundering fund flow"
                ),
                publish_date="2026-09-22",
            ),
        ]
    }
    fetcher = MockFetcher(items=items, pages={})
    crawler = Crawler(
        fetcher=fetcher,
        data_dir=tmp_path,
        total_quota=10,
        max_per_vendor=None,
        enable_negative_filter=True,
    )
    report = crawler.run()
    stats = report["slowmist"]
    assert stats.saved == 0
    assert stats.skipped_negative == 2
    assert fetcher.fetch_log == []          # 标题拦截在抓取之前：零网络开销
    assert list(crawler.manifest.iter_rows()) == []  # 不落盘


def test_negative_keyword_body_blocks_hard(tmp_path):
    """正文显著落入负向区间（kyc verification）：提取后一律抛弃，不落盘。"""
    vendor = VENDORS[0]
    source_url = vendor.sources[0].url
    body = (
        "This article is a KYC verification compliance guideline summary "
        "with money laundering fund flow context paragraphs. " * 12
    )
    page = f"<html><body><article><h1>AML Screening Guide</h1><p>{body}</p></article></body></html>"
    items = {
        source_url: [
            FeedItem(
                url="https://mock.local/slowmist/screening-guide-1",
                title="AML Screening Guide",
                publish_date="2024-01-01",
            )
        ]
    }
    crawler = Crawler(
        fetcher=MockFetcher(
            items=items,
            pages={"https://mock.local/slowmist/screening-guide-1": page},
        ),
        data_dir=tmp_path,
        total_quota=10,
        max_per_vendor=None,
    )
    report = crawler.run()
    stats = report["slowmist"]
    assert stats.saved == 0
    assert stats.skipped_negative == 1
    assert list(crawler.manifest.iter_rows()) == []


def test_negative_filter_can_be_disabled(tmp_path):
    """负向硬拦截可显式关闭（防御性逃生舱）：FATF 标题恢复放行。"""
    vendor = VENDORS[0]
    source_url = vendor.sources[0].url
    body = "On-chain fund flow analysis and money laundering tracing across EVM chains. " * 10
    page = f"<html><body><article><h1>FATF AML Report</h1><p>{body}</p></article></body></html>"
    items = {
        source_url: [
            FeedItem(
                url="https://mock.local/slowmist/fatf-1",
                title="FATF AML Report",
                publish_date="2024-01-01",
            )
        ]
    }
    crawler = Crawler(
        fetcher=MockFetcher(items=items, pages={"https://mock.local/slowmist/fatf-1": page}),
        data_dir=tmp_path,
        total_quota=10,
        max_per_vendor=None,
        enable_negative_filter=False,
    )
    report = crawler.run()
    assert report["slowmist"].saved == 1
    assert report["slowmist"].skipped_negative == 0


def test_source_title_keywords_feed_signal_tightening(tmp_path):
    """feed 源标题事件词硬过滤：仅 incident/hack 类标题放行，产品/政策文丢弃。"""
    vendor = VENDORS[3]  # CertiK：Medium 源带 title_keywords
    feed_source = vendor.sources[1]
    assert feed_source.title_keywords
    items = {
        feed_source.url: [
            FeedItem(url="https://certik.medium.com/cyrus-incident-1", title="Cyrus Finance Incident Analysis"),
            FeedItem(url="https://certik.medium.com/wallet-intro-1", title="What Is Coin98? Inside the Wallet"),
            FeedItem(url="https://certik.medium.com/vasp-policy-1", title="Taiwan Virtual Asset Services Act: New VASP Rules"),
            FeedItem(url="https://certik.medium.com/hack-1", title="Verus Hack Exploit Post-Mortem"),
        ]
    }
    pages = {}
    for item in items[feed_source.url]:
        body = "On-chain fund flow analysis and money laundering tracing. " * 10
        pages[item.url] = f"<html><body><article><p>{body}</p></article></body></html>"
    crawler = Crawler(
        fetcher=MockFetcher(items=items, pages=pages),
        data_dir=tmp_path,
        total_quota=20,
        max_per_vendor=None,
    )
    report = crawler.run()
    stats = report["certik"]
    assert stats.saved == 2
    assert stats.skipped_no_match == 0   # 两篇泛文均被剪枝黑名单硬拦截
    assert stats.skipped_negative == 2   # 钱包介绍文 + VASP 政策文
    rows = list(crawler.manifest.iter_rows())
    assert {row["title"] for row in rows} == {
        "Cyrus Finance Incident Analysis",
        "Verus Hack Exploit Post-Mortem",
    }


def test_negative_keyword_list_matches_spec():
    """负向名单与任务规格逐项一致。"""
    assert NEGATIVE_KEYWORDS == (
        "FATF",
        "compliance guideline",
        "job-seeking",
        "recruitment phishing",
        "audit report summary",
        "kyc verification",
    )
    assert is_negative_title("FATF Report: Gaming Risks")
    assert is_negative_title("Job-Seeking Phishing Joint Report")
    assert is_negative_title("KYC Verification for Web3")
    assert not is_negative_title("Notional Finance Hack Analysis")
    assert is_negative_text("... an audit report summary with KYC verification ...")
    assert not is_negative_text("fund flow tracing across two EVM chains")


# ---------------------------------------------------------------------------
# v2 验收维度 6：CertiK 路径精准过滤（任务 C）
# ---------------------------------------------------------------------------
CERTIK_LISTING_HTML = """
<html><body>
<a href="/products/smart-contract-audit">Smart Contract Audit</a>
<a href="/products/kyc">KYC Verification</a>
<a href="/resources/blog/incident-analysis/liquid-network">Liquid Network Incident Analysis</a>
<a href="/resources/blog/hack/verus-hack">Verus Hack Analysis</a>
<a href="/blog/defituna-incident-analysis">DefiTuna Incident Analysis</a>
<a href="/blog/bridging-the-atlantic-why-security-is-the-real-catalyst-for-transatlantic-crypto-policy">Bridging the Atlantic Policy</a>
<a href="/blog/company-updates">Company Updates</a>
</body></html>
"""


def test_certik_path_precision_filter_blocks_commercial_pages():
    """CertiK 路径精准过滤：商业产品页硬拦截，真实事故专题链接放行。"""
    fetcher = HttpFetcher(delay=0)
    items = fetcher.discover_links(
        CERTIK_LISTING_HTML,
        "https://www.certik.com/resources",
        keywords=("incident", "hack", "exploit"),
        vendor=VENDORS[3],
        required_path_fragments=CERTIK_INCIDENT_PATH_FRAGMENTS,
    )
    urls = [item.url for item in items]
    assert not any("products" in u for u in urls)          # 商业/审计废纸全拦截
    assert not any("policy" in u for u in urls)            # 宏观政策文拦截
    assert not any("company-updates" in u for u in urls)   # 裸域名宽松匹配已剔除
    assert "https://www.certik.com/resources/blog/incident-analysis/liquid-network" in urls
    assert "https://www.certik.com/resources/blog/hack/verus-hack" in urls
    assert "https://www.certik.com/blog/defituna-incident-analysis" in urls  # incident-analysis 语义兜底


def test_certik_path_fragments_are_enforced_when_present():
    """required_path_fragments 非空：厂商名不再参与宽松匹配，路径不达标一律拦截。"""
    fetcher = HttpFetcher(delay=0)
    items = fetcher.discover_links(
        CERTIK_LISTING_HTML,
        "https://www.certik.com/resources",
        keywords=(),
        vendor=VENDORS[3],
        required_path_fragments=CERTIK_INCIDENT_PATH_FRAGMENTS,
    )
    urls = {item.url for item in items}
    # 同域（URL 本身含 certik 字符串）但路径不达标 → 拦截
    assert "https://www.certik.com/products/smart-contract-audit" not in urls
    assert "https://www.certik.com/blog/company-updates" not in urls
    assert len(urls) == 3  # 仅三个事故专题路径放行


def test_certik_registry_source_has_incident_fragments():
    """注册表本身必须携带 CertiK 事故专题路径约束。"""
    certik = VENDORS[3]
    assert any(source.required_path_fragments for source in certik.sources)
    assert CERTIK_INCIDENT_PATH_FRAGMENTS


# ---------------------------------------------------------------------------
# v2 验收维度 7：DeFiHackLabs 深度事故库解析（任务 D）
# ---------------------------------------------------------------------------
GITHUB_TREE_JSON = """
{
  "sha": "abc123",
  "tree": [
    {"path": "README.md", "type": "blob"},
    {"path": "AttackEvents/2024/Phalcon_FundFlow_Case.md", "type": "blob"},
    {"path": "AttackEvents/2024/Tornado_Cash_Laundering.md", "type": "blob"},
    {"path": "AttackEvents/2024/Cross-chain_Bridge_Exploit.md", "type": "blob"},
    {"path": "AttackEvents/2024/BlockSec_PostMortem.md", "type": "blob"},
    {"path": "AttackEvents/2024/Unrelated_Reentrancy.md", "type": "blob"},
    {"path": "tools/exploit.py", "type": "blob"},
    {"path": "AttackEvents", "type": "tree"}
  ]
}
"""


def test_defihacklabs_parse_github_tree_filters_md_and_tags():
    """GitHub 树解析：仅 .md 归档、按资金流标签过滤、产出 raw CDN 直读链接。"""
    items = parse_github_tree(
        GITHUB_TREE_JSON,
        repo="SunWeb3Sec/DeFiHackLabs",
        branch="main",
        tags=("phalcon", "blocksec", "fund flow"),
    )
    urls = [item.url for item in items]
    assert urls == [
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/Phalcon_FundFlow_Case.md",
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/BlockSec_PostMortem.md",
    ]
    # 非 .md、非标签命中、目录节点一律不进入候选
    assert all(u.endswith(".md") for u in urls)
    assert not any("exploit.py" in u or "Unrelated" in u for u in urls)


def test_defihacklabs_parse_github_tree_no_tags_accepts_all_md():
    """无标签约束时保留全部 Markdown 归档（兼容旧调用路径）。"""
    items = parse_github_tree(
        GITHUB_TREE_JSON, repo="SunWeb3Sec/DeFiHackLabs", branch="main", tags=()
    )
    assert len(items) == 6  # README + 5 篇 .md


def test_defihacklabs_parse_github_tree_bad_json_returns_empty():
    assert parse_github_tree("not-json", repo="a/b", tags=("x",)) == []


def _make_tarball(files: dict[str, str]) -> bytes:
    """构造 codeload 格式 tar.gz 字节（顶层目录 DeFiHackLabs-main/）。"""
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"DeFiHackLabs-main/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_defihacklabs_parse_github_tarball_extracts_md_and_tags():
    """codeload tarball 解析：路径或正文标签匹配、排除教程/根导航、raw 地址规范化。"""
    payload = _make_tarball(
        {
            "README.md": "# DeFiHackLabs",
            "AttackEvents/2024/Phalcon_FundFlow_Case.md": "Fund flow via Phalcon tracing.",
            "AttackEvents/2024/Tornado_Cash_Laundering.md": "Tornado laundering case.",
            "AttackEvents/2024/BlockSec_PostMortem.md": "BlockSec post-mortem.",
            "AttackEvents/2024/Unrelated_Reentrancy.md": "reentrancy only",
            "academy/solidity/01_audit/readme.md": "audit tutorial with bridge concepts",
            "tools/exploit.py": "print(1)",
        }
    )
    items = parse_github_tarball(
        payload,
        repo="SunWeb3Sec/DeFiHackLabs",
        branch="main",
        tags=("phalcon", "blocksec", "fund flow"),
    )
    urls = [item.url for item in items]
    assert urls == [
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/Phalcon_FundFlow_Case.md",
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/Tornado_Cash_Laundering.md",
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/BlockSec_PostMortem.md",
    ]
    # 正文原地直提：content_html 非空，调度器零二次请求
    assert items[0].content_html == "Fund flow via Phalcon tracing."
    assert items[1].content_html == "Tornado laundering case."
    # 根导航页、教程目录、无资金流词归档全部排除
    assert not any("README.md" in u or "academy" in u or "Unrelated" in u for u in urls)


def test_defihacklabs_parse_github_tarball_bad_payload_returns_empty():
    assert parse_github_tarball(b"not-a-tarball", repo="a/b", tags=("x",)) == []


DEFIHACK_POSTMORTEM_MD = """# Fund Flow Post-Mortem: Cross-chain Laundering

## Background
The attack drained 4,500 ETH from the vault. Fund flow analysis shows the
proceeds were moved through a multi-hop laundering pipeline. BlockSec Phalcon
detected the first suspicious transfer within minutes of the exploit and
alerted the exchange risk teams before the attacker could complete the
full money tracing evasion cycle.

## On-chain money flow
Attacker 0x111122223333444455556666777788889999AAAA
  -> Bridge: Wormhole
  -> Mixer: Tornado Cash
  -> 0xBBBbBBBbBBBbBBBbBBBbBBBbBBBbBBBbBBBbBBBb
  -> Cash-out: Binance deposit 0xCCCCcccc...

The bridge hop minted wrapped assets on the destination chain, while the
mixer hop split the proceeds into forty-seven intermediate wallets across
three tranches. On-chain fund flow reconstruction confirmed each hop with
transaction hash evidence and temporal clustering of gas price signatures.

## Money tracing conclusion
BlockSec Phalcon traced all three hops within 6 hours. The laundering
typology matches known AML patterns: split, bridge, mix and re-aggregate,
with a cross-chain cash-out endpoint at a custodial exchange.
"""


def test_defihacklabs_fund_flow_evidence_extraction_complete():
    """Markdown 事故复盘与 ASCII 链路抽取完备性：标记、边、跳数全部命中。"""
    evidence = analyze_fund_flow_evidence(DEFIHACK_POSTMORTEM_MD)
    assert evidence["has_flow"] is True
    for marker in ("fund flow", "laundering", "tornado", "cross-chain", "bridge", "phalcon"):
        assert marker in evidence["markers"]
    assert len(evidence["hop_edges"]) == 4   # 0x -> Bridge -> Mixer -> 0x -> Cash-out
    assert evidence["hop_count"] >= 4
    assert any("Bridge" in src or "Bridge" in dst for src, dst in evidence["hop_edges"])


def test_defihacklabs_fund_flow_evidence_absent_for_plain_page():
    """无资金流标记与链路的普通页面：证据为空。"""
    evidence = analyze_fund_flow_evidence(
        "This page describes smart contract gas optimization techniques."
    )
    assert evidence["has_flow"] is False
    assert evidence["markers"] == []
    assert evidence["hop_edges"] == []
    assert evidence["hop_count"] == 0


def test_defihacklabs_scheduler_end_to_end(tmp_path):
    """DeFiHackLabs 归档端到端：raw CDN 直读 Markdown → 落盘 → manifest 台账。"""
    vendor = VENDORS[1]  # BlockSec：DeFiHackLabs（Phalcon / BlockSec / Fund Flow）
    github_source = vendor.sources[3]
    assert github_source.kind == "github"
    assert github_source.fund_flow_tags
    raw_url = (
        "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/"
        "AttackEvents/2024/Phalcon_FundFlow_Case.md"
    )
    # 同名共享源按厂商分流：仅 BlockSec 命中 Phalcon / BlockSec / Fund Flow 归档
    items = {f"{github_source.url}|blocksec": [FeedItem(url=raw_url, title="Phalcon_FundFlow_Case.md")]}
    pages = {raw_url: DEFIHACK_POSTMORTEM_MD}
    crawler = Crawler(
        fetcher=MockFetcher(items=items, pages=pages),
        data_dir=tmp_path,
        total_quota=10,
        max_per_vendor=None,
    )
    report = crawler.run()
    rows = list(crawler.manifest.iter_rows())
    assert len(rows) == 1
    assert rows[0]["url"] == raw_url
    assert rows[0]["vendor"] == "BlockSec"
    assert rows[0]["has_fund_flow"] == ""  # 留待专家最终核验
    body = (tmp_path / rows[0]["filename"]).read_text(encoding="utf-8")
    assert "Tornado Cash" in body
    assert analyze_fund_flow_evidence(body)["has_flow"] is True


# ---------------------------------------------------------------------------
# v2 验收维度 8：存量剪枝、备份防线与配额重平衡（任务 A / E）
# ---------------------------------------------------------------------------
def _prunable_records() -> list[dict]:
    """迷你存量台账：3 篇噪音 + 2 篇保留（跨厂商，编号有缺口）。"""
    return [
        {
            "report_id": "rep_slowmist_001", "vendor": "SlowMist",
            "title": "FATF Report | Gaming Risks", "publish_date": "2026-09-23",
            "matched_kw": "AML", "url": "https://slowmist.medium.com/fatf-1",
            "filename": "rep_slowmist_001_2026-09-23.txt", "has_fund_flow": "",
        },
        {
            "report_id": "rep_slowmist_002", "vendor": "SlowMist",
            "title": "Job-Seeking Phishing Joint Report", "publish_date": "2026-09-22",
            "matched_kw": "AML", "url": "https://slowmist.medium.com/job-seeking-1",
            "filename": "rep_slowmist_002_2026-09-22.txt", "has_fund_flow": "",
        },
        {
            "report_id": "rep_certik_001", "vendor": "CertiK",
            "title": "Smart Contract Audit", "publish_date": "",
            "matched_kw": "certik", "url": "https://www.certik.com/products/smart-contract-audit",
            "filename": "rep_certik_001_smart-contract-audit.txt", "has_fund_flow": "",
        },
        {
            "report_id": "rep_slowmist_003", "vendor": "SlowMist",
            "title": "Notional Finance Hack Analysis", "publish_date": "2026-09-07",
            "matched_kw": "AML, fund flow", "url": "https://slowmist.medium.com/notional-hack",
            "filename": "rep_slowmist_003_2026-09-07.txt", "has_fund_flow": "",
        },
        {
            "report_id": "rep_peckshield_001", "vendor": "PeckShield",
            "title": "xWin Finance Incident: Root Cause Analysis", "publish_date": "2021-06-25",
            "matched_kw": "incident", "url": "https://peckshield.medium.com/xwin",
            "filename": "rep_peckshield_001_2021-06-25.txt", "has_fund_flow": "",
        },
    ]


def _prunable_world(tmp_path: Path) -> tuple[Path, list[dict]]:
    """构造迷你存量世界（落盘）：3 篇噪音 + 2 篇保留（跨厂商，编号有缺口）。"""
    data_dir = tmp_path / "raw_reports"
    data_dir.mkdir()
    records = _prunable_records()
    with (data_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        import csv as _csv

        writer = _csv.DictWriter(fh, fieldnames=list(MANIFEST_HEADERS))
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    for record in records:
        (data_dir / record["filename"]).write_text(
            "On-chain fund flow analysis with money laundering tracing. " * 40,
            encoding="utf-8",
        )
    return data_dir, records


def test_prune_blacklist_classification():
    """负向黑名单硬淘汰：合规 / 社工 / 商业废纸剔除，事件 / 追踪报告保留。"""
    kept, removed = prune_records(_prunable_records())
    assert len(kept) == 2
    assert len(removed) == 3
    assert all("FATF" in r["title"] or "Phishing" in r["title"] or "Audit" in r["title"] for r in removed)
    assert {r["title"] for r in kept} == {
        "Notional Finance Hack Analysis",
        "xWin Finance Incident: Root Cause Analysis",
    }


def test_prune_renumber_continuous_ids():
    """report_id 按厂商独立重排：自增连续、无缺口、filename 同步。"""
    kept, _ = prune_records(_prunable_records())
    renumbered = renumber_records(kept)
    assert [r["report_id"] for r in renumbered] == [
        "rep_slowmist_001", "rep_peckshield_001",
    ]
    assert renumbered[0]["filename"] == "rep_slowmist_001_2026-09-07.txt"


def test_prune_archive_readme_exemption():
    """归档 README 豁免：子目录事故索引保留，仓库根导航 README 仍剔除。"""
    records = [
        {  # 子目录事故索引（DeFiHackLabs past/2024）→ 保留
            "report_id": "rep_blocksec_001", "vendor": "BlockSec",
            "title": "README.md", "publish_date": "",
            "matched_kw": "", "url": (
                "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/"
                "main/past/2024/README.md"
            ), "filename": "rep_blocksec_001_readme-md.txt", "has_fund_flow": "",
        },
        {  # 仓库根导航 README（Knowledge-Base 首页）→ 剔除
            "report_id": "rep_slowmist_001", "vendor": "SlowMist",
            "title": "README.md", "publish_date": "",
            "matched_kw": "", "url": (
                "https://raw.githubusercontent.com/slowmist/Knowledge-Base/"
                "master/README.md"
            ), "filename": "rep_slowmist_001_readme-md.txt", "has_fund_flow": "",
        },
    ]
    kept, removed = prune_records(records)
    assert [r["report_id"] for r in kept] == ["rep_blocksec_001"]
    assert [r["report_id"] for r in removed] == ["rep_slowmist_001"]


def test_prune_pipeline_backup_prune_rewrite(tmp_path):
    """完整剪枝流水线：备份防线 → 物理剔除 → 台账重写（RFC 4180 合规）。"""
    data_dir, records = _prunable_world(tmp_path)
    backup_dir = tmp_path / "raw_reports_v1_backup"
    result = run_prune(data_dir, backup_dir, dry_run=False)

    assert result["backup"] == "backed-up"
    assert result["total"] == 5
    assert result["kept"] == 2
    assert result["removed"] == 3

    # 历史资产完整备份（文件与台账一并归档）
    assert (backup_dir / "manifest.csv").exists()
    assert len(list(backup_dir.glob("*.txt"))) == 5

    # 噪音文件已物理删除，保留文件已重命名且与台账一一对应
    assert not (data_dir / "rep_slowmist_001_2026-09-23.txt").exists()
    assert not (data_dir / "rep_certik_001_smart-contract-audit.txt").exists()
    rows = list(ManifestStore(data_dir / "manifest.csv").iter_rows())
    assert len(rows) == 2
    for row in rows:
        assert (data_dir / row["filename"]).exists()
        assert row["has_fund_flow"] == ""
    # RFC 4180：表头 + CRLF
    raw = (data_dir / "manifest.csv").read_bytes()
    assert raw.startswith(",".join(MANIFEST_HEADERS).encode("utf-8"))
    assert raw.count(b"\r\n") == 3

    # 幂等重跑：备份目录已存在不覆盖，第二次剪枝 0 剔除
    result2 = run_prune(data_dir, backup_dir, dry_run=False)
    assert result2["backup"] == "exists"
    assert result2["removed"] == 0


def test_prune_dry_run_touches_nothing(tmp_path):
    """--dry-run：零写入、零删除、零备份。"""
    data_dir, _ = _prunable_world(tmp_path)
    before_files = {p.name for p in data_dir.glob("*.txt")}
    before_manifest = (data_dir / "manifest.csv").read_bytes()
    result = run_prune(data_dir, tmp_path / "v1_backup", dry_run=True)
    assert result["dry_run"] is True
    assert result["kept"] == 2
    assert {p.name for p in data_dir.glob("*.txt")} == before_files
    assert (data_dir / "manifest.csv").read_bytes() == before_manifest
    assert not (tmp_path / "v1_backup").exists()


def test_backup_raw_reports_idempotent(tmp_path):
    """备份防线幂等：已存在备份绝不覆盖。"""
    data_dir = tmp_path / "raw_reports"
    data_dir.mkdir()
    (data_dir / "a.txt").write_text("original", encoding="utf-8")
    backup_dir = tmp_path / "v1_backup"
    assert backup_raw_reports(data_dir, backup_dir) == "backed-up"
    (data_dir / "a.txt").write_text("mutated", encoding="utf-8")
    assert backup_raw_reports(data_dir, backup_dir) == "exists"
    assert (backup_dir / "a.txt").read_text(encoding="utf-8") == "original"  # v1 原貌保留


def test_min_per_vendor_rounds_never_duplicate(tmp_path):
    """保底配额补扫：厂商未达保底时多遍扫描，manifest 幂等去重保证零重复。"""
    world = _flood_world(n=2)
    crawler = Crawler(
        fetcher=world,
        data_dir=tmp_path,
        total_quota=100,
        max_per_vendor=None,
        min_per_vendor=3,  # 每厂商只有 2 篇：触发多遍补扫
    )
    report = crawler.run()
    assert {code: stats.saved for code, stats in report.items()} == {
        "slowmist": 2, "blocksec": 2, "peckshield": 2, "certik": 2,
    }
    assert sum(s.saved for s in report.values()) == 8
    # 补扫后仍零重复落盘
    assert len(list(crawler.manifest.iter_rows())) == 8
    assert len(list(tmp_path.glob("*.txt"))) == 8
    # 每厂商数据源被多遍扫描（保底拉平尝试），但不会无限循环（封顶 3 遍）
    for vendor in VENDORS:
        assert world.discover_log.count(vendor.sources[0].url) == 3


def test_cli_accepts_min_per_vendor_flag(tmp_path):
    """CLI --min-per-vendor 参数解析与透传。"""
    assert main(
        ["--mock", "--total", "8", "--min-per-vendor", "0", "--data-dir", str(tmp_path)]
    ) == 0
    assert len(list(tmp_path.glob("*.txt"))) == 8
