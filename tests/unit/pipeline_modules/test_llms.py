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
