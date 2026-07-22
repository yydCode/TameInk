---
name: webnovel-audit
description: 对候选正文进行连续性、读者承诺、场景行动或认知负担审稿。用于证据诊断和局部修订方向；不输出统一商业总分，也不自动阻止作者表达。
---

# 证据审稿

本次 `audit_kind` 决定唯一视角：`continuity`、`promise`、`scene` 或 `cognitive_load`。只报告能被正式来源和候选正文共同证明的具体问题。

确定性冲突必须标记为 `conflict`；主观问题标记不确定性、可能反证和局部修改方向。没有问题时返回 `ready` 的空诊断候选，不为了凑数制造问题。

候选类型只能是 `evidence_finding`，属于 `hypothesis`，不能直接正式化。不得输出收入预测、平台推荐判断或商业总分。
