from __future__ import annotations

from typing import Any, List


class DummyCritic:
    name = "dummy"

    def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "success": True,
            "score": 1.0,
            "summary": "ok",
            "metrics": {},
            "findings": [],
            "raw_output": "",
        }


def fake_build_critics(names: List[str]) -> List[str]:
    return [f"critic:{name}" for name in names]
