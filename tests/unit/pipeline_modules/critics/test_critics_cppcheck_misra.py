from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_cppcheck_misra


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _base_paths(tmp_path: Path) -> tuple[Path, Path]:
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")
    rules = _write(tmp_path / "misra_rules.txt", "R1\n")
    return c_file, rules


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_dump_timeout_failure(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)

    calls = []

    def _fake_stream(cmd, *, timeout_s, cwd, stream, prefix):
        calls.append((cmd, timeout_s, cwd, stream, prefix))
        return "", "dump timeout", True, -9

    monkeypatch.setattr(critics_cppcheck_misra, "_run_command_streaming", _fake_stream)
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)
    result = critic.run({"c_file_path": str(c_file), "context": {"debug": True}})

    assert result["success"] is False
    assert "dump failed" in result["summary"]
    assert result["metrics"]["native"]["dump_timed_out"] is True
    assert len(calls) == 1


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_dump_nonzero_failure(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)

    monkeypatch.setattr(
        critics_cppcheck_misra,
        "_run_command_streaming",
        lambda *args, **kwargs: ("", "dump failed", False, 2),
    )
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["metrics"]["native"]["dump_returncode"] == 2


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_dump_missing_dump_file_failure(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)

    monkeypatch.setattr(
        critics_cppcheck_misra,
        "_run_command_streaming",
        lambda *args, **kwargs: ("ok", "", False, 0),
    )
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert "did not create dump file" in result["summary"]
    assert "dump_path_missing" in result["metrics"]["native"]


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_misra_timeout_failure(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)
    _write(Path(f"{c_file}.dump"), "dump")

    seq = [
        ("dump ok", "", False, 0),
        ("", "misra timeout", True, -9),
    ]

    def _fake_stream(*args, **kwargs):
        return seq.pop(0)

    monkeypatch.setattr(critics_cppcheck_misra, "_run_command_streaming", _fake_stream)
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)
    result = critic.run({"c_file_path": str(c_file), "context": {"misra_timeout": 4}})

    assert result["success"] is False
    assert "MISRA run timed out" in result["summary"]
    assert result["metrics"]["native"]["misra_timed_out"] is True
    assert result["metrics"]["native"]["misra_timeout_s"] == 4


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_misra_nonzero_still_analyzes_output(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)
    hdr = _write(tmp_path / "src" / "main.h", "#pragma once\n")
    _write(Path(f"{c_file}.dump"), "dump")

    misra_output = "[src/main.c:10]: (Required) [misra-c2012-1.1] violation\n"
    seq = [
        ("dump ok", "", False, 0),
        (misra_output, "", False, 1),
    ]

    def _fake_stream(*args, **kwargs):
        return seq.pop(0)

    monkeypatch.setattr(critics_cppcheck_misra, "_run_command_streaming", _fake_stream)
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)

    result = critic.run(
        {
            "c_file_path": str(c_file),
            "context": {
                "generated_header_path": str(hdr),
                "generated_files": [str(c_file)],
            },
        }
    )

    assert result["success"] is False
    assert result["metrics"]["misra_required_generated"] == 1
    assert result["metrics"]["native"]["misra_returncode"] == 1
    assert str(c_file) in result["metrics"]["native"]["allowed_files"]
    assert str(hdr) in result["metrics"]["native"]["allowed_files"]
    assert result["metrics"]["native"]["generated_files"] == [str(c_file), str(hdr)]


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_uses_rule_texts_and_keeps_dump_phase_plain(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)
    _write(Path(f"{c_file}.dump"), "dump")

    calls = []

    def _fake_stream(cmd, *, timeout_s, cwd, stream, prefix):
        calls.append(cmd)
        if len(calls) == 1:
            return "dump ok", "", False, 0
        return "", "", False, 0

    monkeypatch.setattr(critics_cppcheck_misra, "_run_command_streaming", _fake_stream)
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is True
    assert len(calls) == 2
    assert "--dump" in calls[0]
    assert "--addon=misra" not in calls[0]
    assert "--rule-texts='" in calls[1]
    assert str(rules).replace("\\", "/") in calls[1].replace("\\", "/")


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_run_generated_files_fallback_to_allowed(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)
    hdr = _write(tmp_path / "src" / "main.h", "#pragma once\n")
    _write(Path(f"{c_file}.dump"), "dump")

    seq = [
        ("dump ok", "", False, 0),
        ("", "", False, 0),
    ]

    monkeypatch.setattr(critics_cppcheck_misra, "_run_command_streaming", lambda *a, **k: seq.pop(0))
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules), timeout=33)

    result = critic.run({"c_file_path": str(c_file), "context": {"generated_header_path": str(hdr)}})
    native = result["metrics"]["native"]
    assert native["generated_files"] == [str(hdr)]
    assert native["allowed_files"] == [str(c_file), str(hdr)]


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_analyze_output_counts_score_and_findings():
    critic = critics_cppcheck_misra.CppcheckMisraCritic("dummy.txt")
    output = (
        "[src/main.c:1]: (Required) [misra-c2012-1.1] req\n"
        "[src/main.c:2]: (Advisory) [misra-c2012-2.2] adv\n"
        "[src/main.c:3]: (Undefined) [misra-c2012-3.3] undef\n"
    )
    result = critic._analyze_output(
        output,
        command="cppcheck ...",
        allowed_files=["src/main.c"],
        generated_files=["src/main.c"],
    )

    assert result["success"] is False
    assert result["metrics"]["misra_required_generated"] == 1
    assert result["metrics"]["misra_advisory_generated"] == 1
    assert result["metrics"]["misra_undefined_generated"] == 1
    assert result["metrics"]["weighted_violations_generated"] == 6
    assert result["score"] == pytest.approx(1.0 / 7.0)
    assert len(result["findings"]) == 3
    assert result["findings"][0]["rule"] == "misra-c2012-1.1"
    assert result["findings"][0]["severity"] == "error"


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_analyze_output_success_when_generated_empty_but_allowed_has_violations():
    critic = critics_cppcheck_misra.CppcheckMisraCritic("dummy.txt")
    output = "[include/helper.h:5]: (Required) [misra-c2012-1.1] helper\n"
    result = critic._analyze_output(
        output,
        command="cppcheck ...",
        allowed_files=["include/helper.h"],
        generated_files=["src/main.c"],
    )

    assert result["success"] is True
    assert result["metrics"]["violations_allowed"] == 1
    assert result["metrics"]["violations_generated"] == 0


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_path_and_location_extractors_and_filters():
    critic = critics_cppcheck_misra.CppcheckMisraCritic("dummy.txt")
    l1 = "[src/main.c:10:2]: (Required) [misra-c2012-1.1] x"
    l2 = "src/main.c:20: error: bad"

    # Current parser behavior keeps ":line" for bracket format with column.
    assert critic._extract_path_from_violation(l1) == "src/main.c:10"
    assert critic._extract_path_from_violation(l2) == "src/main.c"

    loc1 = critic._extract_location_from_violation(l1)
    loc2 = critic._extract_location_from_violation(l2)
    assert loc1 == {"file": "src/main.c", "line": 10, "column": 2}
    assert loc2 == {"file": "src/main.c", "line": 20}

    lines = [l1, "[other.c:1]: (Required) [misra-c2012-2.2] y"]
    filtered = critic._filter_violation_lines(lines, ["src/main.c:10"])
    assert len(filtered) == 1


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_result_from_counts_scoring_and_native_payload():
    critic = critics_cppcheck_misra.CppcheckMisraCritic("dummy.txt")

    ok = critic._result_from_counts(True, 0, 0, 0, "", "ok", native={"x": 1})
    bad_zero = critic._result_from_counts(False, 0, 0, 0, "", "bad")
    bad_weighted = critic._result_from_counts(False, 1, 1, 0, "", "bad")

    assert ok["score"] == 1.0
    assert ok["metrics"]["native"]["x"] == 1
    assert bad_zero["score"] == 0.0
    assert bad_weighted["score"] == pytest.approx(1.0 / 5.0)


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_count_by_severity_and_output_filtering():
    critic = critics_cppcheck_misra.CppcheckMisraCritic("dummy.txt")
    lines = [
        "[src/main.c:1]: (Required) [misra-c2012-1.1] r",
        "[src/main.c:2]: (Advisory) [misra-c2012-2.2] a",
        "[src/main.c:3]: (Undefined) [misra-c2012-3.3] u",
    ]
    req, adv, undef = critic._count_by_severity(lines)
    assert (req, adv, undef) == (1, 1, 1)

    out_lines = lines + ["n/a"]
    filtered = critic._filter_output_lines(out_lines, ["src/main.c"])
    assert len(filtered) == 3


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_write_log_failure_does_not_raise(tmp_path, monkeypatch):
    c_file, rules = _base_paths(tmp_path)
    critic = critics_cppcheck_misra.CppcheckMisraCritic(str(rules))

    def _boom(*args, **kwargs):
        raise OSError("disk error")

    monkeypatch.setattr("builtins.open", _boom)
    critic._write_log(str(c_file.parent), "x.log", "hello")
