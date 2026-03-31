from __future__ import annotations

from typing import Any, Dict, List

import pytest

from spec2code.pipeline_modules.critics import critics_runner
from spec2code.pipeline_modules.critics.critics_compile import CompileCritic
from spec2code.pipeline_modules.critics.critics_cppcheck_misra import CppcheckMisraCritic
from spec2code.pipeline_modules.critics.critics_framac_wp import FramaCWPCritic
from spec2code.pipeline_modules.critics.critics_vernfr import VernfrCritic


class _FakeCritic:
    def __init__(self, name: str, success: bool, score: float):
        self.name = name
        self._success = success
        self._score = score
        self.calls: List[Dict[str, Any]] = []

    def run(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(inp)
        return {
            "tool": self.name,
            "success": self._success,
            "score": self._score,
            "summary": "ok" if self._success else "fail",
            "metrics": {},
            "findings": [],
            "raw_output": "",
        }


@pytest.mark.unit
@pytest.mark.critics
def test_fmt_duration_formats_seconds_minutes_hours():
    assert critics_runner._fmt_duration(5) == "5s"
    assert critics_runner._fmt_duration(62) == "1m02s"
    assert critics_runner._fmt_duration(3661) == "1h01m01s"
    assert critics_runner._fmt_duration(-4) == "0s"


@pytest.mark.unit
@pytest.mark.critics
def test_build_default_critics_respects_framac_options():
    critics = critics_runner.build_default_critics(
        solvers=["Alt-Ergo"],
        timeout=88,
        critic_options={
            "framac-wp": {
                "wp_timeout": 9,
                "smoke_tests": True,
                "model": "typed",
                "rte": False,
            }
        },
    )

    assert len(critics) == 5
    assert isinstance(critics[0], CompileCritic)
    assert isinstance(critics[1], CppcheckMisraCritic)
    assert isinstance(critics[2], FramaCWPCritic)
    assert isinstance(critics[3], VernfrCritic)
    assert isinstance(critics[4], VernfrCritic)

    framac = critics[2]
    assert framac.wp_timeout == 9
    assert framac.smoke_tests is True
    assert framac.model == "typed"
    assert framac.rte is False
    assert framac.timeout == 88


@pytest.mark.unit
@pytest.mark.critics
def test_build_critics_from_names_unknown_raises():
    with pytest.raises(ValueError, match="Unknown critic name"):
        critics_runner.build_critics_from_names(
            names=["does-not-exist"],
            solvers=["Alt-Ergo"],
        )


@pytest.mark.unit
@pytest.mark.critics
def test_build_critics_from_names_applies_per_critic_options(tmp_path):
    custom_rules = str(tmp_path / "rules.txt")
    custom_script = str(tmp_path / "vernfr.sh")

    critics = critics_runner.build_critics_from_names(
        names=["cppcheck-misra", "framac-wp", "vernfr-control-flow"],
        solvers=["Alt-Ergo"],
        timeout=60,
        critic_options={
            "cppcheck-misra": {"timeout": 123, "misra_rules_path": custom_rules},
            "framac-wp": {"timeout": 77, "wp_timeout": 5, "model": "typed", "rte": False},
            "vernfr-control-flow": {"timeout": 41, "script_path": custom_script},
        },
    )

    cpp = critics[0]
    framac = critics[1]
    vernfr = critics[2]

    assert isinstance(cpp, CppcheckMisraCritic)
    assert cpp.timeout == 123
    assert cpp.misra_rules_path == custom_rules

    assert isinstance(framac, FramaCWPCritic)
    assert framac.timeout == 77
    assert framac.wp_timeout == 5
    assert framac.model == "typed"
    assert framac.rte is False

    assert isinstance(vernfr, VernfrCritic)
    assert vernfr.timeout == 41
    assert vernfr.default_script_path == custom_script
    assert vernfr.name == "vernfr-control-flow"


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_routes_default_to_raw():
    critic = _FakeCritic("compile", success=True, score=1.0)
    out = critics_runner.run_critics_on_artifacts(
        critics=[critic],
        raw_c_path="raw.c",
        timeout=13,
    )

    assert out["critics_success"] is True
    assert out["critics_score"] == 1.0
    assert critic.calls[0]["c_file_path"] == "raw.c"
    assert critic.calls[0]["timeout"] == 13


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_routes_spec_target():
    critic = _FakeCritic("compile", success=True, score=1.0)
    critics_runner.run_critics_on_artifacts(
        critics=[critic],
        raw_c_path="raw.c",
        spec_c_path="spec.c",
        critic_targets={"compile": "spec"},
    )

    assert critic.calls[0]["c_file_path"] == "spec.c"


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_spec_target_missing_path_returns_failure_result():
    critic = _FakeCritic("compile", success=True, score=1.0)
    out = critics_runner.run_critics_on_artifacts(
        critics=[critic],
        raw_c_path="raw.c",
        spec_c_path=None,
        critic_targets={"compile": "spec"},
    )

    assert out["critics_success"] is False
    assert out["critics_score"] == 0.0
    assert out["critics_results"][0]["summary"] == "Critic target missing."
    assert critic.calls == []


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_merges_context_and_critic_configs():
    critic = _FakeCritic("compile", success=True, score=1.0)
    critics_runner.run_critics_on_artifacts(
        critics=[critic],
        raw_c_path="raw.c",
        timeout=99,
        base_context={"k": "base", "over": "base"},
        include_dirs=["inc1", "inc2"],
        defines=["D1"],
        compiled_output_path="main.out",
        remove_compiled=False,
        critic_configs={"compile": {"over": "critic", "local": 7}},
    )

    ctx = critic.calls[0]["context"]
    assert ctx["k"] == "base"
    assert ctx["over"] == "critic"
    assert ctx["local"] == 7
    assert ctx["include_dirs"] == ["inc1", "inc2"]
    assert ctx["defines"] == ["D1"]
    assert ctx["compiled_output_path"] == "main.out"
    assert ctx["remove_compiled"] is False


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_aggregates_success_min_score_and_elapsed_fields():
    c1 = _FakeCritic("compile", success=True, score=0.8)
    c2 = _FakeCritic("framac-wp", success=False, score=0.3)

    out = critics_runner.run_critics_on_artifacts(
        critics=[c1, c2],
        raw_c_path="raw.c",
    )

    assert out["critics_success"] is False
    assert out["critics_score"] == 0.3
    assert len(out["critics_results"]) == 2

    for item in out["critics_results"]:
        assert "elapsed_time_s" in item
        assert item["elapsed_time_s"] >= 0.0
        assert "elapsed_time_s" in item["metrics"]
        assert item["metrics"]["elapsed_time_s"] >= 0.0


@pytest.mark.unit
@pytest.mark.critics
def test_run_critics_on_artifacts_applies_per_critic_timeout_override():
    critic = _FakeCritic("framac-wp", success=True, score=1.0)
    critics_runner.run_critics_on_artifacts(
        critics=[critic],
        raw_c_path="raw.c",
        timeout=60,
        critic_configs={"framac-wp": {"timeout": 123}},
    )

    assert critic.calls[0]["timeout"] == 123
