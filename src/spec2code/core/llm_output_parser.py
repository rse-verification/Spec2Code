from __future__ import annotations

import json
import re
from typing import Any, Dict


class ModelOutputError(ValueError):
    """A completed model response whose artifacts cannot be used by the pipeline."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


def _text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        item["text"] for item in content
        if isinstance(item, dict) and item.get("type") in {None, "text", "output_text"}
        and isinstance(item.get("text"), str)
    )


def _get_model_text(output_llm: Any) -> str:
    fallback = ""
    try:
        text = output_llm.text()
        if isinstance(text, str):
            fallback = text
            if text.strip():
                return text
    except Exception:
        pass

    # Some adapters expose only the provider response. Ignore non-text blocks
    # (e.g. thinking/tool calls), and retain every text block, not just the first.
    try:
        data = output_llm.json()
        if not isinstance(data, dict):
            return fallback
        response = data.get("response", data)
        if isinstance(response, dict):
            for key in ("text", "output_text", "content"):
                text = _text_blocks(response.get(key))
                if text.strip():
                    return text
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                text = _text_blocks(message.get("content"))
                if text.strip():
                    return text
            output = response.get("output")
            if isinstance(output, dict):  # Bedrock Converse
                return _text_blocks((output.get("message") or {}).get("content"))
            if isinstance(output, list):  # OpenAI Responses
                return "".join(
                    _text_blocks(item.get("content")) for item in output
                    if isinstance(item, dict) and item.get("type") == "message"
                )
        return _text_blocks(data.get("text")) or fallback
    except Exception:
        return fallback


def _unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key '{key}' in model output.")
        result[key] = value
    return result


def _parse_artifacts(text: str) -> Dict[str, Any]:
    # Match full delimiter lines so C strings mentioning END_C are not truncated.
    markers = list(re.finditer(r"(?m)^[ \t]*(BEGIN|END)_(C|H)[ \t]*$", text))
    if markers:
        names = [f"{m[1]}_{m[2]}" for m in markers]
        if names not in (["BEGIN_C", "END_C", "BEGIN_H", "END_H"], ["BEGIN_H", "END_H", "BEGIN_C", "END_C"]):
            raise ValueError("Expected one complete BEGIN_C/END_C block and one BEGIN_H/END_H block.")
        return {markers[i][2].lower(): text[markers[i].end():markers[i + 1].start()].strip() for i in (0, 2)}

    candidate = text.strip()
    # A single JSON fence may have explanatory prose around it. Never guess
    # between multiple alternatives or silently repair truncated JSON/C strings.
    fences = re.findall(r"(?ms)^[ \t]*```(?:json)?[ \t]*\n(.*?)^[ \t]*```[ \t]*$", candidate)
    if len(fences) > 1:
        raise ValueError("Multiple JSON blocks in model output; return one implementation.")
    if fences:
        candidate = fences[0]
    try:
        obj = json.loads(candidate, object_pairs_hook=_unique_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model output must contain complete sentinel blocks or valid JSON: {exc.msg}.") from exc
    if not isinstance(obj, dict):
        raise ValueError("Model output JSON must be an object containing 'c' and 'h'.")
    return obj


def extract_llm_response_info(output_llm: Any) -> Dict[str, Any]:
    raw_text = _get_model_text(output_llm)
    try:
        if not raw_text.strip():
            raise ValueError("Model returned empty text output.")
        obj = _parse_artifacts(raw_text.replace("\r\n", "\n").replace("\r", "\n"))
        for key in ("c", "h"):
            if key not in obj:
                raise ValueError(f"Model output is missing '{key}'. Both C and header artifacts are required.")
            if not isinstance(obj[key], str) or not obj[key].strip():
                raise ValueError(f"Model output field '{key}' must be a non-empty string.")
        return {
            "raw_output": raw_text,
            "code": obj["c"].strip(),
            "generated_header": obj["h"].strip(),
            "exact_model_used": obj.get("model") if isinstance(obj.get("model"), str) and obj["model"].strip() else "unknown",
        }
    except ValueError as exc:
        raise ModelOutputError(str(exc), raw_text) from exc
