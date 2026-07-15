from langchain_core.tools import BaseTool, tool

from app.agents.backend import NovelWorkspaceBackend
from app.domain.errors import WorkspacePathViolationError
from app.domain.paths import validate_formal_path


def build_repository_tools(
    backend: NovelWorkspaceBackend, *, allow_draft_write: bool
) -> list[BaseTool]:
    @tool
    def read_source(path: str) -> str:
        """Read a whitelisted formal path, with an optional leading slash."""
        formal_path = path.removeprefix("/")
        try:
            validate_formal_path(formal_path)
        except WorkspacePathViolationError as error:
            raise RuntimeError(error.code) from error
        result = backend.read(f"/{formal_path}", 0, 1_000_000)
        if result.error is not None or result.file_data is None:
            raise RuntimeError(result.error or "SOURCE_READ_FAILED")
        return result.file_data["content"]

    tools: list[BaseTool] = [read_source]
    if allow_draft_write:

        @tool
        def save_draft(path: str, content: str) -> str:
            """Save one new file beneath the current task's /drafts root."""
            result = backend.write(path, content)
            if result.error is not None:
                raise RuntimeError(result.error)
            return result.path or path

        tools.append(save_draft)
    return tools
