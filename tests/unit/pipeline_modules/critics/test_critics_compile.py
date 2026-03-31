from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_compile


def _write_c_file(tmp_path: Path, name: str = "main.c") -> Path:
    p = tmp_path / name
    p.write_text("int main(void){return 0;}\n", encoding="utf-8")
    return p


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_missing_file_returns_failure():
    critic = critics_compile.CompileCritic()
    result = critic.run({"c_file_path": "does/not/exist.c"})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert "File does not exist" in result["summary"] or result["summary"] == "Compilation failed."
    assert result["findings"][0]["severity"] == "error"


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_timeout_returns_timeout_failure(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_compile,
        "run_command",
        lambda cmd, timeout: ("", "gcc timed out", False),
    )

    critic = critics_compile.CompileCritic()
    result = critic.run({"c_file_path": str(c_file), "timeout": 5})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["message"] == "Compilation timeout"
    assert result["metrics"]["timeout"] == 5
    assert result["findings"][0]["message"] == "Compilation timeout"


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_success_no_warnings(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)
    compiled = tmp_path / "build" / "main.o"
    compiled.parent.mkdir(parents=True, exist_ok=True)
    compiled.write_text("obj", encoding="utf-8")

    monkeypatch.setattr(critics_compile, "run_command", lambda cmd, timeout: ("", "", True))

    critic = critics_compile.CompileCritic()
    result = critic.run(
        {
            "c_file_path": str(c_file),
            "context": {"compiled_output_path": str(compiled), "remove_compiled": True},
        }
    )

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["summary"] == "Compilation succeeded."
    assert result["findings"] == []
    assert not compiled.exists()


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_warning_only_returns_success_with_warning(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)
    warning = f"{c_file}:3:7: warning: unused variable 'x'"
    monkeypatch.setattr(critics_compile, "run_command", lambda cmd, timeout: ("", warning, True))

    critic = critics_compile.CompileCritic()
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is True
    assert result["score"] == 0.9
    assert result["summary"] == "Compilation completed with warnings."
    assert result["metrics"]["warnings"] == 1
    assert result["findings"][0]["severity"] == "warning"


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_error_returns_failure_with_location(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)
    err = f"{c_file}:12:3: error: expected ';'"
    monkeypatch.setattr(critics_compile, "run_command", lambda cmd, timeout: ("", err, True))

    critic = critics_compile.CompileCritic()
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Compilation failed."
    assert result["findings"][0]["location"]["line"] == 12
    assert result["findings"][0]["location"]["column"] == 3


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_respects_remove_compiled_false(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)
    compiled = tmp_path / "main.o"
    compiled.write_text("obj", encoding="utf-8")

    monkeypatch.setattr(critics_compile, "run_command", lambda cmd, timeout: ("", "", True))

    critic = critics_compile.CompileCritic()
    result = critic.run(
        {
            "c_file_path": str(c_file),
            "context": {"compiled_output_path": str(compiled), "remove_compiled": False},
        }
    )

    assert result["success"] is True
    assert compiled.exists()


@pytest.mark.unit
@pytest.mark.critics
def test_compile_run_builds_command_with_context_options(tmp_path, monkeypatch):
    c_file = _write_c_file(tmp_path)
    include_dir = tmp_path / "include dir"
    include_dir.mkdir(parents=True, exist_ok=True)

    seen = {}

    def _fake_run_command(cmd, timeout):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return "", "", True

    monkeypatch.setattr(critics_compile, "run_command", _fake_run_command)

    critic = critics_compile.CompileCritic()
    result = critic.run(
        {
            "c_file_path": str(c_file),
            "timeout": 17,
            "extra_args": ["-Wall"],
            "context": {
                "gcc": "clang",
                "gcc_flags": ["-c", "-std=c11"],
                "include_dirs": [str(include_dir)],
                "defines": ["X=1"],
                "compiled_output_path": str(tmp_path / "out file.o"),
            },
        }
    )

    assert result["success"] is True
    assert seen["timeout"] == 17
    assert "clang" in seen["cmd"]
    assert "-std=c11" in seen["cmd"]
    assert "-DX=1" in seen["cmd"]
    assert f"-I{include_dir}" in seen["cmd"] or f"'-I{include_dir}'" in seen["cmd"]
    assert "-Wall" in seen["cmd"]


@pytest.mark.unit
@pytest.mark.critics
def test_parse_gcc_location_supports_line_and_line_column():
    critic = critics_compile.CompileCritic()

    loc_col = critic._parse_gcc_location("main.c:10:2: error: bad")
    loc_line = critic._parse_gcc_location("main.c:10: warning: meh")

    assert loc_col == {"file": "main.c", "line": 10, "column": 2}
    assert loc_line == {"file": "main.c", "line": 10}


@pytest.mark.unit
@pytest.mark.critics
def test_warning_finding_falls_back_to_default_file_when_no_location():
    critic = critics_compile.CompileCritic()
    finding = critic._warning_finding("just a warning", "default.c")

    assert finding["severity"] == "warning"
    assert finding["location"] == {"file": "default.c"}
