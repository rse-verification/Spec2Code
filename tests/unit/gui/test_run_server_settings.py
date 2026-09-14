from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from spec2code.gui import run_server
from spec2code.gui.settings_store import SettingsStore


class _NoKeyring:
    priority = 0

    def get_password(self, service, name):
        return None

    def set_password(self, service, name, value):
        raise RuntimeError("disabled")

    def delete_password(self, service, name):
        return None


@pytest.mark.unit
def test_settings_updates_maps_semantic_payload_and_explicit_clears():
    payload = {
        "providers": {
            "openai": {"api_key": "openai-secret"},
            "anthropic": {"api_key": "", "clear_api_key": True},
            "aws_bedrock": {
                "profile": "  engineering  ",
                "region": " eu-west-2 ",
                "access_key_id": "access-id",
                "secret_access_key": "secret-key",
                "session_token": "session-token",
                "clear_session_token": True,
            },
            "ollama": {"base_url": "  http://ollama.test/v1  ", "api_key": "ollama-token"},
            "vllm": {"base_url": "   ", "api_key": "vllm-token", "clear_api_key": False},
        },
        "runtime_paths": {"input_root": "ignored"},
        "ignored": {"OPENAI_API_KEY": "must-not-map"},
    }

    nonsecrets, secrets, clear_secrets = run_server._settings_updates(payload)

    assert nonsecrets == {
        "aws_profile": "engineering",
        "aws_region": "eu-west-2",
        "ollama_base_url": "http://ollama.test/v1",
        "vllm_base_url": None,
    }
    assert secrets == {
        "openai_api_key": "openai-secret",
        "aws_access_key_id": "access-id",
        "aws_secret_access_key": "secret-key",
        "aws_session_token": "session-token",
        "ollama_api_key": "ollama-token",
        "vllm_api_key": "vllm-token",
    }
    assert clear_secrets == ["anthropic_api_key", "aws_session_token"]


@pytest.mark.unit
def test_settings_api_payload_has_redacted_public_shape(monkeypatch):
    class FakeStore:
        def read(self):
            return {
                "openai_api_key": {"configured": True, "source": "keyring", "secret": True},
                "anthropic_api_key": {"configured": False, "source": "unset", "secret": True},
                "aws_access_key_id": {"configured": True, "source": "memory", "secret": True},
                "aws_secret_access_key": {"configured": True, "source": "environment", "secret": True},
                "aws_session_token": {"configured": False, "source": "unset", "secret": True},
                "ollama_api_key": {"configured": False, "source": "unset", "secret": True},
                "vllm_api_key": {"configured": True, "source": "keyring", "secret": True},
                "aws_profile": {"configured": True, "source": "config", "secret": False, "value": "dev"},
                "aws_region": {"configured": True, "source": "config", "secret": False, "value": "us-east-1"},
                "ollama_base_url": {
                    "configured": True,
                    "source": "config",
                    "secret": False,
                    "value": "http://ollama.test/v1",
                },
                "case_studies_root": {
                    "configured": True,
                    "source": "config",
                    "secret": False,
                    "value": "case-root",
                },
            }

    monkeypatch.setattr(run_server, "SETTINGS_STORE", FakeStore())

    payload = run_server._settings_api_payload()

    assert payload == {
        "providers": {
            "openai": {
                "ready": True,
                "configured": True,
                "configured_secrets": {"api_key": True},
                "secret_sources": {"api_key": "keyring"},
            },
            "anthropic": {
                "ready": False,
                "configured": False,
                "configured_secrets": {"api_key": False},
                "secret_sources": {"api_key": "unset"},
            },
            "aws_bedrock": {
                "profile": "dev",
                "region": "us-east-1",
                "ready": True,
                "configured": True,
                "configured_secrets": {
                    "access_key_id": True,
                    "secret_access_key": True,
                    "session_token": False,
                },
            },
            "ollama": {
                "ready": True,
                "configured": True,
                "base_url": "http://ollama.test/v1",
                "configured_secrets": {"api_key": False},
            },
            "vllm": {
                "ready": True,
                "configured": True,
                "base_url": "http://localhost:8000/v1",
                "configured_secrets": {"api_key": True},
            },
        },
    }
    serialized = json.dumps(payload)
    assert "openai-secret" not in serialized
    assert "secret-key" not in serialized
    assert "value" not in payload["providers"]["openai"]


@pytest.mark.unit
def test_group_models_uses_provider_specs_and_preserves_unavailable_reason(monkeypatch):
    providers = {
        "local-ollama": {"type": "ollama"},
        "local-vllm": {"type": "openai-compatible", "api_key_env": "VLLM_API_KEY"},
        "custom-provider": {"type": "custom"},
    }
    specs = {
        "gpt-test": {"key_env": "OPENAI_API_KEY"},
        "claude-test": {"key_env": "ANTHROPIC_API_KEY"},
        "ollama/test": {"provider": "local-ollama"},
        "vllm/test": {"provider": "local-vllm"},
        "custom/test": {"provider": "custom-provider"},
    }
    monkeypatch.setattr(run_server.llms, "_available_specs", lambda: (providers, specs))

    grouped = run_server._group_models(
        [
            "test-llm-shutdown",
            "bedrock/example",
            "claude-test",
            "ollama/test",
            "vllm/test",
            "custom/test",
        ],
        {"gpt-test": "missing OPENAI_API_KEY"},
    )

    assert [group["id"] for group in grouped] == [
        "openai",
        "anthropic",
        "aws_bedrock",
        "ollama",
        "vllm",
        "mock",
        "custom-provider",
    ]
    assert [group["label"] for group in grouped[:6]] == [
        "OpenAI",
        "Anthropic",
        "AWS Bedrock",
        "Ollama",
        "vLLM",
        "Test models",
    ]
    openai_model = grouped[0]["models"][0]
    assert openai_model == {
        "name": "gpt-test",
        "ready": False,
        "reason": "missing OPENAI_API_KEY",
    }


