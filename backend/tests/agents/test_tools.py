from pathlib import Path

import pytest

from app.agents.tools import build_repository_tools
from app.domain.project import ConfirmedContent
from tests.agents.test_backend import make_backend


def test_repository_tools_are_bound_and_expose_no_shell_or_http(tmp_path: Path) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))
    tools = {tool.name: tool for tool in build_repository_tools(backend, allow_draft_write=True)}

    assert set(tools) == {"read_source", "save_draft"}
    assert tools["read_source"].invoke({"path": "canon/premise.md"}) == "confirmed"
    assert tools["read_source"].invoke({"path": "/canon/premise.md"}) == "confirmed"
    tools["save_draft"].invoke({"path": "/drafts/tool.md", "content": "draft"})
    assert drafts.read("story-01", task_id, "tool.md") == "draft"


def test_read_only_repository_tools_do_not_expose_draft_write(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    assert [tool.name for tool in build_repository_tools(backend, allow_draft_write=False)] == [
        "read_source"
    ]


def test_repository_tool_propagates_backend_error(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    read = build_repository_tools(backend, allow_draft_write=False)[0]
    with pytest.raises(RuntimeError, match="WORKSPACE_PATH_VIOLATION"):
        read.invoke({"path": "etc/passwd"})
