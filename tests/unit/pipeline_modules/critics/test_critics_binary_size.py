from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_binary_size

def _write_c_file(tmp_path: Path, name: str = "main.c") -> Path:
    p = tmp_path / name
    p.write_text("int main(void){return 0;}\n", encoding="utf-8")
    return p

def _write_object_file(tmp_path: Path) -> Path:
    p = tmp_path / "bin_size_object.o"
    p.write_bytes(b"\x7fELF\x02\x01\x01\x00")
    return p

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_missing_c_file_returns_failure(tmp_path):

    critic = critics_binary_size.BinarySizeCritic(1024)

    input = {"c_file_path": "does/not/exist"}

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Failed to create object file, C-file not found."
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_compile_returns_timeout_failure(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        lambda cmd, timeout, cwd: ("", "timeout", False, 1),
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    input = {"c_file_path": str(c_file), 
             "timeout": 5
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["message"] == "Binary size compile step timed out."
    assert result["metrics"]["timeout"] == 5
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_no_object_file_failure(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        lambda cmd, timeout, cwd: ("", "", True, 0),
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    input = {"c_file_path": str(c_file), 
             "timeout": 5
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Failed to compile object file."
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_no_size_output_failure(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    def fake_run_command(cmd, timeout, cwd):
        if cmd.startswith("gcc "):
            _write_object_file(tmp_path)
        return "", "", True, 0

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        fake_run_command,
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    input = {"c_file_path": str(c_file), 
             "timeout": 5
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Failed to parse binary size output."
    assert not (tmp_path / "bin_size_object.o").exists()

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_with_object_file_passes(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    def fake_run_command(cmd, timeout, cwd):
        if cmd.startswith("gcc "):
            _write_object_file(tmp_path)
            return "", "", True, 0
        if cmd.startswith("size "):
            return (
                "   text    data     bss     dec     hex filename\n"
                "    100      20       4     124      7c bin_size_object.o\n",
                "",
                True,
                0,
            )
        return "", "", True, 0

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        fake_run_command,
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    input = {"c_file_path": str(c_file), 
             "timeout": 5
             }

    result = critic.run(input)

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["metrics"]["binary_size_bytes"] == 124
    assert result["findings"] == []
    assert not (tmp_path / "bin_size_object.o").exists()

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_compile_nonzero_ignores_stale_object_file(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)
    stale_object = _write_object_file(tmp_path)

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        lambda cmd, timeout, cwd: ("", "compile error", True, 1),
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    result = critic.run({"c_file_path": str(c_file), "timeout": 5})

    assert result["success"] is False
    assert result["summary"] == "Failed to compile object file."
    assert result["metrics"]["exit_code"] == 1
    assert not stale_object.exists()

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_size_command_nonzero_returns_failure(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    def fake_run_command(cmd, timeout, cwd):
        if cmd.startswith("gcc "):
            _write_object_file(tmp_path)
            return "", "", True, 0
        return "", "size error", True, 1

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        fake_run_command,
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    result = critic.run({"c_file_path": str(c_file), "timeout": 5})

    assert result["success"] is False
    assert result["summary"] == "Binary size command failed."
    assert result["metrics"]["exit_code"] == 1
    assert not (tmp_path / "bin_size_object.o").exists()

@pytest.mark.unit
@pytest.mark.critics
def test_binary_size_over_limit_returns_failure(tmp_path, monkeypatch):
    
    c_file = _write_c_file(tmp_path)

    def fake_run_command(cmd, timeout, cwd):
        if cmd.startswith("gcc "):
            _write_object_file(tmp_path)
            return "", "", True, 0
        return (
            "   text    data     bss     dec     hex filename\n"
            "   1000      40       8    1048     418 bin_size_object.o\n",
            "",
            True,
            0,
        )

    monkeypatch.setattr(
        critics_binary_size,
        "run_command",
        fake_run_command,
    )

    critic = critics_binary_size.BinarySizeCritic(1024)

    result = critic.run({"c_file_path": str(c_file), "timeout": 5})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["binary_size_bytes"] == 1048
    assert result["findings"][0]["rule"] == "binary_size_limit"
    assert not (tmp_path / "bin_size_object.o").exists()