@pytest.mark.unit
def test_models_cache_isolates_exact_credentials(monkeypatch):
    calls: list[dict[str, str]] = []

    def fake_compute(env):
        calls.append(dict(env))
        return {"models": [env["AWS_ACCESS_KEY_ID"]], "note": "computed"}

    monkeypatch.setattr(run_server, "_MODELS_CACHE", {"by_key": {}})
    monkeypatch.setattr(run_server.time, "time", lambda: 100.0)
    monkeypatch.setattr(run_server, "_compute_models_payload", fake_compute)
    first_env = {
        "AWS_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "first-access-id",
        "AWS_SECRET_ACCESS_KEY": "first-secret",
    }
    second_env = {
        "AWS_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "second-access-id",
        "AWS_SECRET_ACCESS_KEY": "second-secret",
    }

    first = run_server._models_payload_cached(first_env)
    second = run_server._models_payload_cached(second_env)

    assert first["models"] == ["first-access-id"]
    assert second["models"] == ["second-access-id"]
    assert calls == [first_env, second_env]


@pytest.mark.unit
def test_models_cache_honors_ttl_boundary(monkeypatch):
    clock = [100.0]
    calls = 0

    def fake_compute(_env):
        nonlocal calls
        calls += 1
        return {"models": [f"result-{calls}"], "note": "computed"}

    monkeypatch.setattr(run_server, "_MODELS_CACHE", {"by_key": {}})
    monkeypatch.setattr(run_server, "MODELS_CACHE_TTL_S", 60.0)
    monkeypatch.setattr(run_server.time, "time", lambda: clock[0])
    monkeypatch.setattr(run_server, "_compute_models_payload", fake_compute)
    env = {"AWS_REGION": "eu-west-1"}

    first = run_server._models_payload_cached(env)
    clock[0] = 159.9
    cached = run_server._models_payload_cached(env)
    clock[0] = 160.0
    expired = run_server._models_payload_cached(env)

    assert first["models"] == ["result-1"]
    assert cached["models"] == ["result-1"]
    assert expired["models"] == ["result-2"]
    assert calls == 2
    assert "served from cache" in cached["note"]
    assert "served from cache" not in expired["note"]


@pytest.mark.unit
def test_provider_error_redacts_submitted_secret(monkeypatch):
    submitted_secret = "sk-submitted-only-secret"

    class FakeModels:
        def list(self):
            raise RuntimeError(f"authentication failed for {submitted_secret}")

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url, timeout, max_retries):
            assert api_key == submitted_secret
            assert base_url == "https://api.openai.com/v1"
            assert timeout == 10.0
            assert max_retries == 0
            self.models = FakeModels()

    monkeypatch.setattr(run_server, "_effective_runtime_env", lambda: {"OPENAI_API_KEY": submitted_secret})
    monkeypatch.setattr(run_server.llms, "OpenAI", FakeOpenAI)

    result = run_server._test_provider_connection("openai")

    assert result == {"ok": False, "error": "authentication failed for ***"}
    assert submitted_secret not in json.dumps(result)


@pytest.mark.unit
def test_settings_http_api_saves_without_returning_secret(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json", environment={}, keyring_backend=_NoKeyring())
    monkeypatch.setattr(run_server, "SETTINGS_STORE", store)
    monkeypatch.setattr(run_server, "MODELS_CACHE_FILE", tmp_path / "models-cache.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), run_server._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urlopen(f"{base_url}/settings", timeout=3) as response:
            settings_html = response.read()
            assert b"Model providers" in settings_html
            assert b"Available models" in settings_html
            assert b"refreshAvailableModelsBtn" in settings_html
            assert b"Appearance" in settings_html
            assert b"Runtime paths" not in settings_html
            assert b"Save settings" not in settings_html

        body = json.dumps({
            "providers": {
                "openai": {"api_key": "never-return-this"},
                "aws_bedrock": {"profile": "bedrock", "region": "eu-west-1"},
                "vllm": {"base_url": "http://localhost:8000/v1", "api_key": "local-token"},
            },
        }).encode("utf-8")
        request = Request(
            f"{base_url}/api/settings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["ok"] is True
        assert payload["settings"]["providers"]["openai"]["ready"] is True
        assert "never-return-this" not in json.dumps(payload)
        assert store.env_snapshot({})["OPENAI_API_KEY"] == "never-return-this"
        assert store.env_snapshot({})["VLLM_API_KEY"] == "local-token"

        changed_endpoint = json.dumps({
            "providers": {"vllm": {"base_url": "http://localhost:9000/v1"}},
        }).encode("utf-8")
        request = Request(
            f"{base_url}/api/settings",
            data=changed_endpoint,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=3)
        assert exc_info.value.code == 400
        assert store.env_snapshot({})["VLLM_API_KEY"] == "local-token"

        changed_endpoint = json.dumps({
            "providers": {"vllm": {"base_url": "http://localhost:9000/v1", "clear_api_key": True}},
        }).encode("utf-8")
        request = Request(
            f"{base_url}/api/settings",
            data=changed_endpoint,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3):
            pass
        assert "VLLM_API_KEY" not in store.env_snapshot({})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
