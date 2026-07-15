from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.project import ConfirmedContent
from app.main import create_app
from app.repositories.canon import CanonRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository


def test_memory_and_search_api_complete_correction_lifecycle(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    CanonRepository(workspace).write_markdown(
        "story-01",
        "canon/chapters/0001.md",
        ConfirmedContent(markdown="雨夜相遇\n长街重逢"),
    )
    RevisionRepository(workspace).current_revision("story-01")

    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects/story-01/memory",
            json={
                "id": "meeting",
                "kind": "fact",
                "source": "canon/chapters/0001.md",
                "location": "line 1, column 1",
                "quote": "雨夜相遇",
            },
        )
        fetched = client.get("/api/projects/story-01/memory/fact/meeting")
        corrected = client.put(
            "/api/projects/story-01/memory/fact/meeting",
            json={
                "source": "canon/chapters/0001.md",
                "location": "line 2, column 1, char 5",
                "quote": "长街重逢",
            },
        )
        searched = client.get("/api/projects/story-01/search", params={"q": "长街重逢"})
        revoked = client.post("/api/projects/story-01/memory/fact/meeting/revoke")

    assert created.status_code == 201
    assert fetched.json()["quote"] == "雨夜相遇"
    assert corrected.json()["location"] == "line 2, column 1, char 5"
    assert [hit["path"] for hit in searched.json()] == [
        "canon/chapters/0001.md",
        "memory/facts/meeting.yaml",
    ]
    assert revoked.json()["status"] == "superseded"
