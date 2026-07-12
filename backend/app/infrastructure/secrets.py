from typing import Protocol

import keyring

SERVICE_NAME = "tame-ink"
ACCOUNT_NAME = "model-api-key"


class KeyringBackend(Protocol):
    def set_password(self, service: str, username: str, password: str) -> None: ...

    def get_password(self, service: str, username: str) -> str | None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class SecretStoreError(RuntimeError):
    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)!r})"


class ApiKeyStore:
    def __init__(self, backend: KeyringBackend = keyring) -> None:
        self._backend = backend

    @property
    def has_api_key(self) -> bool:
        return self.get() is not None

    def save(self, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("API_KEY_EMPTY")
        try:
            self._backend.set_password(SERVICE_NAME, ACCOUNT_NAME, api_key)
        except Exception as error:
            raise SecretStoreError("SECRET_STORE_WRITE_FAILED") from error

    def get(self) -> str | None:
        try:
            return self._backend.get_password(SERVICE_NAME, ACCOUNT_NAME)
        except Exception as error:
            raise SecretStoreError("SECRET_STORE_READ_FAILED") from error

    def delete(self) -> None:
        try:
            self._backend.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        except Exception as error:
            raise SecretStoreError("SECRET_STORE_DELETE_FAILED") from error

    def __repr__(self) -> str:
        return f"{type(self).__name__}(has_api_key={self.has_api_key})"
