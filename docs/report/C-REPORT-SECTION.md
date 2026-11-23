# C 板块报告章节

本章记录 C 的成本控制、token 计量与结构化研究辩论实现，以及 NVDA / 2026-11-19 的实时对照。
补样修订后，Before 与 After 各纳入十个样本；After 的 total token 均值与中位数分别低 7.84%
和 7.22%。本次对照使用同协议下的 11-19 Before（mean 160315.8、median 159615）。
[PR #11](https://github.com/Lukelalalalll/cs5351-group-project/pull/11) 已合并，合并版本为
`0f0a2eeb7d7bb3b6df04be6e5f929e7a533de141`。截至 2026-11-23，main 的 `requirements.yaml`
已将上述 11-19 Before 登记为 COST-01 active baseline；11-18 与 09-01 基线保留为
superseded 历史。本次降幅以 11-19 基线计算。

## 实现与范围

C 将 `max_tool_rounds`、`news_article_limit`、`global_news_queries` 由 20/20/5 调整为
**8/8/3**（`src/tradingagents/default_config.py`），并提供逐调用、逐 agent 及全局 token
计量（`src/cli/stats_handler.py`）。usage 缺失与真实零消耗分别表达：`usage_complete` 为布尔值
（等价于 `usage_state == "complete"`），另以 `usage_state` 取 `complete / partial / unavailable /
no_calls` 之一描述全局 token 总量的完整程度，避免把未知消耗当作降本。

研究辩论限定在 Bull、Bear 与 Research Manager：**生成阶段**用 Idea Cards 保存
claim、evidence、stance、uncertainty 与 Osborn 规则；**裁决阶段**由 Research Manager 引用已有
卡片作出推荐。状态与日志记录 `termination_reason`（`converged` / `max_rounds`）与
`convergence_rounds`（未真实收敛时为 null），以及结构化 `debate_record`
（声明 `src/tradingagents/agents/state.py`，初始化 `src/tradingagents/graph/propagation.py`，
Bear 判定 `.../researchers/bear_researcher.py`，RM 组装 `.../managers/research_manager.py`）。
成本证据包中运行 JSON 的 `debate` 字段是摘要，不含完整卡片正文。
[完整辩论证据](../evidence/c-debate-2026-11-19/README.md) 从同十个有效 After 的
本地 full-state 提取原卡片、轮次轨迹及 RM 裁决原文，附逐样本验证和来源 SHA；整份 full-state 未提交。

后续局部优化包括：Bear 消除已存在于 history 的重复对手发言；Research Manager 在同次结构化
响应解析失败时，仅复用**满足输出契约**的原文；不完整或无效的裁决不得当作成功，否则走既定的
回退或失败路径。本次测量评估这些改动的组合效果，未进行单项消融。上下文压缩为 **Proposed** 架构方案。

## 实验协议

处理新闻输入可得性问题后，新对照固定 **NVDA / 2026-11-19**（盘中口径）：Before 与 After
共用一套独立的**七天 ticker 新闻窗口适配器**，实际窗口为 **2026-11-12 至 2026-11-19**，发生
调整时在工具返回中向模型说明实际窗口。该适配器只作用于 ticker 新闻；global 新闻与行情等
仍走常规实时路径，未被固定。

- Before：upstream `9fa1196`，**20/20/5**。
- After：C 的 **8/8/3** 版本（16 项冻结文件 SHA 与集成的测量版本一致）。
- 两侧：课程 `CS5351/DeepSeek-V4-Flash`、`temperature 0.0`、analysts `market+news`、
  research/risk rounds `1/1`；实时 Yahoo，未启用 fixed-news 数据集或新闻 Replay。

## 样本选择与结果

原始 Before 十条中，两条 **141 行**记录缺少独立行情请求证据；按 E 的审核意见保留原件、从正式
选择清单排除，并补跑两条带实际工具请求与原始响应证据的 Before。最终 Before = 原八条 + 两条补样。
After 共 12 次尝试，纳入 10 条有效，另 2 条分别因行情超时与新闻 SSL 失败**保留单列**。
选择依据是有效性与证据要求，**没有按 token 高低筛选**。

| 指标 | Before 十样本 | After 十样本 |
|---|---:|---:|
| total token 均值 | 160315.8 | 147754.2 |
| total token 中位数 | 159615 | 148087 |
| total token 合计 | 1603158 | 1477542 |
| total token 最小值 | 145545 | 132330 |
| total token 最大值 | 174399 | 160591 |
| input token 均值 | 136602.4 | 124466.1 |
| output token 均值 | 23713.4 | 23288.1 |

均值下降 (160315.8−147754.2)/160315.8 = **7.84%**；中位数下降 (159615−148087)/159615 = **7.22%**。
降幅主要来自 input 侧（−8.9%），output 侧基本持平（−1.8%）。两侧各自的请求范围分布为：Before
五条 252 行、五条 264 行，After 五条 252 行、五条 264 行。样本间并非逐条固定输入配对，且输入
未完全固定，结果为该批样本的描述性统计。

After 12 次尝试共耗 **1729316** token（两条失败合计 251774），作为**执行开销单列**，不与
Before 十个有效样本的合计混为同一成本指标。修订前的 Before 153510.4 / 154416.5 及旧降幅
不再用于本组样本。

## 验证、限制与状态

十个有效 After 的核查记录显示逐调用、逐 agent 与总量对账一致；辩论记录含双方卡片与引用、
四项 Osborn 规则、`debate_rounds=1`、`termination_reason=max_rounds`、`convergence_rounds=null`。
本批实际观察到的终止方式为单轮封顶；结构化输出回退率未纳入统计。

集成版本 `b3157c8…` 的离线记录为 **1462 passed、1 skipped、0 failed**（跳过项为可选
`langchain_aws`）。以上结果来自该集成版本的本地离线回归。

- **跨 UTC 日补样**：两条 Before 补样的分析日仍为 11-19，但实际执行在 UTC 11-20；执行时点差异
  可能影响窗口内可获得新闻与行情终值，影响大小未量化。
- **输入未完全固定**：Before 的新闻等原始输入未完整 fixture 留存，**Before 不可完整重放**；
  两条补样有行情请求与响应原文，其余八条以运行汇总记录留证。
- **行情范围**：After 的 252/264 行对应不同请求起始日期；完整性核查应结合实际请求与原始响应。
- 原 2026-11-18 与 2026-09-01 基线均保留为 superseded 历史，不与本组混算。

## 人类监督与干预

以下监督与干预均有个人原始转录支持（会话来源与消息定位索引见 `transcripts/60671980-LI Runyao.md`，C-A01…C-A10；完整 `full/`/`sources/` 原件在仓库外归档，见该转录说明）：

- **C-A01** 先只读审计计量路径与最小方案、明确批准后，才在独立目录构建成本测量工具。
- **C-A02** 纠正“缺失 usage 被显示为零消耗”，要求增加 `usage_complete` 等状态区分完整/部分/全部缺失。
- **C-A03** 将辩论终止要求落实到**零轮与未收敛**语义（`termination_reason` / `convergence_rounds`）。
- **C-A04** 暂停越过文件所有权边界的修改，并批准把定义迁回 C 负责的模块。
- **C-A05** 阻止不完整输入进入成本验收统计。
- **C-A06** 面对已嵌入辩论记录的重复写入与回归失败，先比较字段与消费者依赖，批准只移除重复写入、保留嵌入式 `debate_record` 全部字段，不削弱测试、不删除辩论证据。
- **C-A07** 否决未经授权的“强制只交付最近 60 行行情”截断（会改变模型明确请求的历史区间）。
- **C-A08** 明确驳回错误的 After 测量树并暂停真实运行。
- **C-A09** 拒绝以无效裁决换取更少调用，并要求完整回归。
- **C-A10** 按证据补样、不按 token 筛选，并如实披露跨 UTC 日限制。

个人转录（LI Runyao / 60671980）保留十条可定位批注；五份原始会话 JSON 与五份完整消息转写在仓库外归档保存（见 `transcripts/60671980-LI Runyao.md` 说明），仓库内仅保留精简转录、消息定位索引与 SHA 清单。

交叉评审材料包括 [C 对 B 评审 memo](../review/C-PEER-REVIEW-B.md) 与 [交叉批注](../review/C-CROSS-ANNOTATIONS-B.md)。

报告数字、样本定位、代码位置与完整转录入口见 [C-EVIDENCE-INDEX.md](C-EVIDENCE-INDEX.md)。
