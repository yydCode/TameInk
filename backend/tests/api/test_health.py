from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_service_status_and_version() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "tame-ink-api",
        "version": "0.1.0",
    }
