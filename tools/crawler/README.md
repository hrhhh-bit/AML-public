# tools/crawler —— 独立数据采集子系统（四大厂商分层研报爬取流水线）

为跨链 AML 拓扑生成系统（Stage-1）构建的**完全物理解耦**的原始研报采集子系统，
遵循实证学术规范（PRISMA 数据漏斗），对 **SlowMist / BlockSec / PeckShield / CertiK**
四大权威安全厂商实施**总目标驱动 + 保底软上限**的均衡采集（Stratified Harvesting），
并内建**全局负向主题词硬拦截**与**存量精细化剪枝**，重构 60~80 篇高信噪比黄金研报池。

## 目录结构

| 文件                 | 职责                                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `crawl_reports.py`   | 主采集入口、总目标/保底/软上限调度器、负向主题词硬拦截漏斗、控制台健康度仪表盘                                                       |
| `prune_reports.py`   | 存量资产归档与精细化剪枝流水线（备份防线 + 负向黑名单硬淘汰 + report_id 重排 + manifest 重写）                                       |
| `filters.py`         | 全局负向主题词名单（NEGATIVE_KEYWORDS）与标题 / URL 剪枝黑名单（商业废纸、宏观政策、社工通报）                                       |
| `vendor_registry.py` | 四大厂商数据源注册表（CertiK 事故专题路径精准过滤、DeFiHackLabs / CryptoVulhub 开源事故库）、检索词与配额常量                        |
| `extractor.py`       | 高保真正文提取与降噪（`trafilatura` 优先，标准库解析器回退）、ASCII 资金流链路抽取（`analyze_fund_flow_evidence`）                   |
| `fetcher.py`         | HTTP 采集器（浏览器 UA/超时/重试/限速/gzip/响应缓存）、RSS `content:encoded` 原地正文直提、GitHub 树 API + codeload tarball 归档发现 |
| `manifest.py`        | PRISMA 元数据总账（RFC 4180 CSV，幂等增量追加、剪枝全量重写）                                                                        |

## 架构隔离红线（Hard Isolation Tenets）

- `tools/crawler/` 下代码**严禁导入** `src/` 中任何状态机、RAG 检索或 Agent 决策模块；
- 采集脚本**绝对严禁读写** `data/` 下的生产物理知识库文件；
- 采集产物**唯一输出目标**为 `data/raw_reports/`：
  - 研报文本：`data/raw_reports/{report_id}_{date_or_slug}.txt`
  - 元数据总账：`data/raw_reports/manifest.csv`
- **历史资产备份防线**：任何清洗 / 覆盖生产目录前，自动完整备份
  `data/raw_reports/` 至 `data/raw_reports_v1_backup/`（已存在则绝不覆盖）。

## 采集策略（v2 信噪比重构）

- **全局负向主题词硬拦截**：标题 / 正文命中 `NEGATIVE_KEYWORDS`
  （FATF、compliance guideline、job-seeking、recruitment phishing、
  audit report summary、kyc verification）或剪枝黑名单（商业/审计废纸、
  宏观政策、社工通报），即使命中 AML 关键词也一律直接抛弃、不落盘；
- **CertiK 路径精准过滤**：仅放行 `/resources/blog/incident-analysis/`、
  `/resources/blog/hack/`、`/resources/blog/security-incident/` 及
  `incident-analysis` 语义路径，剔除裸域名 `certik` 宽松匹配；
- **开源深度事故库激活**：`SunWeb3Sec/DeFiHackLabs`（BlockSec，
  Phalcon / BlockSec / Fund Flow / Money Tracing / Tornado / Cross-chain
  标签）与 `Rivaill/CryptoVulhub`（PeckShield）经 GitHub 树 API /
  codeload tarball 归档发现，正文原地直提、零二次请求；
- **feed 标题事件词硬过滤**：CertiK Medium 源仅放行 incident / hack /
  exploit / attack 标题，剔除产品与政策文；
- **分层配额**：总目标 60~80 篇（默认 80），单厂商保底 15、软上限 20
  （跨轮累计防垄断）。

## 反爬策略（Anti-bot Strategy）

- **RSS 原地正文直提**：Medium 官方 RSS 的 `<content:encoded>` 已携带整篇正文 HTML，解析后直接本地清洗落盘，**绝不二次访问文章网页**（彻底绕开 Cloudflare 403）；
- **GitHub blob → raw 转换**：`github.com/{owner}/{repo}/blob/{branch}/{path}` 自动改写为 `raw.githubusercontent.com/...` 纯文本 CDN 直读，无网页反爬；
- **codeload tarball 整仓归档**：GitHub 树 API 限流时回退 tarball 下载，本地解析 Markdown 归档并原地直提正文；
- **浏览器级 User-Agent**：所有请求标配现代 Chrome UA 与合理 Accept 头，不使用 Python 默认 urllib UA。

## 快速开始

```powershell
# 离线自检：内置 Mock 源 + 临时目录落盘，生产数据零写入（验收标准）
python tools/crawler/crawl_reports.py --dry-run

# 离线跑通全流程并落盘（不发起网络请求）
python tools/crawler/crawl_reports.py --mock

# 真实网络采集（默认全局 80 篇，保底 15 / 软上限 20，先自动备份）
python tools/crawler/crawl_reports.py

# 自定义配额与时间窗（--min-per-vendor 0 关闭保底；归档长文可放宽 --max-chars）
python tools/crawler/crawl_reports.py --total 80 --min-per-vendor 15 --max-per-vendor 20 --max-chars 200000

# 存量精细化剪枝（备份 → 黑名单硬淘汰 → report_id 重排 → manifest 重写）
python tools/crawler/prune_reports.py --dry-run   # 先评估
python tools/crawler/prune_reports.py             # 正式执行
```

可选依赖（安装后启用 trafilatura 高保真提取引擎）：

```powershell
pip install -e ".[crawler]"
```

## Manifest Schema（RFC 4180，UTF-8，CRLF）

`report_id, vendor, title, publish_date, matched_kw, url, filename, has_fund_flow`

- `report_id`：`rep_{vendor_code}_{index:03d}`（按厂商独立自增，剪枝后自动重排连续）；
- `publish_date`：`YYYY-MM-DD`，未知留空；
- `has_fund_flow`：人工审核标记列，恒定为空串，留待人类专家定标；
- 同一 URL 幂等去重；归档文件名（.md）标题豁免标题去重（仅按 URL 去重）。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_crawler.py -v
```

全部用例离线运行（`unittest.mock` + 内存 Mock 源），不发真实外网请求。
