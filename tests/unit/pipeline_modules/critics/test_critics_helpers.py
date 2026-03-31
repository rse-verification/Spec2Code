from __future__ import annotations

import pytest

from spec2code.pipeline_modules.critics.critics_compile import _extract_diagnostics
from spec2code.pipeline_modules.critics.critics_cppcheck_misra import CppcheckMisraCritic
from spec2code.pipeline_modules.critics.critics_framac_wp import FramaCWPCritic


@pytest.mark.unit
@pytest.mark.critics
def test_extract_diagnostics_splits_warnings_and_errors():
    raw = (
        "main.c:10:2: warning: unused variable 'x'\n"
        "main.c:20:5: error: expected ';'\n"
        "ld: undefined reference to `foo`\n"
    )
    out = _extract_diagnostics(raw)
    assert len(out["warnings"]) == 1
    assert len(out["errors"]) == 2


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_analyze_output_gates_on_generated_files_only():
    critic = CppcheckMisraCritic(misra_rules_path="dummy.txt")
    output = (
        "[include/helper.h:5]: (Required) [misra-c2012-2.2] helper issue\n"
    )

    result = critic._analyze_output(
        output,
        command="cppcheck ...",
        allowed_files=["src/main.c", "include/helper.h"],
        generated_files=["src/main.c"],
    )

    assert result["success"] is True
    assert result["metrics"]["violations_allowed"] == 1
    assert result["metrics"]["violations_generated"] == 0
    assert result["findings"] == []


@pytest.mark.unit
@pytest.mark.critics
def test_cppcheck_analyze_output_reports_generated_required_violation():
    critic = CppcheckMisraCritic(misra_rules_path="dummy.txt")
    output = "[src/main.c:10]: (Required) [misra-c2012-1.1] violation\n"

    result = critic._analyze_output(
        output,
        command="cppcheck ...",
        allowed_files=["src/main.c"],
        generated_files=["src/main.c"],
    )

    assert result["success"] is False
    assert result["metrics"]["misra_required_generated"] == 1
    assert result["score"] == pytest.approx(0.25)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "error"


@pytest.mark.unit
@pytest.mark.critics
def test_framac_extract_inline_targets_from_entry_functions_block():
    critic = FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    interface_text = (
        "Module shutdown_algorithm {\n"
        "  entry_functions: {\n"
        "    void ShutdownAlgorithm_10ms(void)\n"
        "  }\n"
        "}\n"
    )
    assert critic._extract_inline_targets(interface_text) == ["ShutdownAlgorithm_10ms"]


@pytest.mark.unit
@pytest.mark.critics
def test_framac_extract_inline_targets_falls_back_to_prototypes():
    critic = FramaCWPCritic(solvers=["Alt-Ergo"], wp_timeout=2)
    interface_text = "void A(void);\nint B(int x);\n"
    assert critic._extract_inline_targets(interface_text) == ["A", "B"]
