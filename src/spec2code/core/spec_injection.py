from __future__ import annotations

import re
from typing import List

_PROTOTYPE_RX = re.compile(
    r"(?m)^\s*(?:extern\s+)?(?:static\s+)?[A-Za-z_]\w*(?:\s+[*\w]+)*\s+[A-Za-z_]\w*\s*\([^;]*\)\s*;\s*$"
)


def _first_significant_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _remove_header_include(lines: List[str], header_name: str) -> List[str]:
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("#include") and header_name in s:
            continue
        out.append(line)
    return out


def _inject_module_state_constants(c_code: str, header_name: str, header_content: str) -> str:
    if not header_content.strip():
        return c_code

    signature = _first_significant_line(header_content)
    if signature and signature in c_code:
        return c_code

    lines = c_code.splitlines()
    lines = _remove_header_include(lines, header_name)

    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#include"):
            insert_at = i + 1
        elif insert_at > 0:
            break

    injected = []
    injected.extend(lines[:insert_at])
    if insert_at > 0 and (injected and injected[-1].strip()):
        injected.append("")
    injected.append(header_content.rstrip())
    injected.append("")
    injected.extend(lines[insert_at:])
    return "\n".join(injected).strip("\n") + "\n"


def extract_signature_from_interface(*, interface_text: str) -> str:
    if not isinstance(interface_text, str) or not interface_text.strip():
        raise ValueError("Interface text is empty; cannot extract function signature.")

    matches = [m.group(0).strip() for m in _PROTOTYPE_RX.finditer(interface_text)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one function prototype in interface; found {len(matches)}.")
    return matches[0]


def _signature_to_definition_regex(signature: str) -> re.Pattern:
    sig = (signature or "").strip()
    if not sig.endswith(";"):
        raise ValueError("Extracted signature must end with ';'")
    sig = sig[:-1].strip()

    esc = re.escape(sig).replace(r"\ ", r"\s+")
    return re.compile(rf"(?m)^(?P<def>(?:static\s+)?{esc})\s*\{{")


def inject_formal_spec_before_definition(*, c_code: str, interface_text: str, formal_spec: str) -> str:
    if not isinstance(c_code, str) or not c_code.strip():
        raise ValueError("Empty C code from LLM.")
    if not isinstance(formal_spec, str) or not formal_spec.strip():
        raise ValueError("Empty formal spec.")

    signature = extract_signature_from_interface(interface_text=interface_text)
    rx = _signature_to_definition_regex(signature)
    matches = list(rx.finditer(c_code))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one function definition match for extracted signature; found {len(matches)}."
        )

    m = matches[0]
    insert_at = m.start("def")
    return c_code[:insert_at] + formal_spec.strip() + "\n" + c_code[insert_at:]