from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_no_loops
from spec2code.pipeline_modules.critics.critics_registry import CRITIC_BUILDERS, GUI_CRITICS_CATALOG


def _function(path: Path, name: str, statements: list[dict]) -> dict:
    return {
        "kind": "FunctionDecl",
        "name": name,
        "loc": {"file": str(path), "line": 1, "col": 1},
        "inner": [{"kind": "CompoundStmt", "inner": statements}],
    }


def _ast(*functions: dict) -> dict:
    return {"kind": "TranslationUnitDecl", "inner": list(functions)}


def _call(target: str, line: int) -> dict:
    return {
        "kind": "CallExpr",
        "loc": {"line": line, "col": 3},
        "inner": [{"kind": "DeclRefExpr", "referencedDecl": {"kind": "FunctionDecl", "name": target}}],
    }


def _run_ast(monkeypatch, source: Path, ast: dict, *, completed=True, exit_code=0, stderr="", timing=None):
    monkeypatch.setattr(
        critics_no_loops,
        "run_command",
        lambda command, timeout, cwd=None, stream=False: (json.dumps(ast), stderr, completed, exit_code, timing or {}),
    )
    return critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source)})


@pytest.mark.unit
@pytest.mark.critics
@pytest.mark.parametrize(
    ("kind", "rule"),
    [
        ("ForStmt", "no_for_loop"),
        ("WhileStmt", "no_while_loop"),
        ("DoStmt", "no_do_while_loop"),
        ("GotoStmt", "no_goto"),
        ("IndirectGotoStmt", "no_computed_goto"),
    ],
)
def test_no_loops_reports_each_prohibited_ast_node(tmp_path, kind, rule):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    node = {"kind": kind, "loc": {"line": 4, "col": 5}}

    findings = critics_no_loops.NoLoopsCritic()._findings(_ast(_function(source, "step", [node])), str(source))

    assert len(findings) == 1
    assert findings[0]["rule"] == rule
    assert findings[0]["location"] == {"file": str(source), "line": 4, "column": 5}


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_direct_and_indirect_recursion(tmp_path):
    source = tmp_path / "generated.c"
    source.write_text("void a(void) {}\n", encoding="utf-8")
    ast = _ast(
        _function(source, "direct", [_call("direct", 3)]),
        _function(source, "first", [_call("second", 7)]),
        _function(source, "second", [_call("first", 11)]),
    )

    findings = critics_no_loops.NoLoopsCritic()._findings(ast, str(source))

    recursion = [finding for finding in findings if finding["rule"] == "no_recursion"]
    assert len(recursion) == 3
    assert any("direct -> direct" in finding["message"] for finding in recursion)
    assert any("first -> second -> first" in finding["message"] for finding in recursion)


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_long_cycle_but_not_acyclic_callers(tmp_path):
    source = tmp_path / "generated.c"
    source.write_text("void entry(void) {}\n", encoding="utf-8")
    ast = _ast(
        _function(source, "entry", [_call("first", 2)]),
        _function(source, "first", [_call("second", 4)]),
        _function(source, "second", [_call("third", 6)]),
        _function(source, "third", [_call("first", 8)]),
    )

    recursion = [finding for finding in critics_no_loops.NoLoopsCritic()._findings(ast, str(source)) if finding["rule"] == "no_recursion"]

    assert len(recursion) == 3
    assert all(finding["location"]["line"] != 2 for finding in recursion)
    assert any("first -> second -> third -> first" in finding["message"] for finding in recursion)


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_allows_non_iterative_control_flow_and_external_calls(tmp_path):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    allowed = [
        {"kind": "IfStmt", "loc": {"line": 2}},
        {"kind": "SwitchStmt", "loc": {"line": 3}},
        _call("external_function", 4),
    ]

    assert critics_no_loops.NoLoopsCritic()._findings(_ast(_function(source, "step", allowed)), str(source)) == []


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_ignores_constructs_in_included_headers(tmp_path):
    source = tmp_path / "generated.c"
    header = tmp_path / "helper.h"
    source.write_text('#include "helper.h"\nvoid step(void) {}\n', encoding="utf-8")
    loop = {"kind": "ForStmt", "range": {"begin": {"file": str(header), "line": 2, "col": 3}}}
    ast = _ast(_function(header, "header_helper", [loop]), _function(source, "step", []))

    assert critics_no_loops.NoLoopsCritic()._findings(ast, str(source)) == []


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_uses_range_and_macro_expansion_location(tmp_path):
    source = tmp_path / "generated.c"
    header = tmp_path / "macros.h"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    macro_loop = {
        "kind": "DoStmt",
        "range": {
            "begin": {
                "spellingLoc": {"file": str(header), "line": 1, "col": 16},
                "expansionLoc": {"file": str(source), "line": 7, "col": 5},
            }
        },
    }

    findings = critics_no_loops.NoLoopsCritic()._findings(_ast(_function(source, "step", [macro_loop])), str(source))

    assert findings[0]["rule"] == "no_do_while_loop"
    assert findings[0]["location"] == {"file": str(source), "line": 7, "column": 5}


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_fails_closed_for_unresolved_indirect_call(tmp_path):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    indirect_call = {
        "kind": "CallExpr",
        "range": {"begin": {"line": 5, "col": 3}},
        "inner": [{"kind": "DeclRefExpr", "referencedDecl": {"kind": "VarDecl", "name": "callback"}}],
    }

    findings = critics_no_loops.NoLoopsCritic()._findings(_ast(_function(source, "step", [indirect_call])), str(source))

    assert findings[0]["rule"] == "no_unresolved_indirect_call"
    assert findings[0]["location"]["line"] == 5


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_passes_loop_free_source_and_uses_clang_ast(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(critics_no_loops, "run_command", lambda command, timeout, cwd=None, stream=False: (json.dumps(_ast(_function(source, "step", []))), "", True, 0))

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source), "context": {"include_dirs": ["headers"], "defines": ["FEATURE=1"]}})

    assert result["success"] is True
    assert result["findings"] == []
    assert "-Iheaders" in result["metrics"]["command"]
    assert "-DFEATURE=1" in result["metrics"]["command"]


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_quotes_paths_and_forwards_clang_flags(tmp_path):
    source = tmp_path / "source folder" / "generated file.c"
    source.parent.mkdir()
    source.write_text("void step(void) {}\n", encoding="utf-8")

    command = critics_no_loops.NoLoopsCritic(clang="clang-18")._ast_command(
        str(source),
        {"include_dirs": [tmp_path / "header folder"], "defines": ["VALUE=two words"], "clang_flags": ["-std=c11"]},
    )

    assert command.startswith("clang-18 ")
    assert "'-I" in command and "header folder'" in command
    assert "'-DVALUE=two words'" in command
    assert "-std=c11" in command
    assert "'" + str(source) + "'" in command


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_missing_source_file():
    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": "missing-generated.c"})

    assert result["success"] is False
    assert result["findings"][0]["rule"] == "clang_ast"
    assert "does not exist" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_timeout_and_process_timing(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(
        critics_no_loops,
        "run_command",
        lambda command, timeout, cwd=None, stream=False: ("", "partial output", False, None, {"real": 4.2}),
    )

    result = critics_no_loops.NoLoopsCritic(timeout=4).run({"c_file_path": str(source)})

    assert result["success"] is False
    assert "timed out" in result["summary"]
    assert result["metrics"]["timeout"] == 4
    assert result["metrics"]["process_real_s"] == 4.2


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_invalid_json_ast(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(critics_no_loops, "run_command", lambda command, timeout, cwd=None, stream=False: ("not-json", "", True, 0))

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source)})

    assert result["success"] is False
    assert "valid JSON AST" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_counts_multiple_findings_and_preserves_timing(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("void step(void) {}\n", encoding="utf-8")
    ast = _ast(_function(source, "step", [
        {"kind": "ForStmt", "range": {"begin": {"line": 2, "col": 3}}},
        {"kind": "GotoStmt", "range": {"begin": {"line": 3, "col": 3}}},
    ]))

    result = _run_ast(monkeypatch, source, ast, timing={"real": 0.1, "user": 0.05, "sys": 0.01})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["prohibited_constructs"] == 2
    assert result["metrics"]["process_real_s"] == 0.1
    assert [finding["rule"] for finding in result["findings"]] == ["no_for_loop", "no_goto"]


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_reports_clang_parse_failure(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("not valid C", encoding="utf-8")
    monkeypatch.setattr(critics_no_loops, "run_command", lambda command, timeout, cwd=None, stream=False: ("", "error: expected ';'", True, 1))

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source)})

    assert result["success"] is False
    assert result["findings"][0]["rule"] == "clang_ast"
    assert "could not parse" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_is_registered_with_a_configurable_clang_command():
    critic = CRITIC_BUILDERS["no-loops"]({"clang": "clang-18", "timeout": 12}, [], 60)

    assert isinstance(critic, critics_no_loops.NoLoopsCritic)
    assert critic.clang == "clang-18"
    assert critic.timeout == 12


