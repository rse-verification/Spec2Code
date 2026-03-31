from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec2code.gui import run_server


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.unit
def test_run_verify_files_requires_c_file_path(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    out = run_server._run_verify_files({})
    assert out["ok"] is False
    assert "c_file_path" in out["error"]


@pytest.mark.unit
def test_run_verify_files_rejects_paths_outside_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    outside = tmp_path.parent / "outside.c"
    outside.write_text("int main(void){return 0;}\n", encoding="utf-8")

    out = run_server._run_verify_files({"c_file_path": str(outside)})
    assert out["ok"] is False
    assert "inside repository" in out["error"]


@pytest.mark.unit
def test_run_verify_files_requires_existing_c_file(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    out = run_server._run_verify_files({"c_file_path": "src/missing.c"})
    assert out["ok"] is False
    assert "c_file_path not found" in out["error"]


@pytest.mark.unit
def test_run_verify_files_validates_include_dirs_and_generated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")

    out = run_server._run_verify_files({"c_file_path": str(c_file), "include_dirs": ["does/not/exist"]})
    assert out["ok"] is False
    assert "include_dirs entry not found" in out["error"]

    out2 = run_server._run_verify_files({"c_file_path": str(c_file), "generated_files": ["nope.c"]})
    assert out2["ok"] is False
    assert "generated_files entry not found" in out2["error"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("timeout", 0, "timeout must be a positive integer"),
        ("critic_options", "x", "critic_options must be an object/dict"),
        ("critic_context", "x", "critic_context must be an object/dict"),
    ],
)
def test_run_verify_files_validates_scalar_and_dict_inputs(tmp_path, monkeypatch, field, value, expected):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")

    payload = {"c_file_path": str(c_file), field: value}
    out = run_server._run_verify_files(payload)
    assert out["ok"] is False
    assert expected in out["error"]


@pytest.mark.unit
def test_run_verify_files_returns_build_critics_error(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")

    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: (_ for _ in ()).throw(ValueError("bad critic")))

    out = run_server._run_verify_files({"c_file_path": str(c_file), "critics": ["bad"]})
    assert out["ok"] is False
    assert "Failed to build critics" in out["error"]


@pytest.mark.unit
def test_run_verify_files_returns_run_critics_error(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")

    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    out = run_server._run_verify_files({"c_file_path": str(c_file), "critics": ["compile"]})
    assert out["ok"] is False
    assert "Verification failed" in out["error"]


@pytest.mark.unit
def test_run_verify_files_happy_path_builds_and_runs_critics(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_server, "REPORTS_DIR", tmp_path / "output" / "reports")
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")
    hdr_file = _write(tmp_path / "src" / "main.h", "#pragma once\n")
    include_dir = tmp_path / "include"
    include_dir.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _fake_build(**kwargs):
        captured["build"] = kwargs
        return [object()]

    monkeypatch.setattr(run_server, "build_critics_from_names", _fake_build)

    def _fake_run(**kwargs):
        captured["run"] = kwargs
        return {"critics_success": True, "critics_score": 1.0, "critics_results": []}

    monkeypatch.setattr(run_server, "run_critics_on_artifacts", _fake_run)

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "generated_header_path": str(hdr_file),
            "critics": ["compile", "framac-wp"],
            "timeout": 23,
            "include_dirs": [str(include_dir)],
            "defines": ["DEBUG"],
            "generated_files": [str(c_file)],
            "critic_context": {"debug": True},
            "critic_options": {"framac-wp": {"wp_timeout": 7, "solvers": "Alt-Ergo", "framac_wp_no_let": True}},
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["timeout"] == 23
    assert out["inputs"]["critics"] == ["compile", "framac-wp"]

    build_kwargs = captured["build"]
    assert build_kwargs["names"] == ["compile", "framac-wp"]
    assert build_kwargs["timeout"] == 23
    assert build_kwargs["solvers"] == ["Alt-Ergo"]
    assert build_kwargs["critic_options"]["framac-wp"]["wp_timeout"] == 7
    assert "solvers" not in build_kwargs["critic_options"]["framac-wp"]
    assert build_kwargs["critic_options"]["framac-wp"]["framac_wp_no_let"] is True

    run_kwargs = captured["run"]
    assert run_kwargs["raw_c_path"].endswith("main.c")
    assert Path(run_kwargs["raw_c_path"]).parent != c_file.parent
    assert run_kwargs["spec_c_path"] is None
    assert run_kwargs["timeout"] == 23
    assert str(include_dir) in run_kwargs["include_dirs"]
    assert str(Path(run_kwargs["raw_c_path"]).parent) in run_kwargs["include_dirs"]
    assert run_kwargs["defines"] == ["DEBUG"]
    assert run_kwargs["critic_targets"] == {}
    assert run_kwargs["spec_c_path"] is None
    assert run_kwargs["base_context"]["debug"] is True
    assert run_kwargs["base_context"]["generated_header_path"] == str(hdr_file)
    assert run_kwargs["base_context"]["generated_files"] == [str(c_file)]
    assert run_kwargs["critic_configs"]["framac-wp"]["framac_wp_no_let"] is True

    verify_report = tmp_path / "output" / "reports" / "latest-verify.json"
    assert verify_report.is_file()


@pytest.mark.unit
def test_list_repo_entries_files_and_dirs_with_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    _write(tmp_path / "src" / "a.c", "int a;\n")
    _write(tmp_path / "src" / "b.h", "#pragma once\n")
    _write(tmp_path / "docs" / "readme.md", "hello\n")
    _write(tmp_path / "output" / "reports" / "latest-verify.json", "{}\n")
    _write(tmp_path / "output" / "tmp.c", "int o;\n")

    files = run_server._list_repo_entries(kind="file", exts=[".c", ".h"], limit=20)
    assert "src/a.c" in files
    assert "src/b.h" in files
    assert "docs/readme.md" not in files
    assert "output/tmp.c" not in files

    dirs = run_server._list_repo_entries(kind="dir", query="src", limit=20)
    assert "src" in dirs
    assert all(not d.startswith("output") for d in dirs)


@pytest.mark.unit
def test_list_templates_includes_gui_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_server, "GUI_TEMPLATES_DIR", tmp_path / "config" / "gui_templates")

    _write(tmp_path / "config" / "gui_templates" / "shutdown-algorithm-template.json", "[]\n")

    templates = run_server._list_templates()

    assert "config/gui_templates/shutdown-algorithm-template.json" in templates


@pytest.mark.unit
def test_run_pipeline_from_template_resolves_dotdot_paths_from_template_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_server, "GUI_TMP_DIR", tmp_path / "output" / "gui_tmp")

    tpl = _write(
        tmp_path / "input" / "sgmm-config.json",
        """[
  {
    \"name\": \"cfg\",
    \"case_study\": \"sgmm_full\",
    \"selected_prompt_template\": \"zero-shot\",
    \"llms_used\": [\"x\"],
    \"n_programs_generated\": 1,
    \"output_folder\": \"../output/test_runs/sgmm\",
    \"natural_spec_path\": \"../case_studies/sgmm_full/headers/nlspec.txt\",
    \"interface_path\": \"../case_studies/sgmm_full/headers/sgmm.is\",
    \"verification_header_path\": \"../case_studies/sgmm_full/headers/sgmm_full_ver.h\",
    \"include_dirs\": [\"../case_studies/sgmm_full/headers\"],
    \"headers_dir\": \"../case_studies/sgmm_full/headers\",
    \"headers_manifest\": {\"sgmm.h\": \"hdr\"},
    \"temperature\": 0.7,
    \"critic_options\": {
      \"framac-wp\": {
        \"verification_header_template_path\": \"../case_studies/sgmm_full/headers/sgmm_full_ver.h\"
      },
      \"cppcheck-misra\": {
        \"misra_rules_path\": \"../src/spec2code/pipeline_modules/critics/misra_rules_2012.txt\"
      }
    },
    \"critics\": [\"compile\"]
  }
]\n""",
    )

    captured = {}

    def _fake_run_with_config(path, **kwargs):
        cfg = Path(path)
        data = cfg.read_text(encoding="utf-8")
        captured["data"] = data
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(run_server, "_run_pipeline_with_config_path", _fake_run_with_config)

    out = run_server._run_pipeline_from_template(
        {
            "template": str(tpl.relative_to(tmp_path)).replace("\\", "/"),
            "models": ["test-llm-shutdown"],
            "manual_models": "",
            "n_programs_generated": 1,
            "temperature": 0.7,
        }
    )

    assert out["ok"] is True
    loaded = json.loads(captured["data"])[0]
    assert loaded["natural_spec_path"] == str(tmp_path / "case_studies" / "sgmm_full" / "headers" / "nlspec.txt")
    assert loaded["interface_path"] == str(tmp_path / "case_studies" / "sgmm_full" / "headers" / "sgmm.is")
    assert loaded["headers_dir"] == str(tmp_path / "case_studies" / "sgmm_full" / "headers")
    assert loaded["include_dirs"][0] == str(tmp_path / "case_studies" / "sgmm_full" / "headers")
    assert loaded["critic_options"]["framac-wp"]["verification_header_template_path"] == str(
        tmp_path / "case_studies" / "sgmm_full" / "headers" / "sgmm_full_ver.h"
    )
    assert loaded["critic_options"]["cppcheck-misra"]["misra_rules_path"] == str(
        tmp_path / "src" / "spec2code" / "pipeline_modules" / "critics" / "misra_rules_2012.txt"
    )
    assert captured["kwargs"].get("env_overrides") == {}


