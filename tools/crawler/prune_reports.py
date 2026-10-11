"""存量资产归档与精细化剪枝流水线（Surgical Pruning）。

职责（任务 A / E）：
1. 执行任何清洗或覆盖前，自动完整备份 `data/raw_reports/` 至
   `data/raw_reports_v1_backup/`，严禁直接物理抹除旧数据；
2. 读取 manifest.csv，按标题 / URL 特征执行负向黑名单硬淘汰：
   - 商业 / 审计废纸（smart-contract-audit / kyc / penetration-testing / bug-bounty…）
   - 宏观政策与社工通报（FATF / Regulatory / Compliance Guide / Phishing / Job-Seeking…）
3. 删除被淘汰记录对应的 .txt 物理文件；
4. 重排 report_id（按厂商自增连续）、重命名保留文件、重写 manifest.csv
   （RFC 4180，has_fund_flow 重置为空字符串留待专家核验）。

用法:
    python tools/crawler/prune_reports.py --dry-run          # 仅评估，不落盘
    python tools/crawler/prune_reports.py                    # 备份 + 剪枝 + 重写

本模块严格遵守架构隔离红线：不导入 src/ 下任何模块，不触碰任何
生产物理知识库文件。
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.crawler.filters import (  # noqa: E402
    is_prunable_title,
    is_prunable_url,
    is_root_readme_url,
)
from tools.crawler.manifest import ManifestStore  # noqa: E402

DEFAULT_DATA_DIR = _PROJECT_ROOT / "data" / "raw_reports"
DEFAULT_BACKUP_DIR = _PROJECT_ROOT / "data" / "raw_reports_v1_backup"

_FILENAME_SUFFIX_RE = re.compile(r"^rep_[a-z0-9]+_\d{3}_(.*)$")


def backup_raw_reports(
    data_dir: str | Path,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
) -> str:
    """完整备份现存 raw_reports 至 v1_backup（幂等：已存在则不覆盖）。"""
    source = Path(data_dir)
    target = Path(backup_dir)
    if not source.exists() or not any(source.iterdir()):
        return "empty"
    if target.exists():
        return "exists"
    shutil.copytree(source, target)
    return "backed-up"


def load_manifest_rows(data_dir: str | Path) -> list[dict[str, str]]:
    csv_path = Path(data_dir) / "manifest.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def prune_records(records: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """按黑名单硬淘汰：返回 (保留, 剔除) 两个有序列表。

    归档文件（.md 文件名标题）只做 URL 判定，避免 README 标题规则
    误伤历史事故索引（DeFiHackLabs past/202x/README.md 等）。
    """
    kept: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    for record in records:
        title = (record.get("title") or "").strip()
        url = (record.get("url") or "").strip()
        archive_title = title.lower().endswith((".md", ".markdown"))
        prunable = (
            is_prunable_url(url)
            or is_root_readme_url(url)
            or (not archive_title and is_prunable_title(title))
        )
        if prunable:
            removed.append(record)
        else:
            kept.append(record)
    return kept, removed


def _split_vendor_code(report_id: str) -> str:
    match = re.match(r"^rep_([a-z0-9]+)_\d{3}$", (report_id or "").strip())
    return match.group(1) if match else ""


def _rebuild_filename(new_report_id: str, old_filename: str) -> str:
    """重排 report_id 后同步重命名文件，保持 manifest 与磁盘一一对应。"""
    match = _FILENAME_SUFFIX_RE.match(old_filename or "")
    suffix = match.group(1) if match else (old_filename or "")
    return f"{new_report_id}_{suffix}"


def renumber_records(kept: list[dict[str, str]]) -> list[dict[str, str]]:
    """按厂商独立自增重排 report_id（从 001 连续），filename 同步重写。"""
    counters: dict[str, int] = {}
    rebuilt: list[dict[str, str]] = []
    for record in kept:
        code = _split_vendor_code(record.get("report_id") or "")
        if not code:
            rebuilt.append(dict(record))
            continue
        counters[code] = counters.get(code, 0) + 1
        new_report_id = f"rep_{code}_{counters[code]:03d}"
        new_record = dict(record)
        new_record["report_id"] = new_report_id
        new_record["filename"] = _rebuild_filename(
            new_report_id, record.get("filename") or ""
        )
        rebuilt.append(new_record)
    return rebuilt


def run_prune(
    data_dir: str | Path,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
    dry_run: bool = False,
) -> dict:
    """执行完整剪枝流水线：备份 → 淘汰 → 删文件 → 重排编号 → 重写台账。"""
    data_dir = Path(data_dir)
    rows = load_manifest_rows(data_dir)
    kept, removed = prune_records(rows)
    renumbered = renumber_records(kept)
    if dry_run:
        return {
            "backup": "skipped-dry-run",
            "total": len(rows),
            "kept": len(kept),
            "removed": len(removed),
            "removed_rows": removed,
            "renumbered": renumbered,
            "dry_run": True,
        }
    backup_status = backup_raw_reports(data_dir, backup_dir)

    manifest_path = data_dir / "manifest.csv"
    if rows:
        # 重写台账前先落盘新编号（rewrite 为全量覆盖，原子性由临时文件保证）
        store = ManifestStore(manifest_path)
        store.rewrite(renumbered)
    for record in removed:
        filename = (record.get("filename") or "").strip()
        if not filename:
            continue
        target = (data_dir / filename).resolve()
        try:
            if target.exists() and target.is_file():
                target.unlink()
        except OSError:
            pass
    # 重命名保留文件，使磁盘文件名与新 report_id 前缀一致
    for old_record, new_record in zip(kept, renumbered):
        old_name = (old_record.get("filename") or "").strip()
        new_name = (new_record.get("filename") or "").strip()
        if not old_name or not new_name or old_name == new_name:
            continue
        old_path = data_dir / old_name
        new_path = data_dir / new_name
        try:
            if old_path.exists() and not new_path.exists():
                old_path.rename(new_path)
        except OSError:
            pass
    return {
        "backup": backup_status,
        "total": len(rows),
        "kept": len(kept),
        "removed": len(removed),
        "removed_rows": removed,
        "renumbered": renumbered,
        "dry_run": False,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prune_reports.py",
        description=(
            "存量研报精细化剪枝流水线：负向黑名单硬淘汰 + 备份防线 + "
            "manifest 重写（report_id 连续、RFC 4180）"
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅评估剪枝结果并打印，不备份、不删文件、不重写台账",
    )
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_prune(args.data_dir, args.backup_dir, dry_run=args.dry_run)
    print(
        f"[PRUNE] total={result['total']} kept={result['kept']} "
        f"removed={result['removed']} backup={result['backup']} "
        f"{'(DRY RUN)' if result['dry_run'] else ''}"
    )
    for row in result["removed_rows"]:
        title = re.sub(r"\s+", " ", (row.get("title") or "")).strip()
        print(f"[PRUNE] REMOVED {row.get('report_id')}: {title[:80]}")
    if result["dry_run"]:
        print("[PRUNE] dry-run: production data untouched")
    else:
        print(f"[PRUNE] manifest rewritten: {args.data_dir / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
