from pathlib import Path
from uuid import uuid4

import pytest
from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.backend import NovelWorkspaceBackend
from app.domain.errors import WorkspacePathViolationError
from app.domain.project import ConfirmedContent
from app.repositories.canon import CanonRepository
from app.repositories.drafts import DraftRepository
from app.repositories.workspace import WorkspaceRepository
from tests.agents.fake_model import ScriptedChatModel


def make_backend(
    tmp_path: Path,
) -> tuple[NovelWorkspaceBackend, CanonRepository, DraftRepository, str]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    task_id = str(uuid4())
    canon = CanonRepository(workspace)
    drafts = DraftRepository(workspace)
    return NovelWorkspaceBackend(canon, drafts, "story-01", task_id), canon, drafts, task_id


def test_backend_reads_canon_through_repository_and_writes_only_current_draft(
    tmp_path: Path,
) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))

    read = backend.read("/canon/premise.md")
    written = backend.write("/drafts/chapter.md", "draft")

    assert read.file_data == {"content": "confirmed", "encoding": "utf-8"}
    assert written.error is None
    assert drafts.read("story-01", task_id, "chapter.md") == "draft"


@pytest.mark.parametrize(
    "path",
    [
        "/canon/premise.md",
        "/memory/facts/fact-1.yaml",
        "/etc/passwd",
        "/drafts/../other.md",
        "drafts/file.md",
        "/drafts\\file.md",
    ],
)
def test_backend_rejects_write_outside_current_drafts(tmp_path: Path, path: str) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    result = backend.write(path, "blocked")
    assert result.error == "WORKSPACE_PATH_VIOLATION"


def test_draft_repository_rejects_task_or_path_escape(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    drafts = DraftRepository(workspace)
    with pytest.raises(WorkspacePathViolationError):
        drafts.write("story-01", "not-a-task", "chapter.md", "draft")
    with pytest.raises(WorkspacePathViolationError):
        drafts.write("story-01", str(uuid4()), "../chapter.md", "draft")


def test_backend_edit_is_exact_and_locked_to_current_task(tmp_path: Path) -> None:
    backend, _, drafts, task_id = make_backend(tmp_path)
    drafts.write("story-01", task_id, "chapter.md", "old text")
    result = backend.edit("/drafts/chapter.md", "old", "new")
    assert result.error is None
    assert result.occurrences == 1
    assert drafts.read("story-01", task_id, "chapter.md") == "new text"


@pytest.mark.parametrize("replace_all", [False, True])
def test_backend_edit_rejects_empty_old_string(tmp_path: Path, replace_all: bool) -> None:
    backend, _, drafts, task_id = make_backend(tmp_path)
    drafts.write("story-01", task_id, "chapter.md", "text")
    result = backend.edit("/drafts/chapter.md", "", "injected", replace_all=replace_all)
    assert result.error == "EDIT_TARGET_INVALID"
    assert drafts.read("story-01", task_id, "chapter.md") == "text"


def test_backend_grep_propagates_invalid_virtual_path(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    result = backend.grep("needle", "/etc")
    assert result.error == "WORKSPACE_PATH_VIOLATION"


def test_create_deep_agent_builtin_write_obeys_backend_and_permissions(tmp_path: Path) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))
    register_harness_profile(
        "scriptedchatmodel",
        HarnessProfile(
            excluded_tools=frozenset({"execute"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )

    def invoke_write(path: str, content: str) -> list[ToolMessage]:
        model = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"file_path": path, "content": content},
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
        graph = create_deep_agent(
            model=model,
            backend=backend,
            permissions=[
                FilesystemPermission(operations=["write"], paths=["/drafts/**"], mode="allow"),
                FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            ],
        )
        result = graph.invoke({"messages": [{"role": "user", "content": "write"}]})
        return [message for message in result["messages"] if isinstance(message, ToolMessage)]

    assert invoke_write("/drafts/generated.md", "draft")[0].status == "success"
    assert drafts.read("story-01", task_id, "generated.md") == "draft"
    assert invoke_write("/canon/premise.md", "changed")[0].status == "error"
    assert invoke_write("/tmp/escape.md", "changed")[0].status == "error"
    assert canon.read_markdown("story-01", "canon/premise.md").markdown == "confirmed"


def test_backend_upload_download_stays_inside_virtual_workspace(tmp_path: Path) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))

    uploaded = backend.upload_files(
        [
            ("/drafts/nested/chapter.md", b"draft"),
            ("/canon/outline.md", b"blocked"),
            ("/tmp/escape.md", b"blocked"),
            ("/drafts/../escape.md", b"blocked"),
        ]
    )
    assert uploaded[0].error is None
    assert [item.error for item in uploaded[1:]] == [
        "WORKSPACE_PATH_VIOLATION",
        "WORKSPACE_PATH_VIOLATION",
        "WORKSPACE_PATH_VIOLATION",
    ]
    assert drafts.read("story-01", task_id, "nested/chapter.md") == "draft"

    downloaded = backend.download_files(
        ["/drafts/nested/chapter.md", "/canon/premise.md", "/etc/passwd"]
    )
    assert [item.content for item in downloaded[:2]] == [b"draft", b"confirmed"]
    assert downloaded[2].error == "WORKSPACE_PATH_VIOLATION"


def test_backend_ls_returns_only_sorted_direct_children_and_directories(tmp_path: Path) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="premise"))
    canon.write_markdown(
        "story-01", "canon/chapters/chapter-1.md", ConfirmedContent(markdown="chapter")
    )
    drafts.write("story-01", task_id, "nested/chapter.md", "draft")

    assert backend.ls("/").entries == [
        {"path": "/canon", "is_dir": True},
        {"path": "/drafts", "is_dir": True},
        {"path": "/memory", "is_dir": True},
    ]
    assert backend.ls("/canon").entries == [
        {"path": "/canon/chapters", "is_dir": True},
        {"path": "/canon/premise.md", "is_dir": False},
    ]
    assert backend.ls("/canon/chapters").entries == [
        {"path": "/canon/chapters/chapter-1.md", "is_dir": False}
    ]
    assert backend.ls("/drafts").entries == [{"path": "/drafts/nested", "is_dir": True}]
    assert backend.ls("/memory").entries == []

    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/canon"}, "id": "ls-1"}],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = create_deep_agent(model=model, backend=backend)
    result = graph.invoke({"messages": [{"role": "user", "content": "list"}]})
    tool_result = next(
        message.content
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "ls-1"
    )
    assert "/canon/chapters" in tool_result
    assert "/canon/chapters/chapter-1.md" not in tool_result
