from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol, TypedDict
from typing_extensions import NotRequired, Required

Severity = Literal["info", "warning", "error"]


class Finding(TypedDict):
    tool: str
    severity: Severity
    message: str
    location: Optional[dict]
    rule: Optional[str]


class CriticResult(TypedDict):
    tool: str
    success: bool
    score: float 
    summary: str
    metrics: Dict[str, Any]
    findings: List[Finding]
    raw_output: str
    elapsed_time_s: NotRequired[float]


class CriticInput(TypedDict, total=False):
    c_file_path: Required[str]
    timeout: int
    extra_args: List[str]
    context: Dict[str, Any]  # e.g. include_dirs, compiled_output_path, remove_compiled


class Critic(Protocol):
    name: str

    def run(self, inp: CriticInput) -> CriticResult:
        ...
