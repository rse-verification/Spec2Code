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
