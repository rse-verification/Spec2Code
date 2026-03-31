from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spec2code.core import pipeline_executor


class _FakeLLM:
    def prompt(self, filled_prompt, stream=False, temperature=0.7):
        return {"raw": "ok", "prompt": filled_prompt, "temperature": temperature}


class _FakeRuntime:
    def __init__(self, model_names):
        self.llms_available = {name: _FakeLLM() for name in model_names}


def _make_cfg(tmp_path: Path, *, n_programs: int = 1, with_module_state: bool = False):
    headers_dir = tmp_path / "headers"
    headers_dir.mkdir(parents=True, exist_ok=True)
    (headers_dir / "types.h").write_text("typedef int tI32;\n", encoding="utf-8")

    interface_path = tmp_path / "shutdown_algorithm.is"
    interface_path.write_text("void ShutdownAlgorithm_10ms(void);\n", encoding="utf-8")

    csi = SimpleNamespace(
        input_natural_language_specification="nlspec",
        input_interface="void ShutdownAlgorithm_10ms(void);\n",
        input_type_definitions="typedef int tI32;",
        input_headers_json="[]",
        input_types_header_filename="types.h",
        headers_dir=str(headers_dir),
        module_state_header_filename="module_state_and_constants.h" if with_module_state else None,
        module_state_header_content="#define X 1\n" if with_module_state else None,
    )

    return SimpleNamespace(
        name="cfg-name",
        case_study="shutdown_algorithm",
        selected_prompt_template="zero-shot",
        llms_used=["test-llm-shutdown"],
        n_programs_generated=n_programs,
        output_folder=str(tmp_path / "output"),
        temperature=0.4,
        headers_dir=str(headers_dir),
        include_dirs=[str(headers_dir)],
        critics=["compile"],
        critics_instances=[SimpleNamespace(name="compile", run=lambda inp: inp)],
        timeout_s=77,
        debug=False,
        copy_headers_to_output=True,
        case_study_inputs=csi,
        filled_prompt="PROMPT",
        interface_path=str(interface_path),
        critic_context={"framac_wp_no_let": True},
        critic_options={"framac-wp": {"verification_header_template_path": str(headers_dir / "ver.h")}},
    )


@pytest.mark.unit
def test_execute_pipeline_prepared_validates_filled_prompt(tmp_path):
    cfg = _make_cfg(tmp_path)
    cfg.filled_prompt = ""
    runtime = _FakeRuntime(cfg.llms_used)

    with pytest.raises(RuntimeError, match="filled_prompt"):
        pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)


@pytest.mark.unit
def test_execute_pipeline_prepared_validates_critics_presence(tmp_path):
    cfg = _make_cfg(tmp_path)
    cfg.critics_instances = None
    cfg.critics = None
    runtime = _FakeRuntime(cfg.llms_used)

    with pytest.raises(RuntimeError, match="critics instances"):
        pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)


@pytest.mark.unit
def test_execute_pipeline_prepared_validates_interface_not_empty(tmp_path):
    cfg = _make_cfg(tmp_path)
    cfg.case_study_inputs.input_interface = "\n"
    runtime = _FakeRuntime(cfg.llms_used)

    with pytest.raises(ValueError, match="input_interface is empty"):
        pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)


@pytest.mark.unit
def test_execute_pipeline_prepared_happy_path_writes_outputs_and_copies_files(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    runtime = _FakeRuntime(cfg.llms_used)

    monkeypatch.setattr(
        pipeline_executor,
        "extract_llm_response_info",
        lambda output_llm: {"code": "int main(void){return 0;}\n", "generated_header": "#pragma once\n"},
    )

    seen = {}

    def _fake_process_llm_generated_code(**kwargs):
        seen["kwargs"] = kwargs
        return {"verify_success": True, "critics_success": True, "critics_score": 1.0, "findings": []}

    monkeypatch.setattr(pipeline_executor, "process_llm_generated_code", _fake_process_llm_generated_code)

    pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)

    llm_dir = Path(cfg.output_folder) / "test-llm-shutdown"
    sample_dir = llm_dir / "sample_000"
    assert (llm_dir / "prompt.txt").is_file()
    assert (sample_dir / "output.json").is_file()
    assert (llm_dir / "output.json").is_file()
    assert (Path(cfg.output_folder) / "output_pipeline.json").is_file()

    # copied headers + interface into sample folder
    assert (sample_dir / "types.h").is_file()
    assert (sample_dir / "shutdown_algorithm.is").is_file()

    settings = seen["kwargs"]["settings"]
    assert settings.timeout_s == 77
    assert settings.critic_context.get("framac_wp_no_let") is True
    assert settings.critic_options["framac-wp"]["verification_header_template_path"].endswith("ver.h")

    with (Path(cfg.output_folder) / "output_pipeline.json").open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["name"] == "cfg-name"
    assert "total_elapsed_time" in data