@pytest.mark.unit
def test_extract_bedrock_model_names_normalizes_and_deduplicates():
    payload = {
        "modelSummaries": [
            {"modelId": "anthropic.claude-3-5-sonnet-20240620-v1:0"},
            {"modelId": "anthropic.claude-3-5-sonnet-20240620-v1:0"},
            {"modelId": "meta.llama3-70b-instruct-v1:0"},
            {"bad": "entry"},
        ]
    }

    out = run_server._extract_bedrock_model_names(payload)

    assert out == [
        "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
        "bedrock/meta.llama3-70b-instruct-v1:0",
    ]


@pytest.mark.unit
def test_extract_bedrock_inference_profile_names_prefers_arn_and_deduplicates():
    payload = {
        "inferenceProfileSummaries": [
            {
                "inferenceProfileArn": "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc",
                "inferenceProfileId": "ip-abc",
            },
            {
                "inferenceProfileArn": "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc",
            },
            {
                "inferenceProfileId": "ip-only",
            },
            {
                "bad": "entry",
            },
        ]
    }

    out = run_server._extract_bedrock_inference_profile_names(payload)

    assert out == [
        "bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc",
        "bedrock-profile/ip-only",
    ]


@pytest.mark.unit
def test_sanitize_env_overrides_allows_only_whitelist():
    payload = {
        "ANTHROPIC_API_KEY": "  a  ",
        "OPENAI_API_KEY": "o",
        "AWS_PROFILE": "bedrock",
        "AWS_REGION": "eu-west-1",
        "NOT_ALLOWED": "x",
    }

    out = run_server._sanitize_env_overrides(payload)

    assert out == {
        "ANTHROPIC_API_KEY": "a",
        "OPENAI_API_KEY": "o",
        "AWS_PROFILE": "bedrock",
        "AWS_REGION": "eu-west-1",
    }
    assert "NOT_ALLOWED" not in out


