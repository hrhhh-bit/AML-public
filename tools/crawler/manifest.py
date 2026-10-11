"""PRISMA 元数据总账（RFC 4180 CSV）读写封装。

Schema（列序固定）:
    report_id, vendor, title, publish_date, matched_kw, url, filename, has_fund_flow

写入规范:
    * UTF-8 编码、CRLF 行结束符、QUOTE_MINIMAL 引号规则（RFC 4180）；
    * 纯追加（append）语义 + 按 URL / 标题去重，天然支持幂等重跑；
    * report_id 按厂商独立自增（rep_{vendor_code}_{index:03d}），
      重载历史台账时自动续号，保证增量抓取编号连续不冲突。

本模块严格遵守架构隔离红线：不导入 src/ 下任何模块。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterator

MANIFEST_HEADERS: tuple[str, ...] = (
    "report_id",
    "vendor",
    "title",
    "publish_date",
    "matched_kw",
    "url",
    "filename",
    "has_fund_flow",
)

_REPORT_ID_RE = re.compile(r"^rep_([a-z0-9]+)_(\d{3})$")


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "")).strip().lower()


class ManifestStore:
    """幂等增量 CSV 台账。"""

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        self._by_url: dict[str, dict[str, str]] = {}
        self._titles: set[str] = set()
        self._next_index: dict[str, int] = {}
        self._load()

    # -- 内部 ------------------------------------------------------------
    def _load(self) -> None:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            return
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                url = (row.get("url") or "").strip()
                title = _norm_title(row.get("title") or "")
                if url:
                    self._by_url[url] = row
                if title:
                    self._titles.add(title)
                match = _REPORT_ID_RE.match((row.get("report_id") or "").strip())
                if match:
                    code = match.group(1)
                    nxt = int(match.group(2)) + 1
                    self._next_index[code] = max(self._next_index.get(code, 1), nxt)

    # -- 查询 ------------------------------------------------------------
    def has_url(self, url: str) -> bool:
        return bool(url) and url.strip() in self._by_url

    def has_title(self, title: str) -> bool:
        normalized = _norm_title(title)
        return bool(normalized) and normalized in self._titles

    def next_report_id(self, vendor_code: str) -> str:
        index = self._next_index.get(vendor_code, 1)
        return f"rep_{vendor_code}_{index:03d}"

    def vendor_count(self, vendor_code: str) -> int:
        """该厂商在台账中的现存篇数（编号连续时 next_index - 1 即精确值）。"""
        return max(0, self._next_index.get(vendor_code, 1) - 1)

    def __len__(self) -> int:
        return len(self._by_url)

    def iter_rows(self) -> Iterator[dict[str, str]]:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            return
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                yield dict(row)

    # -- 写入 ------------------------------------------------------------
    def add(self, record: dict[str, Any]) -> bool:
        """追加一条记录；URL 重复时拒绝并返回 False（幂等去重）。

        标题去重对归档文件名（.md / .markdown 结尾）豁免：DeFiHackLabs /
        CryptoVulhub 等多篇归档共享 "README.md" 文件名，只按 URL 去重。
        """
        url = str(record.get("url") or "").strip()
        title = re.sub(r"[\r\n]+", " ", str(record.get("title") or "")).strip()
        archive_title = title.lower().endswith((".md", ".markdown"))
        if self.has_url(url) or (
            title and not archive_title and self.has_title(title)
        ):
            return False
        row = {header: str(record.get(header) or "") for header in MANIFEST_HEADERS}
        row["url"] = url
        row["title"] = title
        row["has_fund_flow"] = ""  # 人工审核列恒定留空，等待后续专家定标
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(MANIFEST_HEADERS),
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\r\n",
            )
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        self._by_url[url] = row
        if _norm_title(title):
            self._titles.add(_norm_title(title))
        match = _REPORT_ID_RE.match(row["report_id"])
        if match:
            self._next_index[match.group(1)] = max(
                self._next_index.get(match.group(1), 1),
                int(match.group(2)) + 1,
            )
        return True

    # -- 全量重写（精细化剪枝专用）--------------------------------------
    def rewrite(self, records: list[dict[str, Any]]) -> None:
        """整体重写 CSV 台账：剪枝后按传入顺序落盘，索引重建。

        - report_id 自增连续性由调用方保证（按厂商从 001 重排）；
        - has_fund_flow 恒定重置为空字符串，留待专家最终核验；
        - RFC 4180：UTF-8、CRLF、QUOTE_MINIMAL。
        """
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._by_url.clear()
        self._titles.clear()
        self._next_index.clear()
        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(MANIFEST_HEADERS),
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\r\n",
            )
            writer.writeheader()
            for record in records:
                row = {header: str(record.get(header) or "") for header in MANIFEST_HEADERS}
                row["title"] = re.sub(
                    r"[\r\n]+", " ", str(record.get("title") or "")
                ).strip()
                row["has_fund_flow"] = ""  # 人工审核列恒定留空
                writer.writerow(row)
                url = row["url"]
                title = _norm_title(row["title"])
                if url:
                    self._by_url[url] = row
                if title:
                    self._titles.add(title)
                match = _REPORT_ID_RE.match(row["report_id"])
                if match:
                    code = match.group(1)
                    nxt = int(match.group(2)) + 1
                    self._next_index[code] = max(
                        self._next_index.get(code, 1), nxt
                    )