@pytest.mark.unit
@pytest.mark.critics
def test_no_loops_gui_catalog_is_opt_in_and_exposes_options():
    entry = next(item for item in GUI_CRITICS_CATALOG if item["name"] == "no-loops")
    options = {option["key"]: option for option in entry["options"]}

    assert entry["default_enabled"] is True
    assert options["timeout"]["default"] == 60
    assert options["clang"]["default"] == "clang"


@pytest.mark.integration
@pytest.mark.critics
@pytest.mark.parametrize(
    ("source_text", "expected_rule"),
    [
        ("void step(void) { for (;;) {} }\n", "no_for_loop"),
        ("void step(void) { while (1) {} }\n", "no_while_loop"),
        ("void step(void) { do {} while (1); }\n", "no_do_while_loop"),
        ("void step(void) { goto end; end: return; }\n", "no_goto"),
        ("void step(void) { void *p = &&end; goto *p; end: return; }\n", "no_computed_goto"),
        ("void step(void) { step(); }\n", "no_recursion"),
        ("void target(void) {} void step(void) { void (*callback)(void) = target; callback(); }\n", "no_unresolved_indirect_call"),
    ],
)
def test_no_loops_with_real_clang_reports_prohibited_source(tmp_path, source_text, expected_rule):
    if shutil.which("clang") is None:
        pytest.skip("clang is not installed")
    source = tmp_path / "generated.c"
    source.write_text(source_text, encoding="utf-8")

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source)})

    assert result["success"] is False
    finding = next(finding for finding in result["findings"] if finding["rule"] == expected_rule)
    assert finding["location"]["line"] == 1
    assert finding["location"]["column"] > 0


