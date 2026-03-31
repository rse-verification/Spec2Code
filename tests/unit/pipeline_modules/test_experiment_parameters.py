from __future__ import annotations

import pytest

from spec2code.pipeline_modules import experiment_parameters


@pytest.mark.unit
def test_initialize_llms_keeps_dynamic_bedrock_names(monkeypatch):
    monkeypatch.setattr(experiment_parameters.llms, "available_model_names", lambda: ["gpt-4o-mini"])
    monkeypatch.setattr(
        experiment_parameters.llms,
        "build_models",
        lambda names: {n: object() for n in names},
    )
    monkeypatch.setattr(experiment_parameters.llms_test, "build_mock_models", lambda: {})

    models = experiment_parameters.initialize_llms(
        [
            "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
            "bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc",
            "unknown-model",
        ]
    )

    assert "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0" in models
    assert "bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc" in models
    assert "unknown-model" not in models


@pytest.mark.unit
def test_ensure_supported_llms_accepts_bedrock_slash_and_colon():
    experiment_parameters.ensure_supported_llms([
        "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
        "bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0",
        "bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc",
    ])


@pytest.mark.unit
def test_ensure_supported_llms_rejects_empty_bedrock_name():
    with pytest.raises(ValueError):
        experiment_parameters.ensure_supported_llms(["bedrock/"])
