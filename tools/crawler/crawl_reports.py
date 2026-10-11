"""四大厂商分层研报爬取流水线 —— 主采集入口与调度器。

用法:
    python tools/crawler/crawl_reports.py --dry-run          # 离线自检（内置 Mock 源 + 临时目录）
    python tools/crawler/crawl_reports.py --mock             # 离线跑通全流程并落盘
    python tools/crawler/crawl_reports.py                    # 真实网络采集（总目标 + 时间窗口为主停止条件）
    python tools/crawler/crawl_reports.py --total 80 --max-per-vendor 40 --since 2021-01-01

架构隔离红线:
    * 本文件及 tools/crawler/ 下所有模块严禁 import src/ 任何模块；
    * 采集流程严禁读写 data/ 下的任何生产物理知识库文件；
    * 采集产物仅落盘 data/raw_reports/（研报文本 + manifest.csv）。
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 支持 `python tools/crawler/crawl_reports.py` 直接执行，
# 同时兼容作为包导入（pytest / python -m tools.crawler.crawl_reports）。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.crawler.extractor import (  # noqa: E402
    MAX_CHARS,
    MIN_CHARS,
    extract_main_text,
    extract_publish_date,
    extract_title,
    match_keywords,
    normalize_iso_date,
    passes_length_filter,
    slugify,
    slugify_from_url,
)
from tools.crawler.fetcher import (  # noqa: E402
    BaseFetcher,
    HttpFetcher,
    build_mock_world,
)
from tools.crawler.filters import (  # noqa: E402
    NEGATIVE_KEYWORDS,
    is_negative_text,
    is_negative_title,
    is_prunable_title,
    is_prunable_url,
    is_root_readme_url,
)
from tools.crawler.manifest import ManifestStore  # noqa: E402
from tools.crawler.vendor_registry import (  # noqa: E402
    DEFAULT_MAX_PER_VENDOR,
    DEFAULT_MIN_PER_VENDOR,
    DEFAULT_TOTAL_QUOTA,
    RECOMMENDED_TOTAL_RANGE,
    VENDORS,
)

# 采集产物唯一目标目录（研报文本与 manifest.csv 均落于此）
DEFAULT_DATA_DIR = _PROJECT_ROOT / "data" / "raw_reports"

# 检索时间窗口下限（publish_date 早于此日期即跳过；未知日期放行）
DEFAULT_SINCE = "2021-01-01"


# ---------------------------------------------------------------------------
# 统计与仪表盘
# ---------------------------------------------------------------------------
@dataclass
class VendorStats:
    vendor: str
    code: str = ""  # 厂商代码（slowmist / blocksec / peckshield / certik）
    cap: int | None = None  # 防垄断软上限（None = 不限）
    discovered: int = 0
    fetched: int = 0
    inline: int = 0  # RSS 原地正文直提条数（未发起二次 HTTP 请求）
    saved: int = 0
    skipped_duplicate: int = 0
    skipped_length: int = 0
    skipped_no_match: int = 0
    skipped_before_since: int = 0
    skipped_negative: int = 0  # 全局负向主题词硬拦截（标题 / 正文）
    errors: int = 0
    char_total: int = 0


def format_telemetry(report: dict[str, VendorStats], total_quota: int) -> str:
    """结构化健康度汇总表：展示各厂商真实自然分布（share%）。"""
    lines = [
        "=" * 94,
        "PRISMA STRATIFIED HARVEST TELEMETRY  (total-driven, anti-monopoly soft cap)",
        "=" * 94,
    ]
    header = (
        f"{'vendor':<11}{'cap':>5}{'saved':>7}{'share%':>8}{'avg_chars':>11}"
        f"{'dup':>6}{'len':>6}{'kw':>6}{'inline':>8}{'since':>7}"
        f"{'neg':>6}{'errors':>8}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    total_saved = sum(stats.saved for stats in report.values())
    total_errors = 0
    for stats in report.values():
        cap = str(stats.cap) if stats.cap else "-"
        share = f"{stats.saved / total_saved * 100:.0f}%" if total_saved else "-"
        avg = stats.char_total // stats.saved if stats.saved else 0
        lines.append(
            f"{stats.vendor:<11}{cap:>5}{stats.saved:>7}{share:>8}{avg:>11}"
            f"{stats.skipped_duplicate:>6}{stats.skipped_length:>6}"
            f"{stats.skipped_no_match:>6}{stats.inline:>8}{stats.skipped_before_since:>7}"
            f"{stats.skipped_negative:>6}{stats.errors:>8}"
        )
        total_errors += stats.errors
    lines.append("-" * len(header))
    lines.append(f"TOTAL: saved={total_saved}/{total_quota}  errors={total_errors}")
    return "\n".join(lines)


def print_telemetry(report: dict[str, VendorStats], total_quota: int) -> None:
    print(format_telemetry(report, total_quota))


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
class Crawler:
    """总目标驱动调度器。

    主停止条件：全局总篇数 --total 达成，或时间窗口内所有厂商的合格报告采尽；
    辅助约束：--max-per-vendor 防垄断软上限（单厂商采入篇数封顶，None = 不限）。
    单遍扫描四大厂商，有多少采多少，不回头补数。
    """

    def __init__(
        self,
        *,
        fetcher: BaseFetcher,
        data_dir: str | Path,
        total_quota: int = DEFAULT_TOTAL_QUOTA,
        max_per_vendor: int | None = None,
        min_per_vendor: int | None = None,
        min_chars: int = MIN_CHARS,
        max_chars: int = MAX_CHARS,
        require_keyword: bool = False,
        since: str | None = None,
        write_files: bool = True,
        logger=None,
        enable_negative_filter: bool = True,
    ) -> None:
        self.fetcher = fetcher
        self.data_dir = Path(data_dir)
        self.total_quota = max(1, int(total_quota))
        self.max_per_vendor = (
            None if max_per_vendor is None else max(1, int(max_per_vendor))
        )
        self.min_per_vendor = (
            None if min_per_vendor is None else max(1, int(min_per_vendor))
        )
        self.min_chars = int(min_chars)
        self.max_chars = int(max_chars)
        self.require_keyword = bool(require_keyword)
        self.since = normalize_iso_date(since) if since else ""
        self.write_files = bool(write_files)
        self.logger = logger
        # 全局负向主题词硬拦截（任务 B）：默认启用，可显式关闭
        self.negative_keywords = (
            tuple(NEGATIVE_KEYWORDS) if enable_negative_filter else ()
        )
        self._total_saved = 0
        if self.write_files:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = ManifestStore(self.data_dir / "manifest.csv")
        # 运行期存量基线快照：防垄断软上限跨轮累计的基准（台账实时值会
        # 将本轮采入重复计入，故必须在 run 前冻结）
        self._baseline_counts: dict[str, int] = {
            code: self.manifest.vendor_count(code) for code in (v.code for v in VENDORS)
        }

    # -- 主流程 ----------------------------------------------------------
    def _vendor_full(self, stats: VendorStats) -> bool:
        """厂商软上限达成：运行期存量基线 + 本轮采入封顶，跨轮累计防垄断。"""
        if self.max_per_vendor is None:
            return False
        baseline = self._baseline_counts.get(stats.code, 0)
        return stats.saved + baseline >= self.max_per_vendor

    def _total_reached(self) -> bool:
        return self._total_saved >= self.total_quota

    def _max_rounds(self) -> int:
        """保底配额开启时最多补扫 2 遍（每厂商保底 15~20 篇的软性拉平）。"""
        return 3 if self.min_per_vendor else 1

    def run(self) -> dict[str, VendorStats]:
        report: dict[str, VendorStats] = {
            vendor.code: VendorStats(vendor=vendor.name, code=vendor.code, cap=self.max_per_vendor)
            for vendor in VENDORS
        }
        self._total_saved = 0
        for round_no in range(self._max_rounds()):
            for vendor in VENDORS:
                stats = report[vendor.code]
                if self._total_reached():
                    self.report = report
                    return report  # 总目标达成：立即停止，后续厂商零抓取
                if round_no == 0 or stats.saved < self.min_per_vendor:
                    self._crawl_vendor(vendor, stats)
            # 无保底，或所有厂商均已达标：结束
            if (
                self.min_per_vendor is None
                or all(stats.saved >= self.min_per_vendor for stats in report.values())
            ):
                break
        self.report = report
        return report

    def _crawl_vendor(self, vendor, stats: VendorStats) -> int:
        for source in vendor.sources:
            if self._vendor_full(stats) or self._total_reached():
                break  # 厂商软上限达成 / 总目标达成：不再检索后续数据源
            try:
                items = self.fetcher.discover(source, vendor=vendor)
            except Exception as exc:
                stats.errors += 1
                self._log(f"[{vendor.name}] discover failed {source.url}: {exc}")
                continue
            stats.discovered += len(items)
            for item in items:
                if self._vendor_full(stats):
                    break  # 厂商软上限达成：自然切换至下一厂商
                if self._total_reached():
                    return stats.saved  # 总目标达成：优雅退出
                # 全局负向主题词硬拦截（任务 B）：标题 / URL 显著落入负向区间
                # （NEGATIVE_KEYWORDS ∪ 存量剪枝黑名单），即使命中 AML 关键词
                # 也一律直接抛弃，不落盘、不发二次请求。
                # 归档文件（.md 文件名标题）只做 URL 判定，避免 README 标题
                # 规则误伤历史事故索引（DeFiHackLabs past/202x/README.md 等）。
                archive_title = (item.title or "").lower().endswith(
                    (".md", ".markdown")
                )
                if self.negative_keywords and (
                    is_negative_title(item.title, self.negative_keywords)
                    or is_prunable_url(item.url)
                    or is_root_readme_url(item.url)
                    or (not archive_title and is_prunable_title(item.title or ""))
                ):
                    stats.skipped_negative += 1
                    continue
                # 标题事件词硬过滤（title_keywords）：feed 源信噪比收紧
                if source.title_keywords and not any(
                    keyword.lower() in (item.title or "").lower()
                    for keyword in source.title_keywords
                ):
                    stats.skipped_no_match += 1
                    continue
                if self.manifest.has_url(item.url):
                    stats.skipped_duplicate += 1
                    continue
                # 标题去重仅对非归档文件名生效（DeFiHackLabs 归档多篇同名
                # README.md，只按 URL 去重，避免误伤历史事故索引）
                if (
                    item.title
                    and not item.title.lower().endswith((".md", ".markdown"))
                    and self.manifest.has_title(item.title)
                ):
                    stats.skipped_duplicate += 1
                    continue
                if item.content_html:
                    # RSS 原地正文（content:encoded / description）：直接清洗落盘，
                    # 严禁再对该条目的 URL 发起任何二次 HTTP 请求（Medium 网页 403 反爬）。
                    raw_html = item.content_html
                    stats.inline += 1
                else:
                    try:
                        raw_html = self.fetcher.fetch(item.url)
                    except Exception as exc:
                        stats.errors += 1
                        self._log(f"[{vendor.name}] fetch failed {item.url}: {exc}")
                        continue
                    stats.fetched += 1

                text = extract_main_text(raw_html, item.url)
                # 正文负向硬拦截（任务 B）：正文关键词落入负向区间一律抛弃
                if self.negative_keywords and is_negative_text(
                    text, self.negative_keywords
                ):
                    stats.skipped_negative += 1
                    continue
                if not passes_length_filter(text, self.min_chars, self.max_chars):
                    stats.skipped_length += 1
                    continue

                title = re.sub(r"\s+", " ", (item.title or "").strip())
                if not title:
                    title = extract_title(raw_html) or slugify_from_url(item.url)
                publish_date = normalize_iso_date(item.publish_date)
                if not publish_date:
                    publish_date = extract_publish_date(raw_html, item.url)

                # 时间窗口过滤：早于 --since 的旧报告跳过；日期未知则放行（manifest 留空标注）
                if self.since and publish_date and publish_date < self.since:
                    stats.skipped_before_since += 1
                    continue

                matched = match_keywords(f"{title}\n{text}", vendor.keywords)
                if self.require_keyword and not matched:
                    stats.skipped_no_match += 1
                    continue

                report_id = self.manifest.next_report_id(vendor.code)
                filename = f"{report_id}_{publish_date or slugify(title)}.txt"
                record = {
                    "report_id": report_id,
                    "vendor": vendor.name,
                    "title": title,
                    "publish_date": publish_date,
                    "matched_kw": ", ".join(matched),
                    "url": item.url,
                    "filename": filename,
                    "has_fund_flow": "",
                }
                if not self.manifest.add(record):
                    stats.skipped_duplicate += 1
                    continue
                if self.write_files:
                    (self.data_dir / filename).write_text(text, encoding="utf-8")
                stats.char_total += len(text)
                stats.saved += 1
                self._total_saved += 1
        return stats.saved

    # -- 工具 ------------------------------------------------------------
    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger(message)
        else:
            print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _since_date_arg(value: str) -> str:
    """--since 参数校验：必须是合法 YYYY-MM-DD。"""
    normalized = normalize_iso_date(value)
    if not normalized:
        raise argparse.ArgumentTypeError(
            f"invalid date: {value!r} (expected YYYY-MM-DD)"
        )
    return normalized


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawl_reports.py",
        description=(
            "四大安全厂商（SlowMist / BlockSec / PeckShield / CertiK）"
            "总目标驱动的均衡研报采集流水线（PRISMA 数据漏斗）"
        ),
    )
    parser.add_argument(
        "--max-per-vendor",
        type=int,
        default=DEFAULT_MAX_PER_VENDOR,
        help=(
            "防垄断软上限：单厂商最多采入篇数，防止单一信源占满样本池"
            f"（默认 {DEFAULT_MAX_PER_VENDOR}，传 0 表示不设上限）"
        ),
    )
    parser.add_argument(
        "--min-per-vendor",
        type=int,
        default=DEFAULT_MIN_PER_VENDOR,
        help=(
            "单厂商保底篇数：各厂商未达标时最多补扫 2 遍"
            f"（默认 {DEFAULT_MIN_PER_VENDOR}，传 0 表示关闭保底）"
        ),
    )
    parser.add_argument(
        "--total",
        type=int,
        default=DEFAULT_TOTAL_QUOTA,
        help=(
            "全局目标篇数（主停止条件，建议 "
            f"{RECOMMENDED_TOTAL_RANGE[0]}~{RECOMMENDED_TOTAL_RANGE[1]}）"
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=f"输出目录（默认 {DEFAULT_DATA_DIR}）",
    )
    parser.add_argument("--min-chars", type=int, default=MIN_CHARS, help="正文最小字符数")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS, help="正文最大字符数")
    parser.add_argument(
        "--require-keyword",
        action="store_true",
        help="启用后丢弃未命中厂商关键词的页面",
    )
    parser.add_argument(
        "--since",
        type=_since_date_arg,
        default=DEFAULT_SINCE,
        metavar="YYYY-MM-DD",
        help=f"检索时间窗口下限：publish_date 早于此日期即跳过（默认 {DEFAULT_SINCE}，未知日期放行）",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="离线模式：使用内置 Mock 源，不发起任何网络请求",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑自检：离线 Mock 源 + 临时目录落盘，生产数据目录零写入",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="请求间速率限制间隔（秒）")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 超时（秒）")
    parser.add_argument("--retries", type=int, default=2, help="HTTP 重试次数")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.total < 1:
        print("[ERROR] --total must be >= 1", file=sys.stderr)
        return 2

    data_dir = args.data_dir or DEFAULT_DATA_DIR
    if args.dry_run:
        args.mock = True
        args.total = 12          # Mock 世界共 12 篇（4 厂商 × 3 篇）：演示软上限 + 总目标达成
        args.max_per_vendor = 3
        args.min_per_vendor = 0  # 干跑自检关闭保底补扫（单遍语义）
        data_dir = Path(tempfile.mkdtemp(prefix="aml_crawler_dryrun_"))
        print("[DRY RUN] offline mock sources; forced total=12, max-per-vendor=3")
        print(f"[DRY RUN] staged output directory: {data_dir} (production data untouched)")
    else:
        if not (RECOMMENDED_TOTAL_RANGE[0] <= args.total <= RECOMMENDED_TOTAL_RANGE[1]):
            print(
                f"[NOTE] total quota {args.total} outside recommended band "
                f"{RECOMMENDED_TOTAL_RANGE}",
                file=sys.stderr,
            )
    max_per_vendor = None if args.max_per_vendor <= 0 else args.max_per_vendor
    min_per_vendor = None if args.min_per_vendor <= 0 else args.min_per_vendor

    # 历史资产备份防线（Hard Tenet）：采集 / 清洗写入生产目录前，
    # 必须先完整备份现存 data/raw_reports/ 至 data/raw_reports_v1_backup/。
    if data_dir == DEFAULT_DATA_DIR:
        from tools.crawler.prune_reports import backup_raw_reports

        backup_raw_reports(data_dir, _PROJECT_ROOT / "data" / "raw_reports_v1_backup")

    if args.mock:
        mock_size = max(args.total, max_per_vendor or 0, 3)
        fetcher = build_mock_world(per_vendor=mock_size)
        print("[MOCK] in-memory mock sources active (no network requests)")
    else:
        fetcher = HttpFetcher(timeout=args.timeout, retries=args.retries, delay=args.delay)

    print(
        f"[WINDOW] retrieval time window: since {args.since} "
        "(older publish_date skipped; unknown dates allowed)"
    )

    crawler = Crawler(
        fetcher=fetcher,
        data_dir=data_dir,
        total_quota=args.total,
        max_per_vendor=max_per_vendor,
        min_per_vendor=min_per_vendor,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        require_keyword=args.require_keyword,
        since=args.since,
        write_files=True,
    )
    try:
        report = crawler.run()
    except Exception as exc:  # 防御性兜底：任何异常均以非零码退出
        print(f"[FATAL] crawl aborted: {exc}", file=sys.stderr)
        return 1

    print_telemetry(report, args.total)
    manifest_path = crawler.manifest.csv_path
    if manifest_path.exists():
        print(f"Manifest: {manifest_path} ({len(crawler.manifest)} record(s))")
    else:
        print(f"Manifest: {manifest_path} (no reports saved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