@pytest.mark.integration
@pytest.mark.critics
def test_no_loops_with_real_clang_ignores_header_loop_and_allows_acyclic_calls(tmp_path):
    if shutil.which("clang") is None:
        pytest.skip("clang is not installed")
    header = tmp_path / "helper.h"
    source = tmp_path / "generated.c"
    header.write_text("static inline void helper(void) { for (;;) { break; } }\n", encoding="utf-8")
    source.write_text('#include "helper.h"\nvoid leaf(void) {}\nvoid step(void) { leaf(); }\n', encoding="utf-8")

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source), "context": {"include_dirs": [str(tmp_path)]}})

    assert result["success"] is True
    assert result["findings"] == []


@pytest.mark.integration
@pytest.mark.critics
def test_no_loops_with_real_clang_reports_macro_expansion_location(tmp_path):
    if shutil.which("clang") is None:
        pytest.skip("clang is not installed")
    header = tmp_path / "macros.h"
    source = tmp_path / "generated.c"
    header.write_text("#define LOOP_ONCE() do {} while (0)\n", encoding="utf-8")
    source.write_text('#include "macros.h"\nvoid step(void) { LOOP_ONCE(); }\n', encoding="utf-8")

    result = critics_no_loops.NoLoopsCritic().run({"c_file_path": str(source), "context": {"include_dirs": [str(tmp_path)]}})

    finding = next(finding for finding in result["findings"] if finding["rule"] == "no_do_while_loop")
    assert finding["location"]["file"] == str(source)
    assert finding["location"]["line"] == 2
