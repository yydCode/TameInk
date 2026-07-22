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


def test_skill_context_compiler_uses_current_records_not_legacy_outline_or_commercial(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    project = workspace.project_path("story-01")
    for path in (
        "project.yaml",
        "commitments/creative-brief.yaml",
        "canon/outline.md",
        "canon/commercial.yaml",
        "commitments/reader-contract.yaml",
        "commitments/story-engine.yaml",
        "commitments/story-cards/card-1.yaml",
        "canon/characters/hero.yaml",
        "commitments/expectations/promise-1.yaml",
        "canon/actual-events/event-1.yaml",
        "canon/chapters/chapter-1.md",
    ):
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("confirmed", encoding="utf-8")

    request = ChapterContextCompiler(workspace, "story-01").request_for_skill(
        "webnovel-draft",
        {
            "story_card_ids": ["card-1"],
            "character_ids": ["hero"],
            "expectation_ids": ["promise-1"],
            "actual_event_ids": ["event-1"],
            "confirmed_chapter_ids": ["chapter-1"],
            "context_intent": {"keywords": ["身份线索"]},
        },
    )

    assert request.stage == "webnovel-draft"
    assert request.fixed_rules == [
        "project.yaml",
        "commitments/creative-brief.yaml",
        "commitments/reader-contract.yaml",
        "commitments/story-engine.yaml",
        "commitments/story-cards/card-1.yaml",
    ]
    assert request.entities == [
        "canon/characters/hero.yaml",
        "commitments/expectations/promise-1.yaml",
        "canon/actual-events/event-1.yaml",
        "canon/chapters/chapter-1.md",
    ]
    assert "canon/outline.md" not in request.fixed_rules
    assert "canon/commercial.yaml" not in request.fixed_rules
