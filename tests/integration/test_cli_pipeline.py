"""Exercise the real CLI, config loader, SDK, parser, executor and report writer.

Only model inference and (in portable cases) the external critic are fixtures.
The native case invokes a separate CLI process and real GCC.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from spec2code.cli import run_pipeline as cli
from spec2code.core import runner
from spec2code.pipeline_modules.critics.critics_registry import CRITIC_BUILDERS
from tests.support.assertions import assert_critic_result_shape

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def reply(value=42):
    return json.dumps({"c": f'#include "controller.h"\nint step(void) {{ return {value}; }}', "h": "int step(void);"})


@pytest.fixture
def model_server(monkeypatch):
    state = SimpleNamespace(replies=[reply()], requests=[], counts=defaultdict(int))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append(request)
            index = state.counts[request["model"]]
            state.counts[request["model"]] += 1
            text = state.replies[min(index, len(state.replies) - 1)]
            payload = {"id": "fixture", "object": "chat.completion", "created": 0, "model": request["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("VLLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("VLLM_API_KEY", "test-key")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class FixtureCritic:
    name = "fixture-check"

    def run(self, inp):
        source = Path(inp["c_file_path"])
        assert source.with_suffix(".h").read_text() == "int step(void);"
        success = "return 42;" in source.read_text()
        return {"tool": self.name, "success": success, "score": float(success), "summary": "Expected return value 42", "metrics": {}, "raw_output": "fixture evidence", "findings": [] if success else [{"tool": self.name, "severity": "error", "message": "Expected return value 42", "location": {"file": str(source), "line": 2}, "rule": "fixture.expected-return"}]}


@pytest.fixture
def pipeline_config(tmp_path, monkeypatch):
    project = tmp_path / "project with spaces"
    (project / "headers").mkdir(parents=True)
    (project / "nlspec.txt").write_text("step returns 42", encoding="utf-8")
    (project / "controller.is").write_text("module controller { entry_functions: { int step(void) } }", encoding="utf-8")
    monkeypatch.setenv("SPEC2CODE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("SPEC2CODE_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("SPEC2CODE_LLM_CONFIG", str(tmp_path / "no-custom-models.yaml"))
    monkeypatch.setattr(runner, "initialize_solvers", lambda: [])
    monkeypatch.setitem(CRITIC_BUILDERS, "fixture-check", lambda *args: FixtureCritic())
    config = {"project_dir": str(project), "case_study": "controller", "name": "smoke", "selected_prompt_template": "zero-shot", "llms_used": ["vllm/fixture-a"], "n_programs_generated": 1, "max_generation_iterations": 2, "output_folder": str(tmp_path / "generated"), "critics": ["fixture-check"]}
    path = tmp_path / "pipeline.json"
    return path, config


@pytest.mark.parametrize(("responses", "attempts", "success"), [
    ([reply()], 1, True),
    (["truncated model response", reply()], 2, True),
    ([reply(-1), reply()], 2, True),
    (["truncated model response"], 2, False),
    ([reply(-1)], 2, False),
])
def test_cli_to_report_and_repair_budget(pipeline_config, model_server, responses, attempts, success, monkeypatch):
    path, config = pipeline_config
    model_server.replies = responses
    path.write_text(json.dumps([config]), encoding="utf-8")
    monkeypatch.setattr("webbrowser.open", lambda *args: pytest.fail("--no-open-report must not launch a browser"))

    # Exit 0 means orchestration completed; the persisted verdict describes verification.
    assert cli.main(["--config", str(path), "--no-open-report"]) == 0
    assert len(model_server.requests) == attempts
    sample = next(Path(config["output_folder"]).glob("*/sample_000"))
    result = json.loads((sample / "output.json").read_text())
    assert result["critics_success"] is success
    assert result["generation_attempt_count"] == attempts
    assert len(result["generation_attempts"]) == attempts
    assert result["generation_stop_reason"] == ("all_critics_passed" if success else "max_generation_iterations_reached")
    assert result["exact_model_used"] == "vllm/fixture-a"
    for number in range(attempts):
        assert (sample / f"attempt_{number:03}/output.json").is_file()
    if result["critics_results"]:
        for critic in result["critics_results"]:
            assert_critic_result_shape(critic)
        assert Path(result["generated_file_path"]).is_file()
        assert Path(result["generated_header_path"]).is_file()
    if attempts > 1:
        repair = model_server.requests[1]["messages"][0]["content"]
        assert "Repair Objective" in repair
        assert ("truncated model response" if responses[0].startswith("truncated") else "Expected return value 42") in repair
    report = Path(os.environ["SPEC2CODE_OUTPUT_ROOT"]) / "reports/last-run.html"
    html = report.read_text(encoding="utf-8")
    assert "window.__PIPELINE_DATA__" in html
    assert '"critics_success": ' + str(success).lower() in html
    assert (report.parent / "analytics.js").is_file()
    assert (Path(config["output_folder"]) / "output_pipeline.json").is_file()


def test_cli_keeps_multiple_models_and_samples_separate(pipeline_config, model_server):
    path, config = pipeline_config
    config.update(llms_used=["vllm/fixture-a", "vllm/fixture-b"], n_programs_generated=2)
    path.write_text(json.dumps([config]), encoding="utf-8")
    assert cli.main(["-c", str(path), "--no-open-report"]) == 0
    samples = list(Path(config["output_folder"]).glob("*/sample_*/output.json"))
    assert len(samples) == 4
    assert dict(model_server.counts) == {"fixture-a": 2, "fixture-b": 2}
    assert all(json.loads(sample.read_text())["generation_attempt_count"] == 1 for sample in samples)


@pytest.mark.native
def test_real_cli_process_repairs_a_gcc_failure(pipeline_config, model_server, tmp_path):
    if os.name == "nt" or shutil.which("gcc") is None:
        pytest.skip("requires GCC and POSIX critic commands")
    path, config = pipeline_config
    config["critics"] = ["compile"]
    model_server.replies = [reply("missing_symbol"), reply()]
    path.write_text(json.dumps([config]), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path), "PYTHON_DOTENV_DISABLED": "1"}
    # Cold SDK imports on a Windows-mounted WSL filesystem can exceed a minute.
    completed = subprocess.run([sys.executable, "-m", "spec2code.cli.run_pipeline", "-c", str(path), "--no-open-report"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    sample = next(Path(config["output_folder"]).glob("*/sample_000/output.json"))
    result = json.loads(sample.read_text())
    assert result["generation_attempt_count"] == 2
    assert result["generation_attempts"][0]["critics_results"][0]["success"] is False
    assert result["critics_results"][0]["tool"] == "compile"
    assert_critic_result_shape(result["critics_results"][0])
    assert result["critics_success"] is True
    assert "missing_symbol" in model_server.requests[1]["messages"][0]["content"]
    assert (Path(env["SPEC2CODE_OUTPUT_ROOT"]) / "reports/last-run.html").is_file()
