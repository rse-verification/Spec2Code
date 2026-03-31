from __future__ import annotations

import os

import pytest

from spec2code.pipeline_modules import config_loader


@pytest.mark.unit
def test_abspath_resolves_relative_and_preserves_absolute(tmp_path):
    base_dir = str(tmp_path)
    relative = config_loader._abspath(base_dir, os.path.join("a", "..", "b", "file.txt"))
    absolute_input = os.path.join(base_dir, "x", "y", "z.txt")
    absolute = config_loader._abspath(base_dir, absolute_input)

    assert relative == os.path.normpath(os.path.join(base_dir, "b", "file.txt"))
    assert absolute == os.path.normpath(absolute_input)


@pytest.mark.unit
def test_pick_types_header_filename_precedence():
    assert config_loader._pick_types_header_filename([
        {"filename": "a.h"},
        {"filename": "defined_types.h"},
        {"filename": "scania_types.h"},
    ]) == "defined_types.h"

    assert config_loader._pick_types_header_filename([
        {"filename": "a.h"},
        {"filename": "scania_types.h"},
    ]) == "scania_types.h"

    assert config_loader._pick_types_header_filename([
        {"filename": "first.h"},
        {"filename": "second.h"},
    ]) == "first.h"

    assert config_loader._pick_types_header_filename([]) == "defined_types.h"


@pytest.mark.unit
def test_optional_bool_or_false_validates_type():
    assert config_loader._optional_bool_or_false({}, "copy") is False
    assert config_loader._optional_bool_or_false({"copy": True}, "copy") is True

    with pytest.raises(ValueError, match="must be boolean"):
        config_loader._optional_bool_or_false({"copy": "yes"}, "copy")
