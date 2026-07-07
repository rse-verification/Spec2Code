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
                "inferred_main_function": "entry_point",
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
                "inferred_main_function": "entry_point",
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
                "inferred_main_function": "entry_point",
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
            "context": {},
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
