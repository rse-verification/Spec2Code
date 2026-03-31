from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_framac_wp


def _make_c_file(tmp_path: Path, name: str = "main.c") -> Path:
    p = tmp_path / name
    p.write_text("int main(void){return 0;}\n", encoding="utf-8")
    return p


@pytest.mark.unit
@pytest.mark.critics
def test_framac_run_builds_expected_command_and_context_flags(tmp_path, monkeypatch):
    c_file = _make_c_file(tmp_path)
    seen = {}

    def _fake_run_command(cmd, timeout, cwd=None):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        seen["cwd"] = cwd
        return "Proved goals: 1 / 1\n", "", True

    monkeypatch.setattr(critics_framac_wp, "run_command", _fake_run_command)

    critic = critics_framac_wp.FramaCWPCritic(
        solvers=["Alt-Ergo", "CVC4"],
        wp_timeout=7,
        smoke_tests=True,
        timeout=42,
        model="typed",
        rte=True,
    )

    result = critic.run(
        {
            "c_file_path": str(c_file),
            "context": {
                "framac_wp_no_let": True,
                "interface_text": "void ShutdownAlgorithm_10ms(void);",
            },
        }
    )

    assert result["success"] is True
    assert seen["timeout"] == 42
    assert seen["cwd"] == str(tmp_path)
    assert "-wp" in seen["cmd"]
    assert "-wp-rte" in seen["cmd"]
    assert "-wp-no-let" in seen["cmd"]
    assert "-wp-smoke-tests" in seen["cmd"]
    assert "-wp-prover Alt-Ergo,CVC4" in seen["cmd"]
    assert "-wp-timeout 7" in seen["cmd"]
    assert "-wp-model typed" in seen["cmd"]

    native = result["metrics"]["native"]
    assert native["inline_targets"] == ["ShutdownAlgorithm_10ms"]
    assert native["rte"] is True
    assert native["wp_timeout"] == 7


@pytest.mark.unit
@pytest.mark.critics
def test_framac_run_timeout_returns_failure_with_native(tmp_path, monkeypatch):
    c_file = _make_c_file(tmp_path)

    monkeypatch.setattr(
        critics_framac_wp,
        "run_command",
        lambda cmd, timeout, cwd=None: ("", "timed out", False),
    )

    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    result = critic.run({"c_file_path": str(c_file), "timeout": 9})

    assert result["success"] is False
    assert result["summary"] == "Timeout"
    assert result["score"] == 0.0
    assert result["findings"][0]["message"] == "Frama-C timed out."
    assert result["metrics"]["native"]["completed"] is False
    assert result["metrics"]["native"]["timeout"] == 9


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_syntax_error_branch():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = "[kernel] noise\nSyntax error near token\n"

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is False
    assert "Syntax error detected" in result["summary"]
    assert result["findings"][0]["message"] == "Syntax error / invalid input."


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_fatal_error_branch():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = "fatal error: cannot open file\n"

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is False
    assert "Fatal error detected" in result["summary"]
    assert result["findings"][0]["message"] == "Fatal error."


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_timeout_goal_details_branch():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = (
        "Proved goals: 1 / 2\n"
        "Timeout\n"
        "Goal xyz (file main.c, line 77)\n"
    )

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is False
    assert result["score"] == pytest.approx(0.5)
    assert "Verification timed out" in result["summary"]
    assert len(result["findings"]) == 1
    assert result["findings"][0]["location"]["line"] == 77
    assert result["metrics"]["native"]["timed_out_goals"] is True


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_timeout_zero_does_not_force_failure():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = "Proved goals: 2 / 2\nTimeout: 0\n"

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is True
    assert result["summary"] == "Verification succeeded."
    assert result["score"] == 1.0


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_full_success_branch():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = "Proved goals: 3 / 3\n"

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["summary"] == "Verification succeeded."
    assert result["metrics"]["proved_goals"] == 3
    assert result["metrics"]["total_goals"] == 3


@pytest.mark.unit
@pytest.mark.critics
def test_framac_analyze_output_partial_failure_branch():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    output = "Proved goals: 1 / 3\n"

    result = critic._analyze_output(output, "main.c", "frama-c cmd")

    assert result["success"] is False
    assert result["score"] == pytest.approx(1.0 / 3.0)
    assert result["summary"] == "Verification failed."
    assert result["findings"][0]["message"] == "Not all goals proved."


@pytest.mark.unit
@pytest.mark.critics
def test_framac_extract_verified_goals_handles_parse_failure():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    assert critic._extract_verified_goals("garbage") == (0, 0)


@pytest.mark.unit
@pytest.mark.critics
def test_framac_extract_timeout_details_without_goal_lines():
    critic = critics_framac_wp.FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    summary, findings = critic._extract_timeout_details("Timeout only\n", "main.c")
    assert summary == "Verification timed out."
    assert findings == []
