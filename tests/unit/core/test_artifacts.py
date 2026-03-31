from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.core import artifacts


@pytest.mark.unit
def test_ensure_dir_creates_missing_directory(tmp_path):
    target = tmp_path / "new" / "dir"
    artifacts._ensure_dir(str(target))
    assert target.is_dir()


@pytest.mark.unit
def test_ensure_dir_replaces_file_with_directory(tmp_path):
    target = tmp_path / "blocked"
    target.write_text("x", encoding="utf-8")

    artifacts._ensure_dir(str(target))

    assert target.is_dir()


@pytest.mark.unit
def test_ensure_dir_raises_when_file_cannot_be_removed(tmp_path, monkeypatch):
    target = tmp_path / "blocked"
    target.write_text("x", encoding="utf-8")

    monkeypatch.setattr(artifacts.os, "remove", lambda p: (_ for _ in ()).throw(OSError("nope")))

    with pytest.raises(RuntimeError, match="Expected directory but found file"):
        artifacts._ensure_dir(str(target))


@pytest.mark.unit
def test_ensure_dir_retries_after_transient_parent_missing(tmp_path, monkeypatch):
    target = tmp_path / "a" / "b"
    real_makedirs = artifacts.os.makedirs
    calls = {"n": 0}

    def _flaky_makedirs(path, exist_ok=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError("transient parent visibility")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(artifacts.os, "makedirs", _flaky_makedirs)

    artifacts._ensure_dir(str(target))
    assert target.is_dir()


@pytest.mark.unit
def test_copy_tree_flat_copies_only_files_and_respects_extension_filter(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (src / "a.h").write_text("a", encoding="utf-8")
    (src / "b.c").write_text("b", encoding="utf-8")
    (src / "sub" / "c.h").write_text("c", encoding="utf-8")

    artifacts._copy_tree_flat(str(src), str(dst), extensions=[".h"])

    assert (dst / "a.h").is_file()
    assert not (dst / "b.c").exists()
    assert not (dst / "c.h").exists()


@pytest.mark.unit
def test_pipeline_settings_defaults_and_custom_values():
    s = artifacts.PipelineSettings()
    assert s.critic_targets["framac-wp"] == "raw"
    assert s.critic_context == {}
    assert s.critic_options == {}

    custom = artifacts.PipelineSettings(
        critic_targets={"compile": "spec"},
        critic_context={"x": 1},
        critic_options={"framac-wp": {"wp_timeout": 5}},
    )
    assert custom.critic_targets == {"compile": "spec"}
    assert custom.critic_context == {"x": 1}
    assert custom.critic_options["framac-wp"]["wp_timeout"] == 5


@pytest.mark.unit
def test_run_critics_compat_passes_spec_c_path_when_supported(monkeypatch):
    captured = {}

    def _fake_runner(*, critics, raw_c_path, compiled_output_path, remove_compiled, timeout,
                     include_dirs, critic_targets, base_context, spec_c_path):
        captured["spec_c_path"] = spec_c_path
        return {"ok": True}

    monkeypatch.setattr(artifacts, "run_critics_on_artifacts", _fake_runner)

    artifacts._run_critics_compat(
        critics=[],
        raw_c_path="raw.c",
        compiled_output_path="raw.out",
        remove_compiled=True,
        timeout=10,
        include_dirs=[],
        critic_targets={},
        base_context={},
    )

    assert "spec_c_path" in captured
    assert captured["spec_c_path"] is None


@pytest.mark.unit
def test_run_critics_compat_passes_spec_c_file_path_when_supported(monkeypatch):
    captured = {}

    def _fake_runner(*, critics, raw_c_path, compiled_output_path, remove_compiled, timeout,
                     include_dirs, critic_targets, base_context, spec_c_file_path):
        captured["spec_c_file_path"] = spec_c_file_path
        return {"ok": True}

    monkeypatch.setattr(artifacts, "run_critics_on_artifacts", _fake_runner)

    artifacts._run_critics_compat(
        critics=[],
        raw_c_path="raw.c",
        compiled_output_path="raw.out",
        remove_compiled=True,
        timeout=10,
        include_dirs=[],
        critic_targets={},
        base_context={},
    )

    assert captured["spec_c_file_path"] is None


@pytest.mark.unit
def test_verify_artifacts_maps_success_and_message(monkeypatch):
    monkeypatch.setattr(
        artifacts,
        "_run_critics_compat",
        lambda **kwargs: {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = artifacts.verify_artifacts(
        critics=[],
        paths=artifacts.ArtifactPaths(raw_c="raw.c", raw_h="raw.h", compiled_out="raw.out"),
        include_dirs=[],
        settings=artifacts.PipelineSettings(),
    )

    assert out["verify_success"] is True
    assert out["verify_message"] == "All critics passed."
    assert out["verify_elapsed_time"] >= 0.0


@pytest.mark.unit
def test_process_llm_generated_code_fails_when_c_write_fails(monkeypatch):
    monkeypatch.setattr(artifacts, "write_file", lambda *args, **kwargs: False)

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}",
        generated_header="#pragma once",
        file_path="x/main.c",
        include_dirs=[],
        critics=[],
    )

    assert "error" in out
    assert "Failed to write raw .c" in out["error"]


@pytest.mark.unit
def test_process_llm_generated_code_fails_when_header_missing(monkeypatch):
    monkeypatch.setattr(artifacts, "write_file", lambda *args, **kwargs: True)

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}",
        generated_header="   ",
        file_path="x/main.c",
        include_dirs=[],
        critics=[],
    )

    assert "error" in out
    assert "did not return a header" in out["error"]


