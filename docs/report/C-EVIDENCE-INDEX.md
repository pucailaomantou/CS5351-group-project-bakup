# C 交付证据索引

本索引以已合入 main 的实验证据包 `docs/evidence/cost01-2026-11-19/` 为权威依据，全部使用
仓库相对路径。核心代码经 **PR #7** 合入 main；实验证据经 **PR #8** 合入 main
（merge commit `b88ac95`）。

## 成本与样本（main 内证据包）

- [实验证据说明](../evidence/cost01-2026-11-19/README.md) — 协议、样本选择、统计、复算方法与限制
- [修订统计](../evidence/cost01-2026-11-19/review/summary_revised.json) — Before/After 的 n/sum/mean/median/min/max
- [二十四条样本选择清单](../evidence/cost01-2026-11-19/review/SAMPLE-LIST-REVISED.csv)
- [行情逐样本证据](../evidence/cost01-2026-11-19/review/MARKET-EVIDENCE.csv)
- [修订审核说明](../evidence/cost01-2026-11-19/review/CANDIDATE-REVIEW-REVISED.md)
- [记录定位与逐记录 SHA](../evidence/cost01-2026-11-19/index/record-locations.json)
- 原始运行记录：`docs/evidence/cost01-2026-11-19/records/before/`（12 条：10 纳入 + 2 排除）
  与 `docs/evidence/cost01-2026-11-19/records/after/`（12 条：10 有效 + 2 失败）。
- [证据包校验清单](../evidence/cost01-2026-11-19/SHA256SUMS.txt)

十 Before 与十 After 分别支撑 160315.8 / 159615 与 147754.2 / 148087；两条 Before 排除与两条
After 失败保留定位，未覆盖原始 `valid` 字段。选择来自 SAMPLE-LIST-REVISED.csv，不按 token 高低。

## 补样与协议（main 内证据包）

- [补样执行与限制说明](../evidence/cost01-2026-11-19/supplement/SUPPLEMENT-README.md)
- [补样行情证据清单](../evidence/cost01-2026-11-19/supplement/market_evidence/) — 两条 Before 补样的请求/响应 manifest 与原文
- [共同七天 ticker 新闻窗口适配器](../evidence/cost01-2026-11-19/protocol/d4_news_window_adapter.py)（归档，未接入应用、非生产默认）
- [原批次实验驱动](../evidence/cost01-2026-11-19/protocol/d4_run.py)
- [补样驱动](../evidence/cost01-2026-11-19/protocol/d4_before_supplement_run.py)
- [行情旁路留证](../evidence/cost01-2026-11-19/protocol/d4_market_evidence.py)

## 实现与离线验证（main 代码）

代码入口为 main 上的实际路径与行号（核对于 `b88ac95`）：

- [8/8/3 配置](../../src/tradingagents/default_config.py#L137)
- [逐调用与逐 agent 计量](../../src/cli/stats_handler.py#L90)
- [辩论终止状态声明](../../src/tradingagents/agents/state.py#L28)
- [终止状态初始化](../../src/tradingagents/graph/propagation.py#L50)
- [Bear 终止判定](../../src/tradingagents/agents/researchers/bear_researcher.py#L131)
- [RM 组装辩论记录](../../src/tradingagents/agents/managers/research_manager.py#L265)
- [ticker 新闻搜索补充（fetch-pool / search supplement）](../../src/tradingagents/dataflows/vendors/yahoo/news.py#L149)
- C 核心集成 PR：<https://github.com/Lukelalalalll/cs5351-group-project/pull/7>（已合入）
- C 实验证据 PR：<https://github.com/Lukelalalalll/cs5351-group-project/pull/8>（已合入）
- 旧 11-18 基线 PR：<https://github.com/Lukelalalalll/cs5351-group-project/pull/6>（历史基线，不可与本组 11-19 混算）

离线验证为**本地** `pytest test/offline`（1462 passed、1 skipped、0 failed；跳过项为可选
`langchain_aws`）。对应集成版本为 `b3157c8`。

## 基准登记与对照测量

- 截至 2026-11-23 核对的 main `0f0a2ee`，`requirements.yaml` 登记 COST-01 active baseline 为 NVDA / 2026-11-19，mean 160315.8、median 159615。
- 本次 NVDA / 2026-11-19 对照使用同协议下的十个 Before，mean 160315.8、median 159615。
- [基线迁移 PR #11](https://github.com/Lukelalalalll/cs5351-group-project/pull/11) 已合并，合并版本为 `0f0a2eeb7d7bb3b6df04be6e5f929e7a533de141`；行情完整性判据按请求范围核验行数。
- 2026-11-18 与 2026-09-01 基线均保留为 superseded 历史。

## 完整辩论证据与交叉评审

- [十个 After 的完整辩论提取件](../evidence/c-debate-2026-11-19/README.md)
- [卡片和引用逐样本验证](../evidence/c-debate-2026-11-19/validation-summary.json)
- [提取来源与 SHA](../evidence/c-debate-2026-11-19/source-index.json)
- [C 对 B 架构与需求材料评审](../review/C-PEER-REVIEW-B.md)
- [C 对 B 转录交叉批注](../review/C-CROSS-ANNOTATIONS-B.md)
- [评审版本及复算依据](../review/C-REVIEW-SOURCE-INDEX.json)

辩论提取件保留完整卡片和 RM 裁决正文，并与成本包中的同十个 After 对应。交叉评审日期为 2026-11-21。

## 个人转录

- [个人转录（精简版）](../../transcripts/60671980-LI Runyao.md) — LI Runyao / 60671980，十条个人批注、原始指令节选与 agent 回应节选。
- [消息定位索引](../../transcripts/evidence-index.json) — 批注到原始消息的定位、session/message ID 与 SHA256。
- [来源清单](../../transcripts/source-inventory.json) — 会话来源与是否纳入说明。
- [转录校验清单（仓库内交付文件）](../../transcripts/SHA256SUMS.txt)
- [归档校验清单（仓库外原件）](../../transcripts/SHA256SUMS.archive.txt) — 记录仓库外 `full/`、`sources/` 原件的 SHA256。

完整原始会话（五份 `full/` 转写与五份 `sources/` 原始 JSON）**不在本仓库**，保存在仓库外归档
`/Users/administrator/CityU/CS5351/c-transcript-archive-20261123/`；仓库内不放置其相对链接，以免形成失效入口。

## 证据覆盖范围

辩论文件提供 full-state 中的卡片、轨迹和 RM 裁决字段；整份 full-state 保存在本地。
历史相关性复算索引列出逐样本 input/total 和原始记录 SHA，旧 11-18 原始记录仍保存在本地。
