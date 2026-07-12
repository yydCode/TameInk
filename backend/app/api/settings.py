from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.model import ModelConfigurationError, build_model, test_connection
from app.infrastructure.secrets import ApiKeyStore, SecretStoreError
from app.infrastructure.settings import ModelSettings, SettingsError, SettingsRepository

router = APIRouter(prefix="/settings", tags=["settings"])

SAFE_CONNECTION_CODES = {
    "MODEL_API_KEY_MISSING",
    "MODEL_SETTINGS_INVALID",
    "MODEL_SETTINGS_NOT_FOUND",
    "MODEL_SETTINGS_READ_FAILED",
    "SECRET_STORE_READ_FAILED",
}


class SettingsResponse(ModelSettings):
    has_api_key: bool


class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    api_key: Annotated[str, Field(min_length=1)]


class SecretStatus(BaseModel):
    has_api_key: bool


def _repositories(request: Request) -> tuple[SettingsRepository, ApiKeyStore]:
    return request.app.state.model_settings, request.app.state.api_keys


@router.get("")
def get_settings(request: Request) -> SettingsResponse:
    settings, secrets = _repositories(request)
    try:
        config = settings.load()
        return SettingsResponse(**config.model_dump(), has_api_key=secrets.has_api_key)
    except RuntimeError as error:
        raise HTTPException(
            status_code=404, detail={"code": str(error), "message": "settings not found"}
        ) from error


@router.put("")
def put_settings(payload: ModelSettings, request: Request) -> SettingsResponse:
    settings, secrets = _repositories(request)
    settings.save(payload)
    return SettingsResponse(**payload.model_dump(), has_api_key=secrets.has_api_key)


@router.put("/secret")
def put_secret(payload: SecretRequest, request: Request) -> SecretStatus:
    _, secrets = _repositories(request)
    try:
        secrets.save(payload.api_key)
        return SecretStatus(has_api_key=True)
    except (ValueError, SecretStoreError) as error:
        raise HTTPException(
            status_code=400, detail={"code": str(error), "message": "secret update failed"}
        ) from error


@router.delete("/secret")
def delete_secret(request: Request) -> SecretStatus:
    _, secrets = _repositories(request)
    try:
        secrets.delete()
        return SecretStatus(has_api_key=False)
    except SecretStoreError as error:
        raise HTTPException(
            status_code=400, detail={"code": str(error), "message": "secret update failed"}
        ) from error


@router.post("/connection")
async def connect(request: Request) -> dict[str, str]:
    settings, secrets = _repositories(request)
    try:
        model = build_model(settings.load(), secrets.get())
        await test_connection(model)
        return {"status": "ok"}
    except (SettingsError, SecretStoreError, ModelConfigurationError) as error:
        candidate = str(error)
        code = candidate if candidate in SAFE_CONNECTION_CODES else "MODEL_CONNECTION_FAILED"
        raise HTTPException(
            status_code=400, detail={"code": code, "message": "connection failed"}
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "MODEL_CONNECTION_FAILED", "message": "connection failed"},
        ) from error
