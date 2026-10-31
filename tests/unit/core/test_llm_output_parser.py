import json
from types import SimpleNamespace

import pytest

from spec2code.core.llm_output_parser import ModelOutputError, extract_llm_response_info

pytestmark = pytest.mark.unit

C = 'const char *s = "END_C";\nint step(void) { return 42; }'
H = "int step(void);"
JSON = json.dumps({"c": C, "h": H, "model": "fixture-model"})
SENTINELS = f"BEGIN_C\n{C}\nEND_C\nBEGIN_H\n{H}\nEND_H"


@pytest.mark.parametrize("text", [
    JSON, f"```json\n{JSON}\n```", f"Here is the implementation:\n```json\n{JSON}\n```\nDone.",
    SENTINELS, SENTINELS.replace("\n", "\r\n"), SENTINELS.replace("\n", "\r"),
    f"Explanation\n{SENTINELS}\nDone.", f"BEGIN_H\n{H}\nEND_H\nBEGIN_C\n{C}\nEND_C",
])
def test_extracts_complete_artifacts_without_truncating_c_strings(text):
    result = extract_llm_response_info(SimpleNamespace(text=lambda: text))
    assert result["code"] == C
    assert result["generated_header"] == H
    assert result["raw_output"] == text
    if text.startswith("{"):
        assert result["exact_model_used"] == "fixture-model"


@pytest.mark.parametrize(("text", "error"), [
    ("", "empty text"), (" \n\t", "empty text"), ("not code", "valid JSON"),
    (JSON[:-1], "valid JSON"), ("[]", "must be an object"), ("null", "must be an object"),
    ('{"c": "code"}', "missing 'h'"), ('{"h": "header"}', "missing 'c'"),
    ('{"c": 2, "h": "header"}', "'c' must be a non-empty string"),
    ('{"c": "code", "h": []}', "'h' must be a non-empty string"),
    ('{"c": "", "h": "header"}', "'c' must be a non-empty string"),
    ('{"c": "code", "h": null}', "'h' must be a non-empty string"),
    ('{"c":"one", "c":"two", "h":"header"}', "Duplicate JSON key"),
    (SENTINELS.replace("END_H", ""), "one complete"),
    (SENTINELS + "\n" + SENTINELS, "one complete"),
    (f"BEGIN_C\n \nEND_C\nBEGIN_H\n{H}\nEND_H", "'c' must be a non-empty string"),
    (f"```json\n{JSON}\n```\n```json\n{JSON}\n```", "Multiple JSON blocks"),
])
def test_rejects_invalid_or_ambiguous_responses_and_preserves_evidence(text, error):
    with pytest.raises(ModelOutputError, match=error) as caught:
        extract_llm_response_info(SimpleNamespace(text=lambda: text))
    assert caught.value.raw_output == text


@pytest.mark.parametrize("payload", [
    {"text": JSON},
    {"response": {"content": [{"type": "thinking", "thinking": "ignore"}, {"type": "text", "text": JSON[:10]}, {"type": "text", "text": JSON[10:]}]}},
    {"response": {"choices": [{"message": {"content": JSON}}]}},
    {"response": {"output": {"message": {"content": [{"text": JSON}]}}}},
    {"response": {"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": JSON}]}]}},
])
def test_adapter_json_fallbacks_read_all_text_and_ignore_nontext(payload):
    result = extract_llm_response_info(SimpleNamespace(json=lambda: payload))
    assert result["code"] == C
    assert result["generated_header"] == H


def test_text_accessor_takes_precedence_over_provider_metadata():
    response = SimpleNamespace(text=lambda: JSON, json=lambda: {"text": "not code"})
    assert extract_llm_response_info(response)["code"] == C


@pytest.mark.parametrize("payload", [[], {"response": {"content": [{"type": "tool_use"}]}}, {"response": {"choices": [None]}}])
def test_missing_text_in_provider_payload_is_a_parse_error(payload):
    with pytest.raises(ModelOutputError, match="empty text"):
        extract_llm_response_info(SimpleNamespace(json=lambda: payload))
