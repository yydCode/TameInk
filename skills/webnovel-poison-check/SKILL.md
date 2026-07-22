---
name: webnovel-poison-check
description: 用毒点清单检查正文，发现会导致读者弃书的结构性写作陷阱（人设崩塌、机械降神、无意义受苦、节奏崩塌等）。
---

# 毒点检测

毒点是让读者弃书的结构性错误，区别于普通写作瑕疵。本次审核按 `skill.yaml` 的 `poison_checklist` 逐条检查正文，对每个发现给出：

- 发生位置的精确引用证据（必须逐字引用正式来源）
- 判断依据（符合哪条 detection_signals）
- 修改方向建议

error 级毒点发现即必须报告；warning 级只在有明确证据时报告，不为凑数制造问题。

候选类型只能是 `evidence_finding`，属于 `hypothesis`，不能直接正式化。
没有毒点时返回 `ready` 的空诊断候选，不得凭空编造问题。
