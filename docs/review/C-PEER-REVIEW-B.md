# C 对 B 架构与需求材料的交叉评审

| 项目 | 内容 |
|---|---|
| Reviewer | LI Runyao / 60671980，C |
| Review date | 2026-11-21，Asia/Shanghai |
| Review target | B 的 PR #5 已合并文档，及个人转录 |
| Snapshot | b88ac95021c65022bf6536108ea055c98292113e |

评审范围包括已合并的蓝图、两份 ADR、B 的个人转录及相关实现代码。

## 主要评审意见

| 编号 | 核对依据 | 观察与建议 |
|---|---|---|
| C-R01 | [蓝图 FR-02](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/architecture-blueprint.md#L53)；[路由](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/src/tradingagents/graph/conditional_logic.py#L26) | 蓝图说路由只读取 count；实际先读取 converged 决定提前结束，再检查 count 上限。建议补全该读取契约，避免未来只按 count 实现而遗漏收敛。 |
| C-R02 | [ADR 001 相关性](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/docs/architecture/adr/001-bound-cost-at-tool-calls.md#L25)；[本次复算来源](C-REVIEW-SOURCE-INDEX.json) | Context 将 r(input,total)=0.9995 归入 11-18 十样本；对同 mean=163633.2 的现存十条 Before 复算为 0.9980636644，并非 0.9995。建议核对该数值的批次归属与计算来源。复算索引提供十条记录的 input/total 和来源 SHA。 |
| C-R03 | [ADR 001 Addendum](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/docs/architecture/adr/001-bound-cost-at-tool-calls.md#L114)；[历史复算记录](C-REVIEW-SOURCE-INDEX.json) | 将 11-18 旧批次的文章数量归因于该日新闻不可得，混淆了原已完成测量和之后优化版的复测失败。现存十个旧 Before 均 data_fetch.complete=true、ticker/news 非空、market_rows=252。建议分别叙述当时已完成的测量和后续复测的取数失败，明确各结论对应的运行批次。 |
| C-R04 | [ADR 001 Evidence](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/docs/architecture/adr/001-bound-cost-at-tool-calls.md#L97)；[ADR 002 Evidence](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/docs/architecture/adr/002-context-layers-compaction-and-reinjection.md#L144)；[已入库统计](../evidence/cost01-2026-11-19/review/summary_revised.json) | 11-19 的 160315.8→147754.2、124466.1/147754.2 已随 PR #8 入库，不应继续全部标为 local/not in repo。建议将 11-19 结果链接到仓库证据目录，并单独注明旧相关性的来源。 |
| C-R05 | [ADR 001 alternatives](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/docs/architecture/adr/001-bound-cost-at-tool-calls.md#L83)；[分析师子图](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/src/tradingagents/graph/setup.py#L53) | max_tool_rounds 限制分析师工具轮次，降低它会提前要求分析师出报告；不是直接截断研究辩论。建议修正 would truncate the debate，保持分析师工具循环与研究辩论循环的概念边界。 |

## 经核对可以保留的设计

- ADR 001 和 ADR 002 均标为 Proposed，与工具调用预算、压缩器的设计状态一致。
- 蓝图将 InvestDebateState.debate_rounds 写为 list，与 state.py 一致；运行摘要中的同名计数为整数，二者不得混用。
- 收敛签名实际为规范化的 (stance, claim) 集合，不是只看 Bullish/Bearish 是否相同；建议蓝图展开 signature 的具体含义。
- ADR 002 采用可注入的估计函数、分工具类型摘要，以及保留 ToolMessage 本体、tool_call_id 和位置；这些是可离线核查的设计约束。
- COST-01 的 11-19 对照与所评版本中登记的 11-18 active baseline 分别列示。

## 评审结论

建议按 C-R01 至 C-R05 更新文档中的状态读取、数据来源和循环边界说明。
对应 B 转录的交叉批注见 [C-CROSS-ANNOTATIONS-B.md](C-CROSS-ANNOTATIONS-B.md)，
被评版本和复算依据见 [C-REVIEW-SOURCE-INDEX.json](C-REVIEW-SOURCE-INDEX.json)。

## 2026-11-22 跟进复核

本次复核 PR #11 `456e1ac`、PR #12 `32d4db8` 与 PR #13 `7af7f50`；三者均为待合并状态。

- **C-R01 / C-R05**：PR #12 已补充 `converged`、`current_response` 与零轮直达 RM 的路由说明，并区分分析师工具循环与研究辩论。ADR 001 Alternatives 仍残留“truncate the debate”的旧句，需删除。蓝图中“RM 对所有非法原因均回退到 max_rounds”的描述与当前 RM 异常状态分支不一致，需与实现修复同步。
- **C-R02 / C-R04**：11-19 纳入的十条 Before 复算 `r(input_tokens,total_tokens)=0.9873830660`，与 PR #12 的 0.9874 一致。ADR 002 中该相关系数属于 Before，而 124466.1 / 147754.2 属于 After，需分别标明批次。两份 ADR 的 Evidence 仍有“未入库”的旧段与新增仓库证据入口并存，需清理。
- **C-R03**：应明确原已完成的 11-18 Before 与后续优化版本复测的新闻取数失败；ADR 001 Addendum 仍残留旧因果句。七天窗口解决模型请求过早窗口的问题，不保证实时服务不再发生超时或 SSL 失败。
- **C-B04 / C-B06**：PR #12 已新增历史需求编号到冻结需求的版本指针；当前提交中的 Annotation 08 仍保留“曾拒绝前一版”的表述，尚未体现 B 本次回复所述收窄为“指令与结果”的修改。
- **PR #11**：十个纳入 run_id 与统计符合修订证据。两条 141 行记录的排除依据应为“请求范围及完整性未独立证实，按审核意见排除并补样”，而不是“已证实请求 252 行却仅返回 141 行”；原记录的 `valid` 未被改写。补样跨 UTC 日的事实见证据包说明。
- **PR #13**：按输入类别设置 freshness limit 与 C 的日期窗口处理职责不同；七天 ticker 新闻适配器仅是本次实验协议，不是应用默认的新鲜度规则。建议 B/D/E 明确 age 相对 `trade_date` 的计算及日历日单位、日期缺失或无效的处理、未来日期的拒绝路径，并补充 age 等于 limit 的边界验证。该 PR 修改需求，尚不构成安全模块实现或图接线完成的证据。

以上为文档及接口复核；原评审快照与复算来源保持不变。

## 2026-11-23 跟进复核

- **基线迁移**：PR #11 已合并至 main `0f0a2eeb7d7bb3b6df04be6e5f929e7a533de141`。COST-01 active baseline 为 NVDA / 2026-11-19，mean 160315.8、median 159615；11-18 与 09-01 保留为 superseded 历史。C 报告与证据索引同步生效状态，实验统计和选择清单不变。
- **PR #12**：复核当前 head `ad323ae660ecff5f1f6fbcb69f3e7f2a9f2cf9bc`。上一轮指出的 Alternatives 旧句、两份 ADR 的旧 Evidence 段及 Addendum 旧因果句已移除；ADR 002 已分别注明 Before 的相关系数与 After 的 input/total 均值。该 PR 仍未合并。
- **C-B06**：分别读取 `32d4db8` 与上述当前 head 中的 B 转录，文件 blob 均为 `ae942374e99c10e85f20d08ec4b4f98ff1e641ac`。Annotation 08 仍含前一版遭拒的叙述，未检出 B 所述“What the record shows, and what it does not”段落；请 B 提供包含该修改的提交或永久链接，再确认闭环。
- **141 行排除说明**：已合并的 COST-01 说明仍称“其余十次均返回 252 行”，并据此断言两条 141 行为不完整抓取。按 `summary_revised.json` 的十个纳入 Before run_id 对照 `MARKET-EVIDENCE.csv`，实际为五条 252 行、五条 264 行。同分析日期、同配置不能证明模型请求范围相同；这两条记录未保存请求范围，因此排除理由应保持为“请求范围及完整性无法独立证实，依审核意见排除并补样”。样本选择和统计无需改变，需求说明请 B 后续修订。
- **后续职责**：`baseline_supplements` 的 Schema 定义由 E 跟进；PR #13 的需求调整与合并顺序由 B 协调。C 本轮仅同步文档，后续按已明确的安全模块接口配合图接线。

## 2026-11-23 评审闭环与 CI 修复复核

- **C-B06 已确认**：B 在 [提交 579d044](https://github.com/Lukelalalalll/cs5351-group-project/commit/579d04480356835f49d5d6b6b92c329f3c66959b) 为 Annotation 08 补充“What the record shows, and what it does not”，明确已保存记录不足以证明所述前后对照，收窄到已呈现的要求与最终文件结果。该补充随 PR #12 合并；此前“未找到该段”的定位问题闭环。
- **141 行说明已确认**：[PR #16](https://github.com/Lukelalalalll/cs5351-group-project/pull/16) 已合并。其五处语义变更均为说明文字，明确缺少请求范围就无法独立判断请求及返回完整性；同日同配置不能证明请求一致。纳入样本、run_id、基线统计及原始记录均未改变，该项评审意见闭环。
- **需求及 Schema 状态**：核对 main `d1dba4f201b4ee43f883233e2fbbce5279904571`，PR #13 与 #15 均已合并；INV-03 按类别期限检查点时输入，实验七天 ticker 新闻窗口不等于应用默认新鲜度规则。Schema 与 CI 配置已入库，不据此认定安全模块或 C 的图接线已经实现。
- **Ruff 独立修复**：[PR #17](https://github.com/Lukelalalalll/cs5351-group-project/pull/17)，commit `32e02b00e0c048264bac7c3178d6b6bafef00c22`，仅五份源码的导入、注解和空行清理，修复 I001×2、UP035×3、UP037×3、F401×1。Ruff 0.17.6 全 `src/` 检查通过；该修复版本本地离线测试为 1487 passed、1 skipped、0 failed。
- **验证与合并状态**：PR #17 的 [GitHub CI](https://github.com/Lukelalalalll/cs5351-group-project/actions/runs/45141022084) 中 Schema Gate、Offline Test Gate、Static Analysis Gate 均通过。本次复核时 #17 尚未合并，不能将其结果写成 main 已全部通过；待维护者合并后，由对应负责人同步技术债和项目状态。