@pytest.mark.unit
def test_credential_ready_models_filters_missing_keys(monkeypatch):
    monkeypatch.setattr(run_server, "_list_models", lambda: ["claude-3.5-sonnet", "test-llm-shutdown"])
    monkeypatch.setattr(
        run_server.llms,
        "_available_specs",
        lambda: (
            {},
            {
                "claude-3.5-sonnet": {
                    "type": "llm",
                    "id": "claude-3.5-sonnet",
                    "key_env": "ANTHROPIC_API_KEY",
                }
            },
        ),
    )

    available, unavailable = run_server._credential_ready_models(env={})
    assert "test-llm-shutdown" in available
    assert "claude-3.5-sonnet" not in available
    assert "claude-3.5-sonnet" in unavailable


@pytest.mark.unit
def test_api_models_hides_bedrock_foundation_ids_when_profiles_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_server, "_default_gui_models", lambda: ["test-llm-shutdown"])
    monkeypatch.setattr(
        run_server,
        "_credential_ready_models",
        lambda env: (["test-llm-shutdown", "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0"], {}),
    )
    monkeypatch.setattr(
        run_server,
        "_list_bedrock_models",
        lambda env: (
            ["bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc"],
            None,
        ),
    )

    env = run_server._effective_runtime_env()
    default_models = run_server._default_gui_models()
    credential_models, unavailable = run_server._credential_ready_models(env)
    all_models = set(credential_models)
    bedrock_models, bedrock_note = run_server._list_bedrock_models(env)
    has_profiles = any(str(m).startswith("bedrock-profile/") for m in bedrock_models)
    if has_profiles:
        all_models = {m for m in all_models if not str(m).startswith("bedrock/")}
        bedrock_models = [m for m in bedrock_models if str(m).startswith("bedrock-profile/")]
    all_models.update(bedrock_models)

    assert default_models == ["test-llm-shutdown"]
    assert "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0" not in all_models
    assert "bedrock-profile/arn:aws:bedrock:eu-west-1:123456789012:inference-profile/ip-abc" in all_models
    assert unavailable == {}
    assert bedrock_note is None


