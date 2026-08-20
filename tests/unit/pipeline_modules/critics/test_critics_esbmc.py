from __future__ import annotations

import shlex

import pytest

from spec2code.pipeline_modules.critics import critics_esbmc
from spec2code.pipeline_modules.critics.critics_esbmc import ESBMCCritic


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_c_file_not_exist_failure(tmp_path):

    result = ESBMCCritic().run(
        {
            "c_file_path": "does/not/exist",
            "timeout": 60,
            "context": {
                "esbmc_options": '--unwind 10 --floatbv --context-bound "2"',
            },
        }
    )

    assert result["success"] is False
    assert result["summary"] == "Could not find C file."


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_timout_failure(tmp_path, monkeypatch):
    c_file = tmp_path / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    captured = {}

    def _fake_run_command(cmd, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return ("", "timeout", False, 1)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic().run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {
                "entry_functions": ["entry_point"],
                "esbmc_options": '--unwind 10 --floatbv --context-bound "2"',
            },
        }
    )

    assert result["success"] is False
    assert result["summary"] == "ESBMC timeout"
    assert captured["timeout"] == 60


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_adds_options_from_context(tmp_path, monkeypatch):
    c_file = tmp_path / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    captured = {}

    def _fake_run_command(cmd, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic().run(
        {
            "c_file_path": str(c_file),
            "timeout": 42,
            "context": {
                "entry_functions": ["entry_point"],
                "esbmc_options": '--unwind 10 --floatbv --context-bound "2"',
            },
        }
    )

    assert result["success"] is True
    assert captured["timeout"] == 42
    assert shlex.split(captured["cmd"]) == [
        "esbmc",
        str(c_file),
        "--unwind",
        "10",
        "--floatbv",
        "--context-bound",
        "2",
        "--function",
        "entry_point",
    ]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_uses_builder_defaults_when_context_has_no_options(tmp_path, monkeypatch):
    c_file = tmp_path / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    captured = {}

    def _fake_run_command(cmd, timeout):
        captured["cmd"] = cmd
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic(esbmc_options=["--unwind", "3"]).run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {"entry_functions": ["main"]},
        }
    )

    assert result["success"] is True
    assert shlex.split(captured["cmd"]) == [
        "esbmc",
        str(c_file),
        "--unwind",
        "3",
        "--function",
        "main",
    ]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_adds_configured_checks_and_stack_limit(tmp_path, monkeypatch):
    c_file = tmp_path / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    captured = {}

    def _fake_run_command(cmd, timeout):
        captured["cmd"] = cmd
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic(
        esbmc_options=["--unwind", "3"],
        uninitialised_vars_check=True,
        struct_fields_check=True,
        strict_types=True,
        ub_shift_check=True,
        unsigned_overflow_check=True,
        stack_limit=8192,
    ).run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {"entry_functions": ["main"]},
        }
    )

    assert result["success"] is True
    assert shlex.split(captured["cmd"]) == [
        "esbmc",
        str(c_file),
        "--unwind",
        "3",
        "--uninitialised-vars-check",
        "--struct-fields-check",
        "--strict-types",
        "--ub-shift-check",
        "--unsigned-overflow-check",
        "--stack-limit",
        "8192",
        "--function",
        "main",
    ]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_context_can_override_configured_checks(tmp_path, monkeypatch):
    c_file = tmp_path / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    captured = {}

    def _fake_run_command(cmd, timeout):
        captured["cmd"] = cmd
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic(uninitialised_vars_check=True, stack_limit=64).run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {
                "entry_functions": ["main"],
                "uninitialised_vars_check": False,
                "strict_types": True,
                "stack_limit": 128,
            },
        }
    )

    assert result["success"] is True
    assert shlex.split(captured["cmd"]) == [
        "esbmc",
        str(c_file),
        "--strict-types",
        "--stack-limit",
        "128",
        "--function",
        "main",
    ]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_stack_limit_must_be_an_integer():
    with pytest.raises(ValueError, match="stack_limit must be an integer"):
        ESBMCCritic(stack_limit="not-an-integer")


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_critic_runs_and_reports_every_entry_function(tmp_path, monkeypatch):
    c_file = tmp_path / "module.c"
    c_file.write_text(
        "void Init(void) {}\nvoid Step(void) {}\n",
        encoding="utf-8",
    )
    commands = []

    def _fake_run_command(cmd, timeout):
        commands.append(cmd)
        entry_function = shlex.split(cmd)[-1]
        if entry_function == "Init":
            return ("VERIFICATION SUCCESSFUL", "", True, 0)
        return (
            "Violated property:\n  file module.c line 2 function Step\n"
            "VERIFICATION FAILED",
            "",
            True,
            1,
        )

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic().run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {
                "entry_functions": ["Init", "Step"],
            },
        }
    )

    assert [shlex.split(cmd)[-1] for cmd in commands] == ["Init", "Step"]
    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["entry_functions"] == ["Init", "Step"]
    assert result["metrics"]["total_runs"] == 2
    assert result["metrics"]["successful_runs"] == 1
    assert result["metrics"]["failed_runs"] == 1
    assert [run["entry_function"] for run in result["metrics"]["runs"]] == ["Init", "Step"]
    assert [run["success"] for run in result["metrics"]["runs"]] == [True, False]
    assert result["findings"][0]["entry_function"] == "Step"
    assert result["findings"][0]["message"].startswith("[Step]")
    assert "ESBMC entry function: Init" in result["raw_output"]
    assert "ESBMC entry function: Step" in result["raw_output"]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_function_names_override_entry_functions(tmp_path, monkeypatch):
    c_file = tmp_path / "module.c"
    c_file.write_text(
        "void Selected(void) {}\nvoid AlsoSelected(void) {}\n",
        encoding="utf-8",
    )
    commands = []

    def _fake_run_command(cmd, timeout):
        commands.append(cmd)
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic(function_names=["Selected", "AlsoSelected"]).run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {"entry_functions": ["Init", "Step"]},
        }
    )

    assert result["success"] is True
    assert [shlex.split(command)[-1] for command in commands] == ["Selected", "AlsoSelected"]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_function_names_accepts_gui_comma_separated_value(tmp_path, monkeypatch):
    c_file = tmp_path / "module.c"
    c_file.write_text("void First(void) {}\nvoid Second(void) {}\n", encoding="utf-8")
    commands = []

    def _fake_run_command(cmd, timeout):
        commands.append(cmd)
        return ("VERIFICATION SUCCESSFUL", "", True)

    monkeypatch.setattr(critics_esbmc, "run_command", _fake_run_command)

    result = ESBMCCritic(function_names="First, Second").run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {"entry_functions": ["Ignored"]},
        }
    )

    assert result["success"] is True
    assert [shlex.split(command)[-1] for command in commands] == ["First", "Second"]


@pytest.mark.unit
@pytest.mark.critics
def test_esbmc_does_not_use_inferred_main_function(tmp_path, monkeypatch):
    c_file = tmp_path / "module.c"
    c_file.write_text("void Inferred(void) {}\n", encoding="utf-8")

    def _unexpected_run_command(cmd, timeout):
        pytest.fail(f"ESBMC should not run without entry_functions: {cmd}")

    monkeypatch.setattr(critics_esbmc, "run_command", _unexpected_run_command)

    result = ESBMCCritic().run(
        {
            "c_file_path": str(c_file),
            "timeout": 60,
            "context": {"inferred_main_function": "Inferred"},
        }
    )

    assert result["success"] is False
    assert result["summary"] == "No functions to analyze with ESBMC."
