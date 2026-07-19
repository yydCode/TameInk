---
name: webnovel-studio
description: 中文商业网络小说创作工作室。用于网络小说平台调研、题材选择、新书策划、书名简介、人设、金手指、战力体系、大纲、全书结构、七步写作法、章节写作、章节改写、审稿评分、长篇连贯性维护、事实库管理、防止剧情跑偏和设定幻觉。适用于番茄小说、起点、七猫、飞卢、晋江，以及都市脑洞、都市高武、玄幻、系统流、重生、快穿、古言脑洞、末世囤货、爽文、serialized webnovel 等任务。
---

# 网络小说工作室

本 skill 用于中文商业网络小说的策划、写作、审稿、连贯性维护和平台适配。

## 核心规则

不要只凭临场想象写长篇。所有长篇创作都必须落到项目事实库、大纲、嵌套结构和商业网文技法上。

事实优先级：
1. `story-bible.md`
2. `world-rules.md`、`characters.md`、`timeline.md`、`foreshadowing.md`
3. `outline.md`、`chapter-plan.md`、`chapter-ledger.md`、`previous-summary.md`
4. 已写章节正文
5. 新灵感

如果新想法与既定事实或宏观结构冲突，先指出冲突，不要硬写。只有明确标记为“设定变更”并记录影响范围后，才能修改核心事实。

## 默认流程

新书项目：
1. 明确平台、频道、题材、目标读者、读者承诺、主角、核心冲突、金手指和长篇连载引擎。
2. 如果用户要求市场方向，只使用公开平台信息做调研，并标明来源或不确定性。
3. 写长章节前，先创建或更新项目文件。
4. 设计嵌套结构：全书、升级梯、第一卷/地图、第一篇章、第一组小篇章、前 5 章。
5. 第 1 章按商业节奏和七步起承转合法起草，再评分和修改。
6. 每章写完后更新连续性文件。

续写章节：
1. 先读取相关项目文件：`brief.md`、`story-bible.md`、`outline.md`、`chapter-plan.md`、`characters.md`、`world-rules.md`、`timeline.md`、`foreshadowing.md`、`chapter-ledger.md`、`previous-summary.md`、`style-guide.md`。
2. 用 `references/novel-architecture.md` 确认当前章节在全书、篇章和小篇章里的作用。
3. 默认用 `references/seven-step-structure.md` 作为章节结构，除非用户指定其他结构。
4. 按章节计划和平台风格写正文。
5. 章节元数据需要记录：钩子、主角目标、主要冲突、情绪回报、新增事实、变更事实、伏笔、下章钩子、七步检查。
6. 输出前先做连续性检查。
7. 如果任务包含落盘修改，写完后更新 `chapter-ledger.md` 和 `previous-summary.md`。

审稿或评分：
1. 先看商业留存，再看文学润色。
2. 按 `references/editing-rubric.md` 评分。
3. 检查章节是否具备七步爽点链：优势亮相、反派抬高、初次摩擦、信息差、反转、震惊、收获与钩子。
4. 检查章节是否推进当前升级梯和小篇章目标。
5. 优先指出最影响追读、爽点、节奏或连贯性的 3 个问题。
6. 能给改写就给可直接替换的改写。
7. 不做空泛表扬。

## 防幻觉规则

- 不虚构平台数据、榜单规则、读者统计或内部推荐算法。
- 平台调研只使用公开来源；不确定的信息必须标记为推断或未知。
- 不擅自新增关键故事事实；新增时必须标记为“新增事实”。
- 已定义的人名、年龄、关系、死亡状态、能力、地点、时间和战力等级不得随意更改。
- 关键事实缺失时，先说明缺失项，或给出明确的“临时假设”。
- 项目文件互相矛盾时，先报告矛盾并建议修复。

## 参考文件导航

按任务只读取需要的参考文件：

- `references/workflow.md`：任务流程、章节循环和长篇节奏。
- `references/research-rules.md`：平台公开调研规则和输出格式。
- `references/commercial-writing.md`：商业网文写作规则。
- `references/novel-architecture.md`：全书、卷、篇章、小篇章、章节、场景的嵌套结构。
- `references/seven-step-structure.md`：七步起承转合章节结构和爽点梯。
- `references/planning-system.md`：新书设定、书名、人设、金手指、嵌套大纲和长篇引擎。
- `references/chapter-writing.md`：章节写作模板和元数据要求。
- `references/editing-rubric.md`：评分、审稿和改写标准。
- `references/continuity-system.md`：事实库、章节台账、时间线、伏笔和防跑偏检查。
- `references/platform-styles.md`：平台和频道适配。
- `references/project-files.md`：项目目录和文件模板。

脚本：

- `scripts/init_project.py`：创建标准网络小说项目目录。
- `scripts/validate_project.py`：检查项目文件是否完整。

## 输出纪律

用户要正文时，优先给正文；除非用户要求分析，否则不要把分析放在正文前。章节元数据放在正文后；如果用户要求干净正文，可以隐藏元数据但仍在内部按元数据检查。