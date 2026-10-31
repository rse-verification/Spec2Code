from __future__ import annotations

import math


def assert_critic_result_shape(result: dict) -> None:
    required = {"tool", "success", "score", "summary", "metrics", "findings", "raw_output"}
    missing = required.difference(result.keys())
    assert not missing, f"Missing critic result keys: {sorted(missing)}"
    assert isinstance(result["tool"], str) and result["tool"]
    assert isinstance(result["success"], bool)
    assert isinstance(result["score"], (int, float)) and not isinstance(result["score"], bool)
    assert math.isfinite(result["score"]) and 0 <= result["score"] <= 1
    assert isinstance(result["summary"], str)
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["raw_output"], str)
    assert isinstance(result["findings"], list)
    for finding in result["findings"]:
        assert finding["severity"] in {"info", "warning", "error"}
        assert isinstance(finding["message"], str)
        assert isinstance(finding.get("location", {}), dict)
