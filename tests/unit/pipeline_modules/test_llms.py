from types import SimpleNamespace

import pytest

from spec2code.pipeline_modules import llms


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[], model_dump=lambda: {})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("token_setting", "expected_parameter"),
    [
        ({"max_completion_tokens": 2048}, "max_completion_tokens"),
        ({"max_tokens": 1024}, "max_tokens"),
    ],
)
def test_yaml_token_limit_is_forwarded_with_the_configured_openai_parameter(
    monkeypatch, token_setting, expected_parameter
):
    completions = _FakeCompletions()
    provider = llms.OpenAICompatibleProvider.__new__(llms.OpenAICompatibleProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model_spec = {
        "provider": "openai_default",
        "model": "test-model",
        **token_setting,
    }

    monkeypatch.setattr(
        llms,
        "_load_yaml_model_config",
        lambda: ({"openai_default": {"type": "openai-compatible"}}, {"test-model": model_spec}),
    )
    monkeypatch.setattr(llms, "_build_provider", lambda provider_spec: provider)

    llms.build_model("test-model").prompt("hello")

    assert completions.kwargs[expected_parameter] == next(iter(token_setting.values()))
    unexpected_parameter = "max_tokens" if expected_parameter == "max_completion_tokens" else "max_completion_tokens"
    assert unexpected_parameter not in completions.kwargs


@pytest.mark.unit
def test_discovered_openai_model_name_builds_with_openai_compatible_provider(monkeypatch):
    created = {}

    class FakeProvider:
        def __init__(self, *, base_url, api_key):
            created.update(base_url=base_url, api_key=api_key)

        def generate(self, **kwargs):
            return llms._SimpleLLMResponse("ok")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llms, "OpenAICompatibleProvider", FakeProvider)

    model = llms.build_model("openai/discovered-model")

    assert model.name == "openai/discovered-model"
    assert model.model_id == "discovered-model"
    assert model._default_max_completion_tokens == 4096
    assert model._default_max_tokens is None
    assert created == {"base_url": "https://api.openai.com/v1", "api_key": "test-key"}


@pytest.mark.unit
def test_initialize_llms_keeps_discovered_provider_prefixed_models(monkeypatch):
    from spec2code.pipeline_modules import experiment_parameters

    sentinel = object()
    monkeypatch.setattr(experiment_parameters.llms, "build_models", lambda names: {name: sentinel for name in names})
    monkeypatch.setattr(experiment_parameters.llms_test, "build_mock_models", lambda: {})

    models = experiment_parameters.initialize_llms(["openai/gpt-5.4-mini"])

    assert models == {"openai/gpt-5.4-mini": sentinel}


@pytest.mark.parametrize("model_id", ["o1", "o3-mini", "o4-mini", "gpt-5", "gpt-5.4-mini"])
def test_reasoning_models_omit_temperature_and_use_completion_token_limit(monkeypatch, model_id):
    completions = _FakeCompletions()
    monkeypatch.setattr(llms, "OpenAI", lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    provider = llms.OpenAICompatibleProvider(base_url="https://api.openai.com/v1", api_key="test")
    provider.generate(model_id=model_id, prompt="code", temperature=0.7, max_tokens=8192)
    assert "temperature" not in completions.kwargs
    assert "max_tokens" not in completions.kwargs
    assert completions.kwargs["max_completion_tokens"] == 8192


@pytest.mark.parametrize("model_id", ["gpt-5-pro", "o1-pro", "gpt-5.1-codex"])
def test_responses_only_models_use_responses_api(monkeypatch, model_id):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="generated code", model_dump=lambda: {})

    monkeypatch.setattr(llms, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create)))
    provider = llms.OpenAICompatibleProvider(base_url="https://api.openai.com/v1", api_key="test")
    result = provider.generate(model_id=model_id, prompt="code", temperature=0.7, max_completion_tokens=4096)
    assert result.text() == "generated code"
    assert calls == [{"model": model_id, "input": "code", "max_output_tokens": 4096}]


def test_keyless_vllm_discovered_model_can_generate(monkeypatch):
    calls = []
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    monkeypatch.setenv("VLLM_BASE_URL", "http://local.test/v1")
    completions = _FakeCompletions()
    monkeypatch.setattr(llms, "OpenAI", lambda **kw: calls.append(kw) or SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    model = llms.build_model("vllm/org/model-name")
    model.prompt("code")
    assert calls == [{"base_url": "http://local.test/v1", "api_key": "not-required"}]
    assert completions.kwargs["model"] == "org/model-name"
    assert completions.kwargs["max_tokens"] == 4096


def test_parameter_fallback_is_bounded_and_preserves_prompt(monkeypatch):
    class Unsupported(Exception):
        status_code = 400

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise Unsupported("temperature is not supported")
        if "max_completion_tokens" in kwargs:
            raise Unsupported("Unsupported parameter: max_completion_tokens")
        return SimpleNamespace(choices=[], model_dump=lambda: {})

    monkeypatch.setattr(llms, "OpenAI", lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    provider = llms.OpenAICompatibleProvider(base_url="http://local.test/v1", api_key="test")
    provider.generate(model_id="custom", prompt="code", temperature=0.7, max_completion_tokens=4096)
    assert len(calls) == 3
    assert calls[-1] == {"model": "custom", "messages": [{"role": "user", "content": "code"}], "max_tokens": 4096}


def test_authentication_error_is_not_retried_as_parameter_error():
    class AuthError(Exception):
        status_code = 401

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise AuthError("unsupported temperature is not the problem")

    with pytest.raises(AuthError):
        llms._request_with_optional_temperature(create, {"temperature": 0.7})
    assert len(calls) == 1


def test_bedrock_access_error_preserved_without_invoke_fallback():
    class AccessError(Exception):
        response = {"Error": {"Code": "AccessDeniedException"}}

    def converse(**kwargs):
        raise AccessError("not authorized for this profile")

    provider = llms.BedrockProvider.__new__(llms.BedrockProvider)
    provider._client = SimpleNamespace(converse=converse)
    with pytest.raises(AccessError, match="not authorized"):
        provider.generate(model_id="anthropic.claude", prompt="code", temperature=0.7)


@pytest.mark.parametrize("name", ["openai/text-embedding-3-small", "openai/gpt-image-1", "openai/whisper-1", "ollama/nomic-embed-text", "vllm/org/reranker"])
def test_non_generation_models_rejected_before_client_creation(name):
    with pytest.raises(ValueError, match="Cannot generate code"):
        llms.build_model(name)
