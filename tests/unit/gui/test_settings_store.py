from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from spec2code.gui.settings_store import KEYRING_SERVICE, SettingsStore


class FakeKeyring:
    priority = 1

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.passwords.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.passwords[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.passwords.pop((service, name), None)


class BrokenKeyring:
    priority = 1

    def get_password(self, service: str, name: str) -> str | None:
        raise RuntimeError("unavailable")

    def set_password(self, service: str, name: str, value: str) -> None:
        raise RuntimeError("unavailable")

    def delete_password(self, service: str, name: str) -> None:
        raise RuntimeError("unavailable")


def test_nonsecrets_persist_with_semantic_names_and_saved_value_wins(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path, environment={"AWS_REGION": "from-env"}, keyring_backend=BrokenKeyring())

    store.update_nonsecrets({"aws_region": "from-file", "ollama_base_url": "http://ollama/v1"})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "aws_region": "from-file",
        "ollama_base_url": "http://ollama/v1",
    }
    settings = store.read()
    assert settings["aws_region"] == {
        "configured": True,
        "source": "config",
        "secret": False,
        "value": "from-file",
    }
    assert settings["ollama_base_url"]["source"] == "config"


def test_config_path_can_be_overridden_by_environment(tmp_path):
    path = tmp_path / "overridden.json"
    store = SettingsStore(environment={"SPEC2CODE_GUI_SETTINGS_PATH": str(path)}, keyring_backend=BrokenKeyring())

    store.update_nonsecrets({"aws_profile": "development"})

    assert store.config_path == path
    assert json.loads(path.read_text(encoding="utf-8")) == {"aws_profile": "development"}


def test_secrets_use_keyring_and_are_redacted_from_reads_and_json(tmp_path):
    backend = FakeKeyring()
    store = SettingsStore(tmp_path / "settings.json", environment={}, keyring_backend=backend)

    store.update_nonsecrets({"vllm_base_url": "http://vllm/v1"})
    store.update_secrets({"openai_api_key": "openai-secret", "vllm_api_key": "vllm-secret"})

    assert backend.passwords[(KEYRING_SERVICE, "openai_api_key")] == "openai-secret"
    assert store.read()["openai_api_key"] == {
        "configured": True,
        "source": "keyring",
        "secret": True,
    }
    assert "secret" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_broken_keyring_falls_back_to_memory_and_clear_is_explicit(tmp_path):
    store = SettingsStore(tmp_path / "settings.json", environment={}, keyring_backend=BrokenKeyring())
    store.update_secrets({"anthropic_api_key": "memory-secret"})

    assert store.read()["anthropic_api_key"]["source"] == "memory"
    assert not (tmp_path / "settings.json").exists()

    store.clear_secret("anthropic_api_key")

    assert store.read()["anthropic_api_key"] == {
        "configured": False,
        "source": "unset",
        "secret": True,
    }


def test_clear_shadows_a_keyring_delete_failure(tmp_path):
    backend = BrokenKeyring()
    store = SettingsStore(tmp_path / "settings.json", environment={}, keyring_backend=backend)
    store.update_secrets({"aws_session_token": "temporary"})

    store.clear_secret("aws_session_token")

    assert store.read()["aws_session_token"]["configured"] is False


def test_clear_shadows_an_inherited_environment_secret(tmp_path):
    store = SettingsStore(
        tmp_path / "settings.json",
        environment={"OPENAI_API_KEY": "inherited"},
        keyring_backend=BrokenKeyring(),
    )

    store.clear_secret("openai_api_key")
    snapshot = store.env_snapshot({"OPENAI_API_KEY": "inherited"})

    assert store.read()["openai_api_key"]["configured"] is False
    assert "OPENAI_API_KEY" not in snapshot

    restarted = SettingsStore(
        tmp_path / "settings.json",
        environment={"OPENAI_API_KEY": "inherited"},
        keyring_backend=BrokenKeyring(),
    )
    assert restarted.read()["openai_api_key"]["configured"] is False
    assert "OPENAI_API_KEY" not in restarted.env_snapshot({"OPENAI_API_KEY": "inherited"})


def test_env_snapshot_maps_all_setting_types_and_is_immutable(tmp_path):
    backend = FakeKeyring()
    store = SettingsStore(
        tmp_path / "settings.json",
        environment={"OPENAI_API_KEY": "environment-secret"},
        keyring_backend=backend,
    )
    store.update_nonsecrets(
        {
            "aws_profile": "development",
            "vllm_base_url": "http://vllm/v1",
        }
    )
    store.update_secrets({"aws_access_key_id": "access", "aws_secret_access_key": "secret"})

    snapshot = store.env_snapshot({"EXISTING": "preserved", "AWS_PROFILE": "base"})

    assert snapshot["EXISTING"] == "preserved"
    assert snapshot["AWS_PROFILE"] == "development"
    assert snapshot["OPENAI_API_KEY"] == "environment-secret"
    assert snapshot["AWS_ACCESS_KEY_ID"] == "access"
    assert snapshot["AWS_SECRET_ACCESS_KEY"] == "secret"
    assert snapshot["VLLM_BASE_URL"] == "http://vllm/v1"
    with pytest.raises(TypeError):
        snapshot["NEW"] = "value"  # type: ignore[index]


def test_updates_validate_names_and_require_explicit_secret_clear(tmp_path):
    store = SettingsStore(tmp_path / "settings.json", environment={}, keyring_backend=BrokenKeyring())

    with pytest.raises(KeyError):
        store.update_nonsecrets({"OPENAI_API_KEY": "wrong namespace"})
    with pytest.raises(KeyError):
        store.update_secrets({"unknown": "value"})
    with pytest.raises(ValueError, match="clear_secret"):
        store.update_secrets({"openai_api_key": ""})


def test_concurrent_nonsecret_updates_leave_valid_json(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path, environment={}, keyring_backend=BrokenKeyring())
    updates = [
        {"aws_profile": "profile"},
        {"aws_region": "region"},
        {"ollama_base_url": "ollama"},
        {"vllm_base_url": "vllm"},
    ]

    with ThreadPoolExecutor(max_workers=len(updates)) as executor:
        list(executor.map(store.update_nonsecrets, updates))

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "aws_profile": "profile",
        "aws_region": "region",
        "ollama_base_url": "ollama",
        "vllm_base_url": "vllm",
    }