@pytest.mark.unit
def test_process_llm_generated_code_fails_when_header_write_fails(monkeypatch):
    def _fake_write(path, content):
        return not str(path).endswith(".h")

    monkeypatch.setattr(artifacts, "write_file", _fake_write)

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}",
        generated_header="#pragma once",
        file_path="x/main.c",
        include_dirs=[],
        critics=[],
    )

    assert "error" in out
    assert "Failed to write header" in out["error"]


@pytest.mark.unit
def test_process_llm_generated_code_fails_when_verification_header_materialization_throws(tmp_path, monkeypatch):
    file_path = tmp_path / "out" / "main.c"
    tpl = tmp_path / "ver.h"
    tpl.write_text("x", encoding="utf-8")

    monkeypatch.setattr(artifacts, "write_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        artifacts,
        "_materialize_verification_header",
        lambda **kwargs: (_ for _ in ()).throw(OSError("copy fail")),
    )

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}",
        generated_header="#pragma once",
        file_path=str(file_path),
        verification_header_template_path=str(tpl),
        include_dirs=[],
        critics=[],
    )

    assert "error" in out
    assert "copy fail" in out["error"]


@pytest.mark.unit
def test_process_llm_generated_code_retargets_verification_header_include_to_generated_c(tmp_path, monkeypatch):
    file_path = tmp_path / "out" / "sgmm.c"
    tpl = tmp_path / "sgmm_full_ver.h"
    tpl.write_text('#include <sgmm_full.c>\n/*@ requires \true; */\n', encoding="utf-8")

    monkeypatch.setattr(
        artifacts,
        "run_critics_on_artifacts",
        lambda **kwargs: {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}\n",
        generated_header="#pragma once\n",
        file_path=str(file_path),
        verification_header_template_path=str(tpl),
        include_dirs=[],
        critics=[],
    )

    assert out["verify_success"] is True
    ver_path = Path(out["verification_header_path"])
    content = ver_path.read_text(encoding="utf-8")
    assert '#include "sgmm.c"' in content
    assert "sgmm_full.c" not in content


@pytest.mark.unit
def test_process_llm_generated_code_passes_context_targets_configs_and_maps_verify_fields(tmp_path, monkeypatch):
    file_path = tmp_path / "out" / "main.c"
    tpl = tmp_path / "ver.h"
    tpl.write_text("void f(void);\n", encoding="utf-8")

    captured = {}

    def _fake_run_critics_on_artifacts(**kwargs):
        captured.update(kwargs)
        return {"critics_success": False, "critics_score": 0.25, "critics_results": []}

    monkeypatch.setattr(artifacts, "run_critics_on_artifacts", _fake_run_critics_on_artifacts)

    settings = artifacts.PipelineSettings(
        timeout_s=12,
        remove_compiled=False,
        critic_targets={"compile": "raw", "framac-wp": "raw"},
        critic_context={"debug": False, "x": 1},
        critic_options={"framac-wp": {"wp_timeout": 8}},
    )

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}\n",
        generated_header="#pragma once\n",
        file_path=str(file_path),
        interface_text="void ShutdownAlgorithm_10ms(void);",
        verification_header_template_path=str(tpl),
        debug=True,
        include_dirs=[str(tmp_path / "inc")],
        critics=[object()],
        settings=settings,
    )

    assert out["write_success"] is True
    assert out["header_write_success"] is True
    assert out["verify_success"] is False
    assert out["verify_message"] == "At least one critic failed."
    assert out["verify_elapsed_time"] >= 0.0
    assert Path(out["verification_header_path"]).is_file()

    assert captured["timeout"] == 12
    assert captured["remove_compiled"] is False
    assert captured["critic_targets"]["framac-wp"] == "spec"
    # Original settings must stay unchanged
    assert settings.critic_targets["framac-wp"] == "raw"

    ctx = captured["base_context"]
    assert ctx["interface_text"].startswith("void ShutdownAlgorithm_10ms")
    # critic_context is merged after debug flag and can override
    assert ctx["debug"] is False
    assert ctx["x"] == 1
    assert "generated_header_path" in ctx

    assert captured["critic_configs"]["framac-wp"]["wp_timeout"] == 8


@pytest.mark.unit
def test_process_llm_generated_code_without_interface_or_debug_keeps_context_minimal(tmp_path, monkeypatch):
    file_path = tmp_path / "out" / "main.c"
    captured = {}

    monkeypatch.setattr(
        artifacts,
        "run_critics_on_artifacts",
        lambda **kwargs: captured.update(kwargs) or {"critics_success": True, "critics_score": 1.0, "critics_results": []},
    )

    out = artifacts.process_llm_generated_code(
        generated_code="int main(void){return 0;}\n",
        generated_header="#pragma once\n",
        file_path=str(file_path),
        interface_text=None,
        debug=False,
        include_dirs=[],
        critics=[],
        settings=artifacts.PipelineSettings(),
    )

    assert out["verify_success"] is True
    ctx = captured["base_context"]
    assert "interface_text" not in ctx
    assert "debug" not in ctx
    assert "generated_header_path" in ctx