@pytest.mark.unit
def test_execute_pipeline_prepared_skips_processing_when_parser_returns_error(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path, n_programs=2)
    runtime = _FakeRuntime(cfg.llms_used)

    parsed = [
        {"error": "bad output", "raw_output": "x"},
        {"code": "int f(void){return 0;}\n", "generated_header": "#pragma once\n"},
    ]

    monkeypatch.setattr(pipeline_executor, "extract_llm_response_info", lambda output_llm: parsed.pop(0))

    calls = {"n": 0}

    def _fake_process_llm_generated_code(**kwargs):
        calls["n"] += 1
        return {"verify_success": True, "critics_success": True, "critics_score": 1.0, "findings": []}

    monkeypatch.setattr(pipeline_executor, "process_llm_generated_code", _fake_process_llm_generated_code)

    pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)

    assert calls["n"] == 1


@pytest.mark.unit
def test_execute_pipeline_prepared_applies_module_state_injection(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path, with_module_state=True)
    runtime = _FakeRuntime(cfg.llms_used)

    monkeypatch.setattr(
        pipeline_executor,
        "extract_llm_response_info",
        lambda output_llm: {"code": "int main(void){return 0;}\n", "generated_header": "#pragma once\n"},
    )

    injected = {"called": False}

    def _fake_inject(code, header_name, header_content):
        injected["called"] = True
        assert header_name == "module_state_and_constants.h"
        assert "#define X 1" in header_content
        return "/* injected */\n" + code

    monkeypatch.setattr(pipeline_executor, "_inject_module_state_constants", _fake_inject)

    seen = {}

    def _fake_process_llm_generated_code(**kwargs):
        seen["code"] = kwargs["generated_code"]
        return {"verify_success": True, "critics_success": True, "critics_score": 1.0, "findings": []}

    monkeypatch.setattr(pipeline_executor, "process_llm_generated_code", _fake_process_llm_generated_code)

    pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)

    assert injected["called"] is True
    assert seen["code"].startswith("/* injected */")


@pytest.mark.unit
def test_execute_pipeline_prepared_uses_interface_stem_for_generated_c_filename(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    cfg.case_study = "sgmm_full"
    cfg.interface_path = str(tmp_path / "sgmm.is")
    Path(cfg.interface_path).write_text("void Sgmm_10ms(void);\n", encoding="utf-8")

    runtime = _FakeRuntime(cfg.llms_used)

    monkeypatch.setattr(
        pipeline_executor,
        "extract_llm_response_info",
        lambda output_llm: {"code": "int main(void){return 0;}\n", "generated_header": "#pragma once\n"},
    )

    seen = {}

    def _fake_process_llm_generated_code(**kwargs):
        seen["file_path"] = kwargs["file_path"]
        return {"verify_success": True, "critics_success": True, "critics_score": 1.0, "findings": []}

    monkeypatch.setattr(pipeline_executor, "process_llm_generated_code", _fake_process_llm_generated_code)

    pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)

    assert Path(seen["file_path"]).name == "sgmm.c"


@pytest.mark.unit
def test_llm_output_dir_name_sanitizes_bedrock_profile_name_for_windows_fs():
    raw = "bedrock-profile/arn:aws:bedrock:eu-west-1:123:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0"
    out = pipeline_executor._llm_output_dir_name(raw)

    assert out
    assert len(out) <= 80
    assert ":" not in out
    assert "/" not in out and "\\" not in out


@pytest.mark.unit
def test_execute_pipeline_prepared_writes_output_txt_with_timing_metrics(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    runtime = _FakeRuntime(cfg.llms_used)

    monkeypatch.setattr(
        pipeline_executor,
        "extract_llm_response_info",
        lambda output_llm: {"code": "int main(void){return 0;}\n", "generated_header": "#pragma once\n"},
    )

    monkeypatch.setattr(
        pipeline_executor,
        "process_llm_generated_code",
        lambda **kwargs: {
            "verify_success": True,
            "critics_success": True,
            "critics_score": 1.0,
            "critics_results": [
                {
                    "tool": "compile",
                    "metrics": {
                        "elapsed_time_s": 1.1,
                        "process_real_s": 1.0,
                        "process_user_s": 0.6,
                        "process_sys_s": 0.2,
                    },
                }
            ],
        },
    )

    pipeline_executor.execute_pipeline_prepared(cfg, runtime=runtime)

    llm_dir = Path(cfg.output_folder) / pipeline_executor._llm_output_dir_name(cfg.llms_used[0])
    out_txt = llm_dir / "sample_000" / "output.txt"
    assert out_txt.is_file()
    content = out_txt.read_text(encoding="utf-8")
    assert "elapsed_time_s" in content
    assert "process_real_s" in content
    assert "process_user_s" in content
    assert "process_sys_s" in content
