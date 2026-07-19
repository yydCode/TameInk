from pathlib import Path

from app.agents.context_compiler import ChapterContextCompiler
from app.domain.project import ConfirmedContent, Project
from app.repositories.canon import CanonRepository
from app.repositories.workspace import WorkspaceRepository


def test_chapter_context_compiler_selects_volume_recent_summaries_and_intent(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    for path, content in {
        "canon/outline.md": "全书大纲",
        "canon/volumes/2.md": "第二卷",
        "memory/summaries/book.md": "全书状态",
        "memory/summaries/volumes/2.md": "第二卷状态",
        "memory/summaries/chapters/1.md": "第一章",
        "memory/summaries/chapters/2.md": "第二章",
        "memory/summaries/chapters/3.md": "第三章",
        "memory/summaries/chapters/4.md": "第四章",
    }.items():
        canon.write_markdown("story-01", path, ConfirmedContent(markdown=content))

    request = ChapterContextCompiler(workspace, "story-01").request_for(
        "DraftWriter",
        {
            "chapter_id": "5",
            "volume_id": "2",
            "plan": {
                "context_intent": {
                    "characters": ["林默"],
                    "locations": [],
                    "abilities": [],
                    "foreshadowing": [],
                    "keywords": ["雨夜线索"],
                }
            },
        },
    )

    assert request.stage == "DraftWriter"
    assert request.volume == ["canon/volumes/2.md"]
    assert request.summaries == [
        "memory/summaries/book.md",
        "memory/summaries/volumes/2.md",
        "memory/summaries/chapters/2.md",
        "memory/summaries/chapters/3.md",
        "memory/summaries/chapters/4.md",
    ]
    assert request.fts_queries == ["林默", "雨夜线索"]
