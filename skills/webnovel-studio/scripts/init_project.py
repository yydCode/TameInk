#!/usr/bin/env python3
"""初始化网络小说项目目录和事实库文件。"""

import argparse
import re
from pathlib import Path

REQUIRED_FILES = {
    "brief.md": "# 项目简报\n\n平台：{platform}\n频道：{channel}\n题材：{genre}\n目标读者：待定\n目标字数：待定\n读者承诺：待定\n商业目标：待定\n更新计划：待定\n边界/禁忌：待定\n",
    "story-bible.md": "# 小说事实库\n\n## 核心设定\n待定\n\n## 读者承诺\n待定\n\n## 不可违背事实\n待定\n\n## 主线\n- 升级线：待定\n- 敌人线：待定\n- 秘密线：待定\n- 关系线：待定\n- 地图线：待定\n\n## 设定变更记录\n暂无\n",
    "outline.md": "# 大纲\n\n## 长篇引擎\n待定\n\n## 篇章1\n章节范围：待定\n核心承诺：待定\n起始状态：待定\n结束状态：待定\n主要敌人：待定\n升级/资源收获：待定\n秘密揭露：待定\n关系变化：待定\n篇章高潮：待定\n下一篇章钩子：待定\n",
    "chapter-plan.md": "# 章节计划\n\n## 前 5 章\n\n### 第1章\n钩子：待定\n目标：待定\n冲突：待定\n爽点/回报：待定\n结尾钩子：待定\n\n### 第2章\n钩子：待定\n目标：待定\n冲突：待定\n爽点/回报：待定\n结尾钩子：待定\n\n### 第3章\n钩子：待定\n目标：待定\n冲突：待定\n爽点/回报：待定\n结尾钩子：待定\n\n### 第4章\n钩子：待定\n目标：待定\n冲突：待定\n爽点/回报：待定\n结尾钩子：待定\n\n### 第5章\n钩子：待定\n目标：待定\n冲突：待定\n爽点/回报：待定\n结尾钩子：待定\n",
    "characters.md": "# 人物表\n\n## 主角\n姓名：待定\n年龄：待定\n身份：待定\n目标：待定\n伤口/缺陷：待定\n优势：待定\n秘密：待定\n状态：待定\n事实约束：待定\n\n## 配角\n待定\n\n## 反派\n待定\n",
    "world-rules.md": "# 世界规则\n\n## 背景设定\n待定\n\n## 金手指\n名称：待定\n触发方式：待定\n能做什么：待定\n不能做什么：待定\n代价/风险/冷却：待定\n成长路径：待定\n如何制造新麻烦：待定\n\n## 战力/系统规则\n待定\n\n## 组织\n待定\n\n## 地点\n待定\n",
    "timeline.md": "# 时间线\n\n## 前史\n待定\n\n## 当前时间线\n待定\n\n## 截止时间\n待定\n",
    "foreshadowing.md": "# 伏笔表\n\n| 编号 | 埋设章节 | 线索 | 计划回收 | 状态 | 备注 |\n| --- | --- | --- | --- | --- | --- |\n| 待定 | 待定 | 待定 | 待定 | 未回收 | 待定 |\n",
    "chapter-ledger.md": "# 章节台账\n\n每章写完后在这里记录已经发生的事实。\n\n## 模板\n\n时间：\n地点：\n主角目标：\n主要冲突：\n本章结果：\n新增人物：\n新增事实：\n人物关系变化：\n资源/地位变化：\n金手指使用：\n战力/能力变化：\n新增伏笔：\n回收伏笔：\n未解决问题：\n下一章承接：\n",
    "style-guide.md": "# 风格指南\n\n平台：{platform}\n频道：{channel}\n题材：{genre}\n视角：待定\n语气：待定\n节奏：商业网文快节奏\n段落风格：适合移动端阅读的短段落\n平台注意事项：待定\n禁忌内容：抄袭、近似模仿、无来源平台结论、破坏事实库的捷径\n",
    "previous-summary.md": "# 最新摘要\n\n尚未写章节。\n",
}


def slugify(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", name.strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned.strip("-.") or "未命名小说"


def main() -> None:
    parser = argparse.ArgumentParser(description="创建网络小说项目目录。")
    parser.add_argument("name", help="小说/项目名称")
    parser.add_argument("--path", default="projects", help="项目父目录")
    parser.add_argument("--platform", default="待定", help="目标平台，例如 fanqie")
    parser.add_argument("--channel", default="待定", help="目标频道，例如 male/female")
    parser.add_argument("--genre", default="待定", help="题材组合")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的模板文件")
    args = parser.parse_args()

    project_dir = Path(args.path).expanduser().resolve() / slugify(args.name)
    chapters_dir = project_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    created = []
    skipped = []
    for filename, template in REQUIRED_FILES.items():
        target = project_dir / filename
        if target.exists() and not args.overwrite:
            skipped.append(filename)
            continue
        target.write_text(
            template.format(platform=args.platform, channel=args.channel, genre=args.genre),
            encoding="utf-8",
        )
        created.append(filename)

    print(f"项目目录：{project_dir}")
    print(f"章节目录：{chapters_dir}")
    if created:
        print("已创建文件：")
        for name in created:
            print(f"- {name}")
    if skipped:
        print("已跳过存在文件：")
        for name in skipped:
            print(f"- {name}")


if __name__ == "__main__":
    main()
