from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


CONFIG_PATH_ENV = "SPEC2CODE_GUI_SETTINGS_PATH"
KEYRING_SERVICE = "spec2code.gui"
_CLEARED_SECRETS_KEY = "_cleared_secrets"

NONSECRET_FIELDS = MappingProxyType(
    {
        "aws_profile": "AWS_PROFILE",
        "aws_region": "AWS_REGION",
        "ollama_base_url": "OLLAMA_BASE_URL",
        "vllm_base_url": "VLLM_BASE_URL",
    }
)

SECRET_FIELDS = MappingProxyType(
    {
        "openai_api_key": "OPENAI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "aws_access_key_id": "AWS_ACCESS_KEY_ID",
        "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
        "aws_session_token": "AWS_SESSION_TOKEN",
        "ollama_api_key": "OLLAMA_API_KEY",
        "vllm_api_key": "VLLM_API_KEY",
    }
)

_BOUND_ENDPOINT_SECRETS = {
    "ollama_base_url": ("ollama_api_key", "Ollama", "http://localhost:11434/v1"),
    "vllm_base_url": ("vllm_api_key", "vLLM", "http://localhost:8000/v1"),
}


def _default_config_path(environment: Mapping[str, str]) -> Path:
    override = environment.get(CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()

    if os.name == "nt" and environment.get("APPDATA"):
        root = Path(environment["APPDATA"])
    elif environment.get("XDG_CONFIG_HOME"):
        root = Path(environment["XDG_CONFIG_HOME"])
    else:
        root = Path.home() / ".config"
    return root / "spec2code" / "gui_settings.json"


def _load_keyring_backend() -> Any | None:
    try:
        keyring = importlib.import_module("keyring")
        backend = keyring.get_keyring()
        if float(backend.priority) <= 0:
            return None
        return backend
    except Exception:
        return None


class SettingsStore:
    """Thread-safe storage for GUI settings and runtime credentials."""

    def __init__(
        self,
        config_path: str | os.PathLike[str] | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        keyring_backend: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._environment = dict(os.environ if environment is None else environment)
        self.config_path = Path(config_path).expanduser() if config_path is not None else _default_config_path(
            self._environment
        )
        self._keyring = keyring_backend if keyring_backend is not None else _load_keyring_backend()
        self._memory_secrets: dict[str, str] = {}
        self._cleared_secrets: set[str] = self._read_clear_tombstones()

    def read(self) -> dict[str, dict[str, object]]:
        """Return values for non-secrets and redacted status metadata for secrets."""
        with self._lock:
            stored = self._read_config()
            result: dict[str, dict[str, object]] = {}
            for name, env_name in NONSECRET_FIELDS.items():
                if name in stored and stored[name] != "":
                    value = stored[name]
                    source = "config"
                elif env_name in self._environment and self._environment[env_name] != "":
                    value = self._environment[env_name]
                    source = "environment"
                else:
                    value = None
                    source = "unset"
                result[name] = {
                    "configured": value is not None,
                    "source": source,
                    "secret": False,
                    "value": value,
                }

            for name, env_name in SECRET_FIELDS.items():
                _, source = self._secret_value_and_source(name, env_name)
                result[name] = {
                    "configured": source != "unset",
                    "source": source,
                    "secret": True,
                }
            return result

    def update_nonsecrets(self, values: Mapping[str, str | None]) -> None:
        """Persist non-secret values; None or an empty string removes a value."""
        self.update(nonsecrets=values)

    def update_secrets(self, values: Mapping[str, str]) -> None:
        """Store secrets in keyring, falling back to process memory on any failure."""
        self.update(secrets=values)

    def clear_secret(self, name: str) -> None:
        """Clear a stored secret without treating an empty value as a credential."""
        self.update(clear_secrets=[name])

    def update(
        self,
        *,
        nonsecrets: Mapping[str, str | None] | None = None,
        secrets: Mapping[str, str] | None = None,
        clear_secrets: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> None:
        """Apply one settings update under a single lock."""
        nonsecrets = dict(nonsecrets or {})
        secrets = dict(secrets or {})
        clear_names = set(clear_secrets or [])
        self._validate_names(nonsecrets, NONSECRET_FIELDS, "non-secret")
        self._validate_names(secrets, SECRET_FIELDS, "secret")
        self._validate_names({name: None for name in clear_names}, SECRET_FIELDS, "secret")
        for name, value in nonsecrets.items():
            if value is not None and not isinstance(value, str):
                raise TypeError(f"Setting '{name}' must be a string or None")
        for name, value in secrets.items():
            if not isinstance(value, str):
                raise TypeError(f"Secret '{name}' must be a string")
            if value == "":
                raise ValueError(f"Use clear_secret() to clear '{name}'")

        with self._lock:
            stored = self._read_config()
            for endpoint_name, (secret_name, provider_label, default_url) in _BOUND_ENDPOINT_SECRETS.items():
                if endpoint_name not in nonsecrets:
                    continue
                endpoint_env = NONSECRET_FIELDS[endpoint_name]
                old_endpoint = stored.get(endpoint_name) or self._environment.get(endpoint_env) or default_url
                new_endpoint = nonsecrets[endpoint_name] or default_url
                secret_env = SECRET_FIELDS[secret_name]
                existing_secret, _ = self._secret_value_and_source(secret_name, secret_env)
                if (
                    new_endpoint != old_endpoint
                    and existing_secret
                    and secret_name not in secrets
                    and secret_name not in clear_names
                ):
                    raise ValueError(
                        f"Changing the {provider_label} endpoint requires re-entering or explicitly clearing its token."
                    )

            for name, value in nonsecrets.items():
                if value is None or value == "":
                    stored.pop(name, None)
                else:
                    stored[name] = value

            next_tombstones = set(self._cleared_secrets)
            next_tombstones.update(clear_names)
            next_tombstones.difference_update(secrets)
            if nonsecrets or next_tombstones != self._cleared_secrets:
                self._write_config(stored, cleared_secrets=next_tombstones)
            self._cleared_secrets = next_tombstones

            for name in clear_names:
                self._memory_secrets.pop(name, None)
                if self._keyring is not None:
                    try:
                        self._keyring.delete_password(KEYRING_SERVICE, name)
                    except Exception:
                        pass

            for name, value in secrets.items():
                persisted = False
                if self._keyring is not None:
                    try:
                        self._keyring.set_password(KEYRING_SERVICE, name, value)
                        persisted = True
                    except Exception:
                        pass
                if persisted:
                    self._memory_secrets.pop(name, None)
                else:
                    self._memory_secrets[name] = value

    def env_snapshot(self, base_env: Mapping[str, str]) -> Mapping[str, str]:
        """Return an immutable base environment overlaid with effective GUI settings."""
        with self._lock:
            snapshot = dict(base_env)
            stored = self._read_config()
            for name, env_name in NONSECRET_FIELDS.items():
                value = stored.get(name) or self._environment.get(env_name)
                if value:
                    snapshot[env_name] = value
            for name, env_name in SECRET_FIELDS.items():
                value, _ = self._secret_value_and_source(name, env_name)
                if value is not None:
                    snapshot[env_name] = value
                elif name in self._cleared_secrets:
                    snapshot.pop(env_name, None)
            return MappingProxyType(snapshot)

    @staticmethod
    def _validate_names(values: Mapping[str, object], allowed: Mapping[str, str], kind: str) -> None:
        unknown = sorted(set(values) - set(allowed))
        if unknown:
            raise KeyError(f"Unknown {kind} setting(s): {', '.join(unknown)}")

    def _secret_value_and_source(self, name: str, env_name: str) -> tuple[str | None, str]:
        if name in self._cleared_secrets:
            return None, "unset"
        if name in self._memory_secrets:
            return self._memory_secrets[name], "memory"
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(KEYRING_SERVICE, name)
                if value:
                    return value, "keyring"
            except Exception:
                pass
        environment_value = self._environment.get(env_name)
        if environment_value:
            return environment_value, "environment"
        return None, "unset"

    def _read_config(self) -> dict[str, str]:
        data = self._read_config_document()
        return {
            name: value
            for name, value in data.items()
            if name in NONSECRET_FIELDS and isinstance(value, str) and value != ""
        }

    def _read_clear_tombstones(self) -> set[str]:
        raw = self._read_config_document().get(_CLEARED_SECRETS_KEY, [])
        if not isinstance(raw, list):
            return set()
        return {str(name) for name in raw if str(name) in SECRET_FIELDS}

    def _read_config_document(self) -> dict[str, Any]:
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write_config(self, values: Mapping[str, str], *, cleared_secrets: set[str] | None = None) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.config_path.parent,
                prefix=f".{self.config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                document: dict[str, object] = dict(sorted(values.items()))
                tombstones = self._cleared_secrets if cleared_secrets is None else cleared_secrets
                if tombstones:
                    document[_CLEARED_SECRETS_KEY] = sorted(tombstones)
                json.dump(document, handle, indent=2)
                handle.write("\n")
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.config_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
