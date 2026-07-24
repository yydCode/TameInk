"""脚本共享 helper：sys.path 注入 + 内存 keyring + AgentRunner 工厂。

被 v4_flash_p1_test.py / v4_flash_p2_test.py / evaluate_chapter.py 复用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import mkdtemp

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.agents.runtime import AgentRunner  # noqa: E402
from app.infrastructure.secrets import ApiKeyStore  # noqa: E402
from app.infrastructure.settings import ModelSettings, SettingsRepository  # noqa: E402
from app.repositories.workspace import WorkspaceRepository  # noqa: E402

# 默认 v4-flash 兼容模型配置
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class MemoryKeyring:
    """内存 keyring backend，绕过桌面环境依赖。"""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def set_password(self, service: str, username: str, password: str) -> None:
        self._api_key = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._api_key

    def delete_password(self, service: str, username: str) -> None:
        self._api_key = ""


def build_runner(
    workspace_dir: Path | None = None,
    project_id: str = "fanqie-eval",
    api_key: str = "",
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> tuple[AgentRunner, WorkspaceRepository, Path]:
    """构建一个配置好 v4-flash 模型的 AgentRunner。

    返回 (runner, workspace, workspace_dir)。
    """
    if workspace_dir is None:
        workspace_dir = Path(mkdtemp(prefix="tame-ink-eval-"))
    workspace = WorkspaceRepository(workspace_dir)
    settings_repo = SettingsRepository(workspace_dir / "settings.json")
    settings_repo.save(
        ModelSettings(
            base_url=base_url,
            model=model,
            timeout=600,
            disable_thinking=True,
        )
    )
    secrets = ApiKeyStore(backend=MemoryKeyring(api_key))
    runner = AgentRunner(workspace, project_id, settings_repo, secrets)
    return runner, workspace, workspace_dir


def print_json(title: str, payload: object, limit: int = 8000) -> None:
    """打印标题 + JSON/文本，超长截断。"""
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:limit])
    else:
        text = str(payload)
        print(text[:limit])
        if len(text) > limit:
            print(f"... [截断，共 {len(text)} 字符]")