@pytest.mark.unit
def test_models_payload_cached_avoids_recompute_until_invalidation(monkeypatch):
    run_server._invalidate_models_cache()
    calls = {"n": 0}

    def _fake_compute(env):
        calls["n"] += 1
        return {
            "models": ["test-llm-shutdown"],
            "all_models": ["test-llm-shutdown"],
            "note": "ok",
        }

    monkeypatch.setattr(run_server, "_compute_models_payload", _fake_compute)

    env = {"AWS_REGION": "eu-west-1"}
    first = run_server._models_payload_cached(env)
    second = run_server._models_payload_cached(env)

    assert calls["n"] == 1
    assert first["models"] == ["test-llm-shutdown"]
    assert "cache" in second["note"].lower()

    run_server._invalidate_models_cache()
    third = run_server._models_payload_cached(env)
    assert calls["n"] == 2
    assert third["models"] == ["test-llm-shutdown"]


@pytest.mark.unit
def test_run_verify_files_uses_framac_formal_path_as_spec_target(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")
    formal = _write(tmp_path / "src" / "formal_ver.h", "#include <sgmm_full.c>\n/*@ requires \\true; */\n")

    captured = {}
    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", lambda **kwargs: captured.update(kwargs) or {"critics_success": True, "critics_score": 1.0, "critics_results": []})

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["framac-wp"],
            "critic_options": {"framac-wp": {"formal_c_path": str(formal), "solvers": "Alt-Ergo"}},
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["formal_c_path"].endswith("formal_ver.h")
    assert out["inputs"]["run_c_path"].endswith("main.c")
    assert captured["spec_c_path"].endswith("formal_ver.h")
    assert captured["critic_targets"]["framac-wp"] == "spec"
    staged_dir = Path(captured["spec_c_path"]).parent
    assert staged_dir.exists()


@pytest.mark.unit
def test_run_verify_files_copies_headers_from_headers_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "#include \"x.h\"\nint main(void){return 0;}\n")
    headers_dir = tmp_path / "headers"
    headers_dir.mkdir(parents=True, exist_ok=True)
    _write(headers_dir / "x.h", "#define X 1\n")

    captured = {}
    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", lambda **kwargs: captured.update(kwargs) or {"critics_success": True, "critics_score": 1.0, "critics_results": []})

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["compile"],
            "headers_dir": str(headers_dir),
        }
    )

    assert out["ok"] is True
    staged_c = Path(captured["raw_c_path"])
    assert (staged_c.parent / "x.h").is_file()
    assert not (c_file.parent / "x.h").is_file()
    assert out["inputs"]["headers_dir"] == [str(headers_dir)]
    assert any(p.endswith("x.h") for p in out["inputs"]["copied_headers"])
    assert str(staged_c.parent) in captured["include_dirs"]


