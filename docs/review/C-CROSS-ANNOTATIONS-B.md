# C 对 B 个人转录的交叉批注

评审者：LI Runyao / 60671980，C。被评者：袁舞扬 / 60211808，B。
评审日期：2026-11-21，Asia/Shanghai。被评版本：main b88ac95021c65022bf6536108ea055c98292113e。

## C-B01 使成本配置判据能够区分改造前后

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L164)。

1. 本次于 2026-11-21 阅读 B 的 Session 1 Turn 2 及 Annotation 01。

2. B 拒绝只要求不超过既有循环上限的判据，并要求有效配置从 20/20/5 变成 8/8/3。

3. 这符合 COST-01 的可验证要求，配置正确性与实际 token 变化需要分别验证。

4. 我认可这一拒绝及目标配置检查，建议最终报告继续同时保留真实成本对照，避免把配置值等同于节省效果。

## C-B02 将任务描述转成可检查的不变式

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L210)。

1. 本次于 2026-11-21 阅读 B 的 Session 1 Turn 3 及其后续输出。

2. B 把“规则必须明确”这一工作任务改成评级词表、仓位上限、日期不匹配和禁止 LLM 自检等系统约束，agent 也指出仓位 cap 数值尚缺。

3. INV-01/02/03 应描述给定输入下可检查的系统行为，业务阈值需要明确来源。

4. 我认可该重写方向，建议后续将 cap 的配置来源、拒绝默认仓位及对应负向用例继续保持可追溯，不把示例阈值当实际生效配置。

## C-B03 区分防未来数据与拒绝过期输入

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L277)。

1. 本次于 2026-11-21 阅读 B 的 Session 1 Turn 4 第二项及 Annotation 04。

2. 该指令明确区分 date_window 的未来日期裁剪和决策层 stale-data 拒绝，不直接复用前者充当后者。

3. 当前 INV-03 的 source 也说明两者不同，这是防止测试通过了错误机制的必要语义边界。

4. 我认可这项区分，建议证据链接该指令，并在需求与测试中保留两个机制的不同职责。

## C-B04 历史 agent 输出不等于冻结后的最终需求

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L334)。

1. 本次于 2026-11-21 对照 B 的 Session 1 Turn 5 最终输出与 main 的 requirements.yaml。

2. 会话输出中的 FR-04 是仓位解析、FR-05 是决策元数据，而当前冻结 YAML 的 FR-04 是 token 计量、FR-05 是 guard。

3. 实现与验收应以冻结后的 PRD 为准，历史草稿与最终需求之间需要清楚的版本关系。

4. 我建议 B 补一个从该草稿到最终采纳版本的说明或版本指针；保持原始转录不变，当前实现与验收引用 main 的最终 PRD。

## C-B05 以测量证据修正验收单位并保护同伴记录

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L408)。

1. 本次于 2026-11-21 阅读 B 的 Session 2、差异及 Annotation 08。

2. B 用 rounds 与 calls 的区别和旧批次双峰分布解释从逐次阈值改成十样本均值、中位数，同时要求保留 C 的 baseline 原行并新增字段。

3. 这体现 COST-01 的可比性和单文件所有权治理，但会话中的 09-01 数字只属于历史阶段，不应直接当作当前 active baseline。

4. 我认可用证据推动需求修订及保留原记录的做法，建议最终评测注明各版本采纳时点，避免把旧指标迁移当作优化收益。

## C-B06 区分批注自述与已呈现的原始往返

来源：[B 转录对应段落](https://github.com/Lukelalalalll/cs5351-group-project/blob/b88ac95021c65022bf6536108ea055c98292113e/transcripts/60211808-%E8%A2%81%E8%88%9E%E6%89%AC.md#L551)。

1. 本次于 2026-11-21 阅读 B 的 Annotation 08 并回看 Session 2 展示的 prompt 和 diff。

2. 批注自述曾拒绝 agent 改写 baseline 原行，而当前正文展示的是已保持该行不变的结果，未包含被拒绝的前一版输出。

3. 转录中的干预应能定位到原始指令、被拒绝的输出和后续结果。

4. 建议补充前一版输出的消息定位或附件，保留当前已展示的正确 diff。

对应架构与实现的核查见 [C-PEER-REVIEW-B.md](C-PEER-REVIEW-B.md)。原始材料 SHA 见 [C-REVIEW-SOURCE-INDEX.json](C-REVIEW-SOURCE-INDEX.json)。
