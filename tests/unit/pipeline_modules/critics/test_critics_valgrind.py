from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_valgrind


def _write_executable(tmp_path: Path, name: str = "program.sh") -> Path:
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe

def _write_c_file(tmp_path: Path, name: str = "main.c") -> Path:
    p = tmp_path / name
    p.write_text("int main(void){return 0;}\n", encoding="utf-8")
    return p

def _write_massif_report(tmp_path: Path, name: str = "massif.out") -> Path:
    p = tmp_path / name
    p.write_text(massif_report_success, encoding="utf-8")
    return p

def _write_massif_limit_report(tmp_path: Path, name: str = "massif.out") -> Path:
    p = tmp_path / name
    p.write_text(massif_report_with_usage, encoding="utf-8")
    return p

memcheck_output_success = """==1376107== Memcheck, a memory error detector
==1376107== Copyright (C) 2002-2024, and GNU GPL'd, by Julian Seward et al.
==1376107== Using Valgrind-3.26.0 and LibVEX; rerun with -h for copyright info
==1376107== Command: ./test.out
==1376107==
==1376107==
==1376107== HEAP SUMMARY:
==1376107==     in use at exit: 0 bytes in 0 blocks
==1376107==   total heap usage: 0 allocs, 0 frees, 0 bytes allocated
==1376107==
==1376107== All heap blocks were freed -- no leaks are possible
==1376107==
==1376107== For lists of detected and suppressed errors, rerun with: -s
==1376107== ERROR SUMMARY: 0 errors from 0 contexts (suppressed: 0 from 0)"""

memcheck_output_errors = """==1392511== Memcheck, a memory error detector
==1392511== Copyright (C) 2002-2024, and GNU GPL'd, by Julian Seward et al.
==1392511== Using Valgrind-3.26.0 and LibVEX; rerun with -h for copyright info
==1392511== Command: ./test.out
==1392511==
==1392511== Invalid write of size 1
==1392511==    at 0x40011E3: phase1 (in /mnt/c/Users/ERUDY8/Work/temp/test.out)
==1392511==    by 0x40013C9: main (in /mnt/c/Users/ERUDY8/Work/temp/test.out)
==1392511==  Address 0x5493040 is 0 bytes after a block of size 10,485,760 alloc'd
==1392511==    at 0x4850858: malloc (vg_replace_malloc.c:447)
==1392511==    by 0x40011BE: phase1 (in /mnt/c/Users/ERUDY8/Work/temp/test.out)
==1392511==    by 0x40013C9: main (in /mnt/c/Users/ERUDY8/Work/temp/test.out)
==1392511==
Phase 1: 10 MB allocated
==1392511==
==1392511== HEAP SUMMARY:
==1392511==     in use at exit: 0 bytes in 0 blocks
==1392511==   total heap usage: 2 allocs, 2 frees, 10,486,784 bytes allocated
==1392511==
==1392511== All heap blocks were freed -- no leaks are possible
==1392511==
==1392511== For lists of detected and suppressed errors, rerun with: -s
==1392511== ERROR SUMMARY: 1 errors from 1 contexts (suppressed: 0 from 0)"""

massif_report_success = """desc: (none)
cmd: ./test.out
time_unit: i
#-----------
snapshot=0
#-----------
time=0
mem_heap_B=0
mem_heap_extra_B=0
mem_stacks_B=0
heap_tree=empty
"""

massif_report_with_usage = """desc: (none)
cmd: ./test.out
time_unit: i
#-----------
snapshot=0
#-----------
time=0
mem_heap_B=256
mem_heap_extra_B=16
mem_stacks_B=64
heap_tree=empty
#-----------
snapshot=1
#-----------
time=10
mem_heap_B=1024
mem_heap_extra_B=32
mem_stacks_B=128
heap_tree=empty
#-----------
snapshot=2
#-----------
time=20
mem_heap_B=512
mem_heap_extra_B=16
mem_stacks_B=4096
heap_tree=empty
"""


