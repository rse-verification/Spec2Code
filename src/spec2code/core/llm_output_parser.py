from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

_JSON_BLOCK_RX = re.compile(r"\{.*\}", re.DOTALL)


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _find_key(text: str, key: str) -> int:
    m = re.search(rf'"{re.escape(key)}"\s*:', text)
    return m.start() if m else -1


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    return i


def _parse_loose_string(text: str, i: int) -> Tuple[str, int]:
    n = len(text)
    if i >= n or text[i] not in ('"', "'"):
        raise ValueError("Expected string opening quote.")
    quote = text[i]
    i += 1

    out_chars = []
    while i < n:
        ch = text[i]

        if ch == quote:
            return "".join(out_chars), i + 1

        if ch == "\\":
            i += 1
            if i >= n:
                break
            esc = text[i]
            if esc == "n":
                out_chars.append("\n")
            elif esc == "t":
                out_chars.append("\t")
            elif esc == "r":
                out_chars.append("\r")
            elif esc == "\\":
                out_chars.append("\\")
            elif esc == '"':
                out_chars.append('"')
            elif esc == "'":
                out_chars.append("'")
            else:
                out_chars.append(esc)
            i += 1
            continue

        if ch == "\n":
            out_chars.append("\n")
            i += 1
            continue
        if ch == "\t":
            out_chars.append("\t")
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue

        out_chars.append(ch)
        i += 1

    raise ValueError("Unterminated string while parsing model output.")


def _extract_field(text: str, key: str) -> str:
    pos = _find_key(text, key)
    if pos < 0:
        raise ValueError(f"Missing key '{key}' in model output.")
    colon = text.find(":", pos)
    if colon < 0:
        raise ValueError(f"Malformed key '{key}' (no colon).")
    j = _skip_ws(text, colon + 1)
    val, _ = _parse_loose_string(text, j)
    return val


def _parse_jsonish_object(raw: str) -> Dict[str, Any]:
    raw = _strip_code_fences(raw)

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "c" in obj and "h" in obj:
            return obj
    except Exception:
        pass

    c = _extract_field(raw, "c")
    h = _extract_field(raw, "h")

    model = None
    try:
        model = _extract_field(raw, "model")
    except Exception:
        model = None

    out: Dict[str, Any] = {"c": c, "h": h}
    if model is not None:
        out["model"] = model
    return out


def _repair_json_with_raw_newlines(s: str) -> str:
    out = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            else:
                if ch == '\\':
                    out.append(ch)
                    esc = True
                elif ch == '"':
                    out.append(ch)
                    in_str = False
                elif ch == '\n':
                    out.append('\\n')
                elif ch == '\r':
                    continue
                else:
                    out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    return "".join(out)


def _extract_between(text: str, start: str, end: str) -> Optional[str]:
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    if j < 0:
        return None
    return text[i:j].strip("\n")


def _get_model_text(output_llm: Any) -> str:
    try:
        t = output_llm.text()
        if isinstance(t, str) and t.strip():
            return t
    except Exception:
        pass

    try:
        j = output_llm.json()
        if isinstance(j, dict):
            resp = j.get("response")
            if isinstance(resp, dict):
                content = resp.get("content")
                if isinstance(content, list) and content:
                    t = content[0].get("text")
                    if isinstance(t, str) and t.strip():
                        return t
            t = j.get("text")
            if isinstance(t, str) and t.strip():
                return t
    except Exception:
        pass

    return ""


def extract_llm_response_info(output_llm: Any) -> Dict[str, Any]:
    raw_text = _get_model_text(output_llm)
    if not raw_text.strip():
        raise ValueError("Model returned empty text output.")

    c = _extract_between(raw_text, "BEGIN_C\n", "\nEND_C")
    h = _extract_between(raw_text, "BEGIN_H\n", "\nEND_H")
    if c is not None and h is not None:
        return {
            "raw_output": raw_text,
            "code": c.strip(),
            "generated_header": h.strip(),
            "exact_model_used": "unknown",
        }

    try:
        obj = json.loads(raw_text)
        return {
            "raw_output": raw_text,
            "code": (obj.get("c") or "").strip(),
            "generated_header": (obj.get("h") or "").strip(),
            "exact_model_used": obj.get("model", "unknown"),
        }
    except Exception as e:
        raise ValueError(
            "Model output was neither sentinel-block format nor valid JSON. "
            f"First 200 chars:\n{raw_text[:200]}"
        ) from e