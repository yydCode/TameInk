import pytest

from app.infrastructure.secrets import ApiKeyStore, SecretStoreError


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_api_key_store_round_trip_without_exposing_secret() -> None:
    backend = FakeKeyring()
    store = ApiKeyStore(backend)

    store.save("secret-value")

    assert store.get() == "secret-value"
    assert store.has_api_key is True
    assert "secret-value" not in repr(store)
    store.delete()
    assert store.get() is None


def test_api_key_store_rejects_blank_secret() -> None:
    with pytest.raises(ValueError, match="API_KEY_EMPTY"):
        ApiKeyStore(FakeKeyring()).save(" ")


def test_api_key_store_wraps_backend_error_with_stable_code_and_cause() -> None:
    class FailingKeyring(FakeKeyring):
        def get_password(self, service: str, username: str) -> str | None:
            raise OSError("backend detail")

    with pytest.raises(SecretStoreError, match="SECRET_STORE_READ_FAILED") as caught:
        ApiKeyStore(FailingKeyring()).get()
    assert isinstance(caught.value.__cause__, OSError)
    assert "backend detail" not in repr(caught.value)
