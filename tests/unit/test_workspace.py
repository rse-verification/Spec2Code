from __future__ import annotations

import json

import pytest

from spec2code.pipeline_modules.config_loader import load_and_prepare_configs
from spec2code.workspace import WorkspacePaths, apply_project_defaults, discover_project


def _project(tmp_path, name="demo"):
    project = tmp_path / "workspace" / "projects" / name
    headers = project / "headers"
    headers.mkdir(parents=True)
    (project / "nlspec.txt").write_text("Requirement", encoding="utf-8")
    (project / f"{name}.is").write_text("interface", encoding="utf-8")
    (headers / "types.h").write_text("typedef int value_t;", encoding="utf-8")
    (headers / f"{name}_ver.h").write_text("/*@ requires true; */", encoding="utf-8")
    return project


@pytest.mark.unit
def test_workspace_root_provides_conventional_children(tmp_path):
    paths = WorkspacePaths.from_env(
        repo_root=tmp_path / "repo",
        env={"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "data")},
    )

    assert paths.projects == tmp_path / "data" / "projects"
    assert paths.output == tmp_path / "data" / "output"
    assert paths.reports == tmp_path / "data" / "output" / "reports"
    assert paths.tmp == tmp_path / "data" / "output" / "gui_tmp"


@pytest.mark.unit
def test_workspace_preserves_legacy_roots_without_new_setting(tmp_path):
    repo = tmp_path / "checkout" / "spec2code"
    paths = WorkspacePaths.from_env(repo_root=repo, env={})

    assert paths.output == repo.parent / "spec2code_output"
    assert paths.input == repo.parent / "spec2code_input"
    assert paths.case_studies == repo.parent / "spec2code_case_studies"


@pytest.mark.unit
def test_discover_project_uses_conventions_and_excludes_verification_header(tmp_path):
    project = _project(tmp_path)

    layout = discover_project(project)

    assert layout.ready is True
    assert layout.spec == project / "nlspec.txt"
    assert layout.interface == project / "demo.is"
    assert layout.headers == project / "headers"
    assert layout.verification_header == project / "headers" / "demo_ver.h"
    assert layout.prompt_headers == {"types.h": ""}


@pytest.mark.unit
def test_project_manifest_resolves_paths_and_prompt_header_descriptions(tmp_path):
    project = _project(tmp_path)
    (project / "requirements.md").write_text("Custom specification", encoding="utf-8")
    (project / "spec2code.project.json").write_text(
        json.dumps(
            {
                "spec": "requirements.md",
                "interface": "demo.is",
                "headers": "headers",
                "verification_header": "headers/demo_ver.h",
                "prompt_headers": {"types.h": "Primitive project types."},
                "include_dirs": ["headers"],
            }
        ),
        encoding="utf-8",
    )

    layout = discover_project(project)

    assert layout.spec == project / "requirements.md"
    assert layout.prompt_headers == {"types.h": "Primitive project types."}
    assert layout.include_dirs == (project / "headers",)


@pytest.mark.unit
def test_apply_project_defaults_preserves_explicit_overrides(tmp_path):
    project = _project(tmp_path)
    explicit_output = tmp_path / "custom-output"
    config = apply_project_defaults(
        {
            "project": "demo",
            "output_folder": str(explicit_output),
            "headers_manifest": {"types.h": "Explicit description"},
        },
        base_dir=tmp_path,
        repo_root=tmp_path / "repo",
        env={"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")},
    )

    assert config["natural_spec_path"] == str(project / "nlspec.txt")
    assert config["headers_dir"] == str(project / "headers")
    assert config["output_folder"] == str(explicit_output)
    assert config["headers_manifest"] == {"types.h": "Explicit description"}


@pytest.mark.unit
def test_manifest_rejects_paths_outside_project(tmp_path):
    project = _project(tmp_path)
    (project / "spec2code.project.json").write_text(
        json.dumps({"spec": "../secret.txt"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside the project"):
        discover_project(project)


@pytest.mark.unit
def test_manifest_rejects_prompt_headers_outside_header_directory(tmp_path):
    project = _project(tmp_path)
    (project / "spec2code.project.json").write_text(
        json.dumps({"headers": "headers", "prompt_headers": {"../../secret.txt": "secret"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside the project"):
        discover_project(project)


@pytest.mark.unit
def test_config_loader_accepts_project_only_paths(tmp_path, monkeypatch):
    project = _project(tmp_path)
    workspace = project.parents[1]
    monkeypatch.setenv("SPEC2CODE_WORKSPACE_ROOT", str(workspace))
    config_path = tmp_path / "run.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "project": "demo",
                    "selected_prompt_template": "zero-shot",
                    "llms_used": ["test-model"],
                    "n_programs_generated": 1,
                    "critics": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    prepared = load_and_prepare_configs(str(config_path), solvers=[])[0]

    assert prepared.case_study == "demo"
    assert prepared.natural_spec_path == str(project / "nlspec.txt")
    assert prepared.headers_dir == str(project / "headers")
    assert prepared.include_dirs == [str(project / "headers")]
    assert prepared.output_folder == str(workspace / "output" / "demo" / "config_demo")
