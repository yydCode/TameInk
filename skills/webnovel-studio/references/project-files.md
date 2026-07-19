# 项目文件规范

本文件用于创建或修复网络小说项目目录。

## 目录结构

```text
projects/小说名/
├─ brief.md
├─ story-bible.md
├─ outline.md
├─ chapter-plan.md
├─ characters.md
├─ world-rules.md
├─ timeline.md
├─ foreshadowing.md
├─ chapter-ledger.md
├─ style-guide.md
├─ previous-summary.md
└─ chapters/
   ├─ 001.md
   ├─ 002.md
   └─ 003.md
```

## 文件用途

`brief.md`：平台、频道、题材、读者承诺、目标读者、目标字数、更新计划、商业目标。

`story-bible.md`：最高优先级事实库。记录核心设定、不可违背事实、主线、主题和禁忌。

`outline.md`：篇章级大纲和长篇引擎。

`chapter-plan.md`：章节级节拍，至少规划接下来 5 章。

`characters.md`：人物事实、动机、关系、状态和说话标记。

`world-rules.md`：金手指、战力体系、社会规则、组织、地理、科技和限制。

`timeline.md`：时间顺序、前史、截止时间、年龄逻辑和过去事件。

`foreshadowing.md`：线索、未解决钩子、计划回收点和状态。

`chapter-ledger.md`：每章已经发生的事实记录。

`style-guide.md`：平台风格、视角、时态、禁忌内容和文字偏好。

`previous-summary.md`：下一章写作前的当前状态摘要。

## 最小标题

每个文件都要有标题，即使内容暂缺也要写“待定”，不要让空白变成隐形歧义。

## 初始化项目

使用：

```bash
python scripts/init_project.py "小说名" --path projects --platform fanqie --channel male --genre "都市高武"
```

然后先补齐项目文件，再写第 1 章。