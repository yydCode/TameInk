"""测试词汇检测 API 端点。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(workspace_root=tmp_path)
    return TestClient(app)


def test_vocabulary_check_returns_issues(client: TestClient) -> None:
    response = client.post(
        "/api/projects/test-proj/vocabulary-check",
        json={
            "text": """
                主角心头一震，不由得后退。他心头一震，再次不由得感叹。
                这段描写嘴角微扬，淡淡地说道。
            """
        },
    )
    assert response.status_code == 200
    issues = response.json()
    assert isinstance(issues, list)
    assert len(issues) >= 2  # 至少"心头一震"和"不由得"
    # 套话应该排在前面
    assert issues[0]["category"] == "cliche"


def test_vocabulary_check_handles_clean_text(client: TestClient) -> None:
    response = client.post(
        "/api/projects/test-proj/vocabulary-check",
        json={"text": "主角走进房间，观察四周环境。桌上放着一封信。"},
    )
    assert response.status_code == 200
    issues = response.json()
    assert issues == []


def test_vocabulary_check_rejects_missing_text(client: TestClient) -> None:
    response = client.post("/api/projects/test-proj/vocabulary-check", json={})
    assert response.status_code == 422  # Pydantic validation error