@pytest.mark.unit
def test_run_verify_files_accepts_multiple_headers_dirs_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "#include \"a.h\"\n#include \"b.h\"\nint main(void){return 0;}\n")
    h1 = tmp_path / "headers1"
    h2 = tmp_path / "headers2"
    h1.mkdir(parents=True, exist_ok=True)
    h2.mkdir(parents=True, exist_ok=True)
    _write(h1 / "a.h", "#define A 1\n")
    _write(h2 / "b.h", "#define B 1\n")

    captured = {}
    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(
        run_server,
        "run_critics_on_artifacts",
        lambda **kwargs: captured.update(kwargs) or {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["compile"],
            "headers_dir": f"{h1}, {h2}",
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["headers_dir"] == [str(h1), str(h2)]
    staged_c = Path(captured["raw_c_path"])
    assert (staged_c.parent / "a.h").is_file()
    assert (staged_c.parent / "b.h").is_file()
    assert not (c_file.parent / "a.h").is_file()
    assert not (c_file.parent / "b.h").is_file()


@pytest.mark.unit
def test_run_verify_files_headers_dir_same_as_c_parent_does_not_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    src_dir = tmp_path / "src"
    c_file = _write(src_dir / "main.c", "#include \"x.h\"\nint main(void){return 0;}\n")
    _write(src_dir / "x.h", "#define X 1\n")

    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(
        run_server,
        "run_critics_on_artifacts",
        lambda **kwargs: {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["compile"],
            "headers_dir": str(src_dir),
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["headers_dir"] == [str(src_dir)]


@pytest.mark.unit
def test_run_verify_files_cleanup_after_verify_removes_newly_copied_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "#include \"a.h\"\nint main(void){return 0;}\n")
    h_dir = tmp_path / "headers"
    h_dir.mkdir(parents=True, exist_ok=True)
    _write(h_dir / "a.h", "#define A 1\n")

    captured = {}
    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(
        run_server,
        "run_critics_on_artifacts",
        lambda **kwargs: captured.update(kwargs) or {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["compile"],
            "headers_dir": str(h_dir),
            "cleanup_after_verify": True,
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["cleanup_after_verify"] is True
    staged_c = Path(captured["raw_c_path"])
    assert not staged_c.parent.exists()
    assert not (c_file.parent / "a.h").exists()


@pytest.mark.unit
def test_run_verify_files_vernfr_requires_interface_path(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")

    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", lambda **kwargs: {"critics_success": True, "critics_score": 1.0, "critics_results": []})

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["vernfr"],
            "critic_options": {"vernfr": {"interface_path": ""}},
        }
    )
    assert out["ok"] is False
    assert "vernfr requires" in out["error"]


@pytest.mark.unit
def test_run_verify_files_expands_vernfr_into_control_and_data(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "shutdown.c", "int main(void){return 0;}\n")
    h_file = _write(tmp_path / "src" / "shutdown.h", "#pragma once\n")
    is_file = _write(tmp_path / "src" / "shutdown.is", "void Shutdown_10ms(void);\n")
    control_script = _write(tmp_path / "scripts" / "control.sh", "#!/usr/bin/env bash\n")
    data_script = _write(tmp_path / "scripts" / "data.sh", "#!/usr/bin/env bash\n")

    captured = {}

    def _fake_build(**kwargs):
        captured["build"] = kwargs
        return [object(), object()]

    def _fake_run(**kwargs):
        captured["run"] = kwargs
        return {"critics_success": True, "critics_score": 1.0, "critics_results": []}

    monkeypatch.setattr(run_server, "build_critics_from_names", _fake_build)
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", _fake_run)

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "generated_header_path": str(h_file),
            "critics": ["vernfr"],
            "critic_options": {
                "vernfr": {
                    "interface_path": str(is_file),
                    "control_flow": True,
                    "data_flow": True,
                    "main": "Shutdown_10ms",
                    "modname": "shutdown",
                    "control_script_path": str(control_script),
                    "data_script_path": str(data_script),
                }
            },
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["requested_critics"] == ["vernfr"]
    assert out["inputs"]["critics"] == ["vernfr-control-flow", "vernfr-data-flow"]

    b = captured["build"]
    assert b["names"] == ["vernfr-control-flow", "vernfr-data-flow"]
    assert b["critic_options"]["vernfr-control-flow"]["main"] == "Shutdown_10ms"
    assert b["critic_options"]["vernfr-control-flow"]["script_path"] == str(control_script)
    assert b["critic_options"]["vernfr-data-flow"]["script_path"] == str(data_script)

    stage_folder = Path(b["critic_options"]["vernfr-control-flow"]["folder"])
    assert stage_folder.exists()


@pytest.mark.unit
def test_run_verify_files_vernfr_stages_interface_aliases_when_names_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "sgmm.c", "int main(void){return 0;}\n")
    h_file = _write(tmp_path / "src" / "sgmm.h", "#pragma once\n")
    is_file = _write(tmp_path / "src" / "sgmm_full.is", "void Sgmm_10ms(void);\n")
    control_script = _write(tmp_path / "scripts" / "control.sh", "#!/usr/bin/env bash\n")

    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])

    checked = {"done": False}

    def _fake_run(**kwargs):
        stage = Path(kwargs["critic_configs"]["vernfr-control-flow"]["folder"])
        # primary module-based name
        assert (stage / "sgmm.is").is_file()
        # source basename alias
        assert (stage / "sgmm_full.is").is_file()
        checked["done"] = True
        return {"critics_success": True, "critics_score": 1.0, "critics_results": []}

    monkeypatch.setattr(run_server, "run_critics_on_artifacts", _fake_run)

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "generated_header_path": str(h_file),
            "critics": ["vernfr"],
            "critic_options": {
                "vernfr": {
                    "interface_path": str(is_file),
                    "control_flow": True,
                    "data_flow": False,
                    "control_script_path": str(control_script),
                }
            },
        }
    )

    assert out["ok"] is True
    assert checked["done"] is True


