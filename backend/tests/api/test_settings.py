import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import ModelSettings
from app.main import create_app
from tests.infrastructure.test_secrets import FakeKeyring


def client_for(tmp_path: Path) -> tuple[TestClient, FakeKeyring]:
    application = create_app(tmp_path)
    backend = FakeKeyring()
    application.state.api_keys = ApiKeyStore(backend)
    return TestClient(application), backend


def test_settings_api_never_echoes_secret(tmp_path: Path) -> None:
    client, _ = client_for(tmp_path)
    config = {"base_url": "https://api.example.com/v1", "model": "model-1", "timeout": 30.0}

    put_config = client.put("/api/settings", json=config)
    put_secret = client.put("/api/settings/secret", json={"api_key": "secret-value"})
    get_config = client.get("/api/settings")

    assert put_config.status_code == 200
    assert put_secret.json() == {"has_api_key": True}
    assert get_config.json() == {**config, "has_api_key": True}
    assert "secret-value" not in repr([put_config.json(), put_secret.json(), get_config.json()])


def test_settings_api_delete_secret(tmp_path: Path) -> None:
    client, _ = client_for(tmp_path)
    client.put("/api/settings/secret", json={"api_key": "secret-value"})
    response = client.delete("/api/settings/secret")
    assert response.json() == {"has_api_key": False}


def test_settings_api_rejects_unsafe_config_with_stable_http_error(tmp_path: Path) -> None:
    client, _ = client_for(tmp_path)
    response = client.put(
        "/api/settings",
        json={"base_url": "http://remote.example.com", "model": "model-1", "timeout": 30},
    )
    assert response.status_code == 422
    assert "secret" not in response.text.lower()


def test_connection_is_explicit_and_uses_saved_config_and_secret(
    tmp_path: Path, monkeypatch
) -> None:
    client, _ = client_for(tmp_path)
    client.put(
        "/api/settings",
        json={
            "base_url": "https://api.example.com/v1",
            "model": "ft:gpt-4o-mini:org:custom",
            "timeout": 30.0,
        },
    )
    client.put("/api/settings/secret", json={"api_key": "secret-value"})
    calls: list[object] = []

    async def fake_connection(model: object) -> None:
        calls.append(model)

    monkeypatch.setattr("app.api.settings.test_connection", fake_connection)
    response = client.post("/api/settings/connection")
    assert response.json() == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0].model_name == "ft:gpt-4o-mini:org:custom"
    assert "secret-value" not in response.text


def test_connection_without_secret_has_stable_error(tmp_path: Path) -> None:
    client, _ = client_for(tmp_path)
    client.put(
        "/api/settings",
        json={"base_url": "https://api.example.com/v1", "model": "model-1", "timeout": 30.0},
    )
    response = client.post("/api/settings/connection")
    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "MODEL_API_KEY_MISSING", "message": "connection failed"}
    }


@pytest.mark.parametrize(
    "provider_error",
    [RuntimeError("SECRET_API_KEY_ABC"), Exception("ordinary provider detail")],
)
def test_connection_sdk_error_is_stable_and_redacted(
    tmp_path: Path, monkeypatch, provider_error: Exception
) -> None:
    client, _ = client_for(tmp_path)
    client.put(
        "/api/settings",
        json={
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
            "timeout": 30.0,
        },
    )
    client.put("/api/settings/secret", json={"api_key": "secret-value"})

    async def fail_connection(model: object) -> None:
        raise provider_error

    monkeypatch.setattr("app.api.settings.test_connection", fail_connection)
    response = client.post("/api/settings/connection")
    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "MODEL_CONNECTION_FAILED", "message": "connection failed"}
    }
    assert "secret-value" not in response.text
    assert str(provider_error) not in response.text


def test_connection_keyring_read_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    class SlowKeyring(FakeKeyring):
        def get_password(self, service: str, username: str) -> str | None:
            time.sleep(0.15)
            return super().get_password(service, username)

    async def run() -> None:
        application = create_app(tmp_path)
        backend = SlowKeyring()
        application.state.api_keys = ApiKeyStore(backend)
        application.state.model_settings.save(
            ModelSettings(
                base_url="https://api.example.com/v1",
                model="model-1",
                timeout=30.0,
            )
        )
        application.state.api_keys.save("secret-value")

        async def fake_connection(model: object) -> None:
            return None

        monkeypatch.setattr("app.api.settings.test_connection", fake_connection)
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ticker_task = asyncio.create_task(ticker())
            request_task = asyncio.create_task(client.post("/api/settings/connection"))
            await asyncio.sleep(0.03)
            assert ticks > 1
            assert not request_task.done()
            response = await request_task
            running = False
            await ticker_task
        assert response.status_code == 200

    asyncio.run(run())
