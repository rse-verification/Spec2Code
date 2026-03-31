from __future__ import annotations


def assert_critic_result_shape(result: dict) -> None:
    required = {"tool", "success", "score", "summary", "metrics", "findings", "raw_output"}
    missing = required.difference(result.keys())
    assert not missing, f"Missing critic result keys: {sorted(missing)}"
