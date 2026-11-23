# C 完整辩论证据 NVDA 2026 11 19

数据来自 COST-01 已纳入的同十个有效 After 的 full-state 记录。
每条 records/<run_id>.json 原样保存 investment_debate_state 整个对象，以及 Research Manager 的 investment_plan 原文
（在提取件中命名为 research_manager_decision）。

- [来源及 SHA](source-index.json)：关联已入库成本记录、所用源 full-state 的 SHA 与提取件 SHA。
- [逐样本检查](validation-summary.json)：十个样本、一百张卡片通过既有 IdeaCard 模型及非空字段检查；
  RM 引用至少一个有效 ID，实际十样本均引用双方，引用集合与原 debate_record 一致。
- 两阶段及四项 Osborn 标签齐全；十个样本均一轮、max_rounds=1、termination_reason=max_rounds、convergence_rounds=null。
- [校验清单](SHA256SUMS.txt) 排除自身。

## 核查方式

按 source-index.json 的 run_record_path 查找同 run_id 成本记录。提取件保留指定字段的 JSON 值与原文，
使用 JSON 重新序列化，并与本地 full-state 逐对象、逐字符串核对。来源 SHA 标识本地完整原件。

在已安装项目依赖的仓库根目录，可不联网复核：

```python
import importlib.util, json, re, sys
from pathlib import Path
p = Path('src/tradingagents/agents/researchers/debate_schemas.py')
spec = importlib.util.spec_from_file_location('debate_evidence_schema', p)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
for p in Path('docs/evidence/c-debate-2026-11-19/records').glob('*.json'):
    d = json.loads(p.read_text())
    s = d['investment_debate_state']
    b = s['debate_record']
    cards = b['bull_idea_cards'] + b['bear_idea_cards']
    assert b['bull_idea_cards'] and b['bear_idea_cards']
    for c in cards:
        m.IdeaCard.model_validate(c)
        assert all(c[k].strip() for k in ('id','claim','evidence','stance','uncertainty'))
    ids = {c['id'] for c in cards}
    cited = set(re.findall(r'\b(?:bull|bear)-\d+-\d+\b', d['research_manager_decision']))
    assert cited and cited <= ids and cited == set(b['rationale_citations'])
    assert b['phases'] == ['generation','adjudication']
    assert len(b['rounds']) <= b['max_rounds']
    assert s['termination_reason'] == b['termination_reason']
    assert s['convergence_rounds'] == b['convergence_rounds']
print('Existing debate evidence checked')
```

## 验证范围

本包补充 FR-01 卡片及引用的可访问证据，并支持 FR-02 在这十个一轮样本中的记录检查。
本批十个样本均为一轮封顶。检查内容为字段结构、非空值、引用一致性、轮次记录与提取一致性。
