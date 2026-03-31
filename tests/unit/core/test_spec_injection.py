from __future__ import annotations

import pytest

from spec2code.core.spec_injection import (
    _inject_module_state_constants,
    extract_signature_from_interface,
    inject_formal_spec_before_definition,
)


@pytest.mark.unit
def test_extract_signature_from_interface_single_prototype():
    interface_text = "void ShutdownAlgorithm_10ms(void);\n"
    assert extract_signature_from_interface(interface_text=interface_text) == "void ShutdownAlgorithm_10ms(void);"


@pytest.mark.unit
def test_extract_signature_from_interface_requires_exactly_one():
    with pytest.raises(ValueError, match="found 0"):
        extract_signature_from_interface(interface_text="Module x {}")

    with pytest.raises(ValueError, match="found 2"):
        extract_signature_from_interface(interface_text="void a(void);\nvoid b(void);\n")


@pytest.mark.unit
def test_inject_formal_spec_before_definition_inserts_once():
    interface_text = "void ShutdownAlgorithm_10ms(void);"
    formal_spec = "/*@ requires \\true; ensures \\true; */"
    c_code = "#include <stdio.h>\n\nvoid ShutdownAlgorithm_10ms(void) {\n}\n"

    out = inject_formal_spec_before_definition(
        c_code=c_code,
        interface_text=interface_text,
        formal_spec=formal_spec,
    )

    assert formal_spec in out
    assert out.index(formal_spec) < out.index("void ShutdownAlgorithm_10ms(void) {")


@pytest.mark.unit
def test_inject_module_state_constants_replaces_include_with_content():
    c_code = '#include "module_state_and_constants.h"\n#include <stdio.h>\n\nvoid ShutdownAlgorithm_10ms(void){}\n'
    header_name = "module_state_and_constants.h"
    header_content = "#define SHDN_X 1\nstatic int g_x = 0;"

    out = _inject_module_state_constants(c_code, header_name, header_content)

    assert '#include "module_state_and_constants.h"' not in out
    assert "#define SHDN_X 1" in out
    assert "static int g_x = 0;" in out