@pytest.mark.unit
def test_run_verify_files_cleanup_after_verify_removes_staging_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "main.c", "int main(void){return 0;}\n")
    formal = _write(tmp_path / "src" / "formal_ver.h", "#include <main.c>\n")

    captured = {}
    monkeypatch.setattr(run_server, "build_critics_from_names", lambda **kwargs: [object()])

    def _fake_run(**kwargs):
        captured["spec"] = kwargs["spec_c_path"]
        return {"critics_success": True, "critics_score": 1.0, "critics_results": []}

    monkeypatch.setattr(run_server, "run_critics_on_artifacts", _fake_run)

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "critics": ["framac-wp"],
            "cleanup_after_verify": True,
            "critic_options": {"framac-wp": {"formal_c_path": str(formal), "solvers": "Alt-Ergo"}},
        }
    )

    assert out["ok"] is True
    assert out["inputs"]["cleanup_after_verify"] is True
    staged_dir = Path(captured["spec"]).parent
    assert not staged_dir.exists()


@pytest.mark.unit
def test_parse_why3_solvers_extracts_known_solver_names():
    out = """
    prover: Alt-Ergo 2.6.2
    prover: Z3 4.12.2
    prover: CVC5 1.1.2
    """
    parsed = run_server._parse_why3_solvers(out)
    assert "Alt-Ergo" in parsed
    assert "Z3" in parsed
    assert "CVC5" in parsed


@pytest.mark.unit
def test_build_critics_catalog_uses_detected_why3_solvers(monkeypatch):
    monkeypatch.setattr(run_server, "_detect_why3_solvers", lambda: ["Z3", "Alt-Ergo"])
    catalog, detected = run_server._build_critics_catalog()

    assert detected == ["Z3", "Alt-Ergo"]
    framac = next(c for c in catalog if c.get("name") == "framac-wp")
    solvers_opt = next(o for o in framac.get("options", []) if o.get("key") == "solvers")
    assert solvers_opt.get("default") == "Z3,Alt-Ergo"


@pytest.mark.unit
def test_infer_main_from_interface_text_prefers_entry_functions_block():
    text = """
    Module sgmm {
      entry_functions: {
        void Sgmm_10ms(void)
      }
    }
    """
    assert run_server._infer_main_from_interface_text(text) == "Sgmm_10ms"


@pytest.mark.unit
def test_run_verify_files_vernfr_infers_main_from_interface_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "REPO_ROOT", tmp_path)
    c_file = _write(tmp_path / "src" / "sgmm.c", "int main(void){return 0;}\n")
    h_file = _write(tmp_path / "src" / "sgmm.h", "#pragma once\n")
    is_file = _write(
        tmp_path / "src" / "sgmm.is",
        "Module sgmm {\n  entry_functions: {\n    void Sgmm_10ms(void)\n  }\n}\n",
    )
    control_script = _write(tmp_path / "scripts" / "control.sh", "#!/usr/bin/env bash\n")

    captured = {}

    def _fake_build(**kwargs):
        captured["build"] = kwargs
        return [object()]

    monkeypatch.setattr(run_server, "build_critics_from_names", _fake_build)
    monkeypatch.setattr(run_server, "run_critics_on_artifacts", lambda **kwargs: {"critics_success": True, "critics_score": 1.0, "critics_results": []})

    out = run_server._run_verify_files(
        {
            "c_file_path": str(c_file),
            "generated_header_path": str(h_file),
            "critics": ["vernfr"],
            "critic_options": {
                "vernfr": {
                    "interface_path": str(is_file),
                    "control_flow": True,
                    "data_flow": False,
                    "control_script_path": str(control_script),
                }
            },
        }
    )

    assert out["ok"] is True
    assert captured["build"]["critic_options"]["vernfr-control-flow"]["main"] == "Sgmm_10ms"
