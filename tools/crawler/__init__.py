"""跨链 AML 研报采集子系统（四大厂商分层配额爬取流水线）。

物理隔离红线：
    * 严禁 import src/ 任何模块（状态机 / RAG / Agent 决策模块）；
    * 严禁读写 data/ 下的生产物理知识库文件；
    * 采集产物仅落盘 data/raw_reports/（研报文本 + manifest.csv）。
"""

from tools.crawler.crawl_reports import Crawler, VendorStats, print_telemetry
from tools.crawler.extractor import extract_main_text
from tools.crawler.manifest import MANIFEST_HEADERS, ManifestStore
from tools.crawler.vendor_registry import VENDORS, get_vendor

__all__ = [
    "Crawler",
    "VendorStats",
    "print_telemetry",
    "extract_main_text",
    "MANIFEST_HEADERS",
    "ManifestStore",
    "VENDORS",
    "get_vendor",
]
