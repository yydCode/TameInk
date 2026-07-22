---
name: webnovel-studio
description: Tame Ink 人机协作网文创作系统的共享执行边界。用于理解候选、正式事实、作者决策和证据规则；不直接生成作品内容。
---

# 创作系统边界

遵守四层事实：`canon` 是已发生事实，`commitment` 是作者确认的承诺，`candidate` 是待审批内容，`hypothesis` 是观察或未验证判断。

只把作者确认过的正式文件当作既定事实。缺少关键前提、发现冲突或需要不可逆选择时，停止生成候选并返回 `needs_decision` 或 `conflict`。

每次执行只服务一个主 Skill。返回 `SkillExecutionContract`：

- `ready`：提供一个可存储候选及其影响范围。
- `needs_decision`：提供作者必须回答的问题，不提供候选。
- `conflict`：提供来源证据、反证方向和待决策问题，不提供候选。

不写正式文件，不修改历史，不把候选、审稿判断或平台观察描述为作者确认事实。