@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_run_missing_executable_returns_failure(tmp_path):

    c_file = _write_c_file(tmp_path)


    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "context": {
                 "compiled_output_path": "does/not/exist"
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Valgrind analysis failed, executable not found."
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_massif_run_timeout_returns_timeout_failure(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        lambda cmd, timeout, cwd: ("", "valgrind timed out", False, 1),
    )

    critic = critics_valgrind.ValgrindCritic(massif=True, memcheck=False)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["message"] == "Valgrind massif timeout"
    assert result["metrics"]["timeout"] == 5
    assert result["findings"][0]["message"] == "Valgrind massif timeout"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_memcheck_run_timeout_returns_timeout_failure(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        lambda cmd, timeout, cwd: ("", "valgrind timed out", False, 1),
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["message"] == "Valgrind memcheck timeout"
    assert result["metrics"]["timeout"] == 5
    assert result["findings"][0]["message"] == "Valgrind memcheck timeout"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_memcheck_no_output_failure(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        lambda cmd, timeout, cwd: ("", "", True, 0),
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert "Memcheck output did not include an error summary." in result["summary"]
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_massif_no_output_failure(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        lambda cmd, timeout, cwd: ("", "", True, 0),
    )

    critic = critics_valgrind.ValgrindCritic(massif=True, memcheck=False)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "Massif output file was not created."
    assert result["findings"][0]["severity"] == "error"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_no_tools_failure(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        lambda cmd, timeout, cwd: ("", "", True, 0),
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=False)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["summary"] == "No Valgrind tools enabled."
    assert result["findings"][0]["severity"] == "warning"

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_memcheck_success(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=memcheck" in cmd
        return memcheck_output_success, "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is True
    assert result["score"] == 1.0
    assert "Memcheck completed with no memory errors or actionable leaks." in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_passes_executable_args_to_executable(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=memcheck" in cmd
        assert f"{exe} --case smoke --name 'phase one'" in cmd
        return memcheck_output_success, "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe),
                 "executable_args": ["--case", "smoke", "--name", "phase one"],
                }
             }

    result = critic.run(input)

    assert result["success"] is True
    assert result["metrics"]["executable_args"] == ["--case", "smoke", "--name", "phase one"]


@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_massif_success(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=massif" in cmd
        assert "--massif-out-file=" in cmd
        _write_massif_report(tmp_path)
        return memcheck_output_success, "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(massif=True, memcheck=False)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is True
    assert result["score"] == 1.0
    assert "Massif analysis completed. Peak heap: " in result["summary"]

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_massif_reports_limits_within_bounds(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=massif" in cmd
        _write_massif_limit_report(tmp_path)
        return "", "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(
        massif=False,
        memcheck=False,
        heap_limit_bytes=2048,
        stack_limit_bytes=8192,
    )

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is True
    assert result["metrics"]["peak_heap_bytes"] == 1024
    assert result["metrics"]["peak_stack_bytes"] == 4096
    assert result["metrics"]["heap_limit_bytes"] == 2048
    assert result["metrics"]["stack_limit_bytes"] == 8192
    assert result["metrics"]["heap_below_limit"] is True
    assert result["metrics"]["stack_below_limit"] is True
    assert "Peak heap usage 1024 bytes is within limit 2048 bytes." in result["summary"]
    assert "Peak stack usage 4096 bytes is within limit 8192 bytes." in result["summary"]

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_massif_fails_when_limit_exceeded(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=massif" in cmd
        _write_massif_limit_report(tmp_path)
        return "", "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(
        massif=True,
        memcheck=False,
        heap_limit_bytes=1000,
        stack_limit_bytes=4096,
    )

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["heap_below_limit"] is False
    assert result["metrics"]["stack_below_limit"] is True
    assert "Peak heap usage 1024 bytes exceeds limit 1000 bytes." in result["summary"]
    assert any(f["rule"] == "massif-heap-limit" and f["severity"] == "error" for f in result["findings"])

@pytest.mark.unit
@pytest.mark.critics
def test_valgrind_memcheck_error_reports(tmp_path, monkeypatch):
    
    exe = _write_executable(tmp_path)
    c_file = _write_c_file(tmp_path)

    def _fake_run_command(cmd, timeout, cwd):
        assert "--tool=memcheck" in cmd
        return memcheck_output_errors, "", True, 0

    monkeypatch.setattr(
        critics_valgrind,
        "run_command",
        _fake_run_command,
    )

    critic = critics_valgrind.ValgrindCritic(massif=False, memcheck=True)

    input = {"c_file_path": str(c_file), 
             "timeout": 5,
             "context": {
                 "compiled_output_path": str(exe)
                }
             }

    result = critic.run(input)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert "Memcheck found 1 errors and 0 leaked bytes." in result["findings"][0]["message"]
    assert result["findings"][0]["severity"] == "error"
