from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec2code.pipeline_modules import config_loader
from tests.support.factories import build_config_dict, write_config, write_shutdown_case_study


@pytest.mark.unit
def test_load_and_prepare_configs_success(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths, output_folder="output/test_runs/shutdown")
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: f"PROMPT::{template}::{len(inputs)}")
    monkeypatch.setattr(
        config_loader,
        "build_critics_from_names",
        lambda *, names, solvers, timeout, critic_options: [f"critic:{name}" for name in names],
    )

    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=["Alt-Ergo"])

    assert len(prepared) == 1
    item = prepared[0]
    assert Path(item.output_folder).parts[-3:] == ("output", "test_runs", "shutdown")
    assert item.interface_path.endswith("shutdown_algorithm.is")
    assert item.case_study_inputs.input_interface.strip().startswith("Module shutdown_algorithm")
    assert item.filled_prompt.startswith("PROMPT::zero-shot")
    assert item.critics_instances == ["critic:compile"]


@pytest.mark.unit
def test_load_and_prepare_configs_missing_interface_file_raises(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["interface_path"] = str(tmp_path / "missing.is")
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: [])

    with pytest.raises(FileNotFoundError, match="interface_path"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_empty_interface_raises(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    paths["interface_path"].write_text("\n", encoding="utf-8")

    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: [])

    with pytest.raises(ValueError, match="interface file is empty"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_invalid_critics_type_raises(tmp_path):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["critics"] = "compile"
    write_config(config_path, [cfg])

    with pytest.raises(ValueError, match="'critics' must be a list"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_defaults_critics_and_optional_values(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg.pop("critics", None)
    cfg.pop("temperature", None)
    cfg.pop("debug", None)
    cfg.pop("timeout_s", None)
    cfg.pop("copy_headers_to_output", None)
    cfg.pop("critic_context", None)
    cfg.pop("critic_options", None)
    cfg.pop("verification_header_path", None)
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")

    captured = {}

    def _fake_build_critics(*, names, solvers, timeout, critic_options):
        captured["names"] = names
        captured["solvers"] = solvers
        captured["timeout"] = timeout
        captured["critic_options"] = critic_options
        return ["critic:compile"]

    monkeypatch.setattr(config_loader, "build_critics_from_names", _fake_build_critics)

    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=["Alt-Ergo"])
    item = prepared[0]

    assert item.critics == ["compile"]
    assert item.temperature == 0.7
    assert item.debug is False
    assert item.timeout_s == 60
    assert item.copy_headers_to_output is True
    assert item.critic_context == {}
    assert item.critic_options == {}
    assert captured == {
        "names": ["compile"],
        "solvers": ["Alt-Ergo"],
        "timeout": 60,
        "critic_options": {},
    }


@pytest.mark.unit
def test_load_and_prepare_configs_critic_context_and_options_passthrough(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["critic_context"] = {"framac_wp_no_let": True, "debug": True}
    cfg["critic_options"] = {
        "framac-wp": {"wp_timeout": 9, "rte": False},
        "cppcheck-misra": {"timeout": 120},
    }
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    captured = {}

    def _fake_build_critics(*, names, solvers, timeout, critic_options):
        captured["critic_options"] = critic_options
        return ["critic:ok"]

    monkeypatch.setattr(config_loader, "build_critics_from_names", _fake_build_critics)
    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    item = prepared[0]

    assert item.critic_context["framac_wp_no_let"] is True
    assert item.critic_options["framac-wp"]["wp_timeout"] == 9
    assert captured["critic_options"]["cppcheck-misra"]["timeout"] == 120


@pytest.mark.unit
def test_load_and_prepare_configs_legacy_framac_fields_are_mapped(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["framac_wp_timeout_s"] = 7
    cfg["framac_wp_no_let"] = True
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:ok"])

    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    item = prepared[0]

    assert item.critic_options["framac-wp"]["wp_timeout"] == 7
    assert item.critic_context["framac_wp_no_let"] is True


@pytest.mark.unit
def test_load_and_prepare_configs_resolves_relative_verification_header_path(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["verification_header_path"] = "case_studies/shutdown_algorithm/headers/shutdown_algorithm_ver.h"
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:compile"])

    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    assert (
        prepared[0]
        .critic_options["framac-wp"]["verification_header_template_path"]
        == str(paths["verification_header_path"])
    )


@pytest.mark.unit
def test_load_and_prepare_configs_missing_verification_header_path_raises(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["verification_header_path"] = "case_studies/shutdown_algorithm/headers/missing_ver.h"
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:compile"])

    with pytest.raises(FileNotFoundError, match="verification_header_path"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_verification_header_path_from_critic_options(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg.pop("verification_header_path", None)
    cfg["critic_options"] = {
        "framac-wp": {
            "verification_header_template_path": "case_studies/shutdown_algorithm/headers/shutdown_algorithm_ver.h"
        }
    }
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:compile"])

    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    assert (
        prepared[0]
        .critic_options["framac-wp"]["verification_header_template_path"]
        == str(paths["verification_header_path"])
    )


@pytest.mark.unit
def test_load_and_prepare_configs_manifest_header_missing_file_raises(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["headers_manifest"]["missing.h"] = "Missing"
    write_config(config_path, [cfg])

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:compile"])

    with pytest.raises(FileNotFoundError, match="headers_manifest"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_manifest_validation_errors(tmp_path):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"

    cfg = build_config_dict(paths)
    cfg["headers_manifest"] = "nope"
    write_config(config_path, [cfg])
    with pytest.raises(ValueError, match="object/dict"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])

    cfg = build_config_dict(paths)
    cfg["headers_manifest"] = {"": "desc"}
    write_config(config_path, [cfg])
    with pytest.raises(ValueError, match="filename key"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])

    cfg = build_config_dict(paths)
    cfg["headers_manifest"] = {"x.h": 123}
    write_config(config_path, [cfg])
    with pytest.raises(ValueError, match="description must be a string"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_module_state_header_present_or_absent(tmp_path, monkeypatch):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"

    monkeypatch.setattr(config_loader, "format_prompt", lambda template, inputs: "prompt")
    monkeypatch.setattr(config_loader, "build_critics_from_names", lambda **kwargs: ["critic:compile"])

    cfg = build_config_dict(paths)
    write_config(config_path, [cfg])
    prepared = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    assert prepared[0].case_study_inputs.module_state_header_filename == "module_state_and_constants.h"
    assert "g_rs_state" in (prepared[0].case_study_inputs.module_state_header_content or "")

    cfg2 = build_config_dict(paths)
    cfg2["headers_manifest"].pop("module_state_and_constants.h")
    write_config(config_path, [cfg2])
    prepared2 = config_loader.load_and_prepare_configs(str(config_path), solvers=[])
    assert prepared2[0].case_study_inputs.module_state_header_filename is None
    assert prepared2[0].case_study_inputs.module_state_header_content is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "expected_match"),
    [
        ("temperature", "hot", "must be a number"),
        ("debug", "yes", "must be boolean"),
        ("timeout_s", 1.2, "must be int"),
        ("copy_headers_to_output", 1, "must be boolean"),
        ("framac_wp_timeout_s", 2.2, "must be int"),
        ("framac_wp_no_let", "false", "must be boolean"),
        ("critic_context", "x", "must be an object/dict"),
        ("critic_options", "x", "must be an object/dict"),
    ],
)
def test_load_and_prepare_configs_optional_type_validation(tmp_path, field, value, expected_match):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg[field] = value
    write_config(config_path, [cfg])

    with pytest.raises(ValueError, match=expected_match):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_critic_options_values_must_be_dict(tmp_path):
    paths = write_shutdown_case_study(tmp_path)
    config_path = tmp_path / "config.json"
    cfg = build_config_dict(paths)
    cfg["critic_options"] = {"framac-wp": 5}
    write_config(config_path, [cfg])

    with pytest.raises(ValueError, match=r"critic_options\[framac-wp\]"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])


@pytest.mark.unit
def test_load_and_prepare_configs_requires_top_level_list_and_dict_items(tmp_path):
    config_path = tmp_path / "config.json"

    config_path.write_text(json.dumps({"name": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="top-level JSON must be a list"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])

    config_path.write_text(json.dumps(["bad-item"]), encoding="utf-8")
    with pytest.raises(ValueError, match="item 0 must be an object/dict"):
        config_loader.load_and_prepare_configs(str(config_path), solvers=[])
