"""Opt-in browser integration: SPEC2CODE_BROWSER_TESTS=1 pytest .../test_browser_workflows.py."""
import json
import os
import threading
from pathlib import Path

import pytest

from spec2code.gui import report, run_server
from spec2code.workspace import apply_project_defaults


@pytest.mark.e2e
@pytest.mark.skipif(os.getenv("SPEC2CODE_BROWSER_TESTS") != "1", reason="Opt-in Playwright browser test")
def test_import_select_run_and_inspect_report(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace"), "SPEC2CODE_OUTPUT_ROOT": str(tmp_path / "output")}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(run_server, "_effective_runtime_env", lambda extra=None: {**env, **(extra or {})})
    monkeypatch.setattr(run_server, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(run_server, "REPORTS_DIR", tmp_path / "output/reports")
    monkeypatch.setattr(run_server, "GUI_TMP_DIR", tmp_path / "output/gui_tmp")
    monkeypatch.setattr(run_server, "_MODELS_CACHE", {"by_key": {}})
    monkeypatch.setattr(run_server, "_discover_provider_models", lambda env: (["openai/gpt-5", "openai/text-embedding-3-small", "vllm/org/code"], []))
    monkeypatch.setattr(run_server, "_credential_ready_models", lambda env: ([], {}))
    monkeypatch.setattr(run_server, "_list_bedrock_models", lambda env, **kwargs: ([], None))
    monkeypatch.setattr(run_server, "_detect_why3_solvers", lambda: [])
    submitted = []

    def start_job(*, config_path, runtime_env):
        config = json.loads(config_path.read_text(encoding="utf-8"))[0]
        submitted.append(apply_project_defaults(config, base_dir=config_path.parent, repo_root=run_server.REPO_ROOT, env=runtime_env))
        return "browser-test"

    monkeypatch.setattr(run_server, "_start_pipeline_job", start_job)
    monkeypatch.setattr(run_server, "_run_job_status", lambda run_id: {"ok": True, "done": True, "returncode": 0})
    project_dir = tmp_path / "controller"
    (project_dir / "headers/nested").mkdir(parents=True)
    (project_dir / "my requirements.md").write_text("Control temperature")
    (project_dir / "controller.is").write_text("module controller")
    (project_dir / "headers/types.h").write_text("typedef int value_t;")
    (project_dir / "headers/nested/constants.h").write_text("#define LIMIT 5")

    data = {"critics_success": False, "critics_results": [
        {"tool": "compile", "success": True, "score": 1, "elapsed_time_s": 0.05, "findings": []},
        {"tool": "framac-wp", "success": False, "score": 0.75, "metrics": {"total_goals": 4, "proved_goals": 3}, "findings": []},
    ], "generation_attempts": [{"critics_results": [{"success": False}], "total_elapsed_time_attempt": 1}]}
    sample = tmp_path / "output/model/sample_000/output.json"
    sample.parent.mkdir(parents=True)
    sample.write_text(json.dumps(data))
    report.render_last_run_report(latest_output_json=sample)

    server = run_server.ThreadingHTTPServer(("127.0.0.1", 0), run_server._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel=os.getenv("SPEC2CODE_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.route("https://cdnjs.cloudflare.com/**", lambda route: route.abort())
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{base}/runner")
            model = page.locator('#modelsSelect input[value="openai/gpt-5"]')
            model.check()
            assert page.locator('#modelsSelect input[value="openai/text-embedding-3-small"]').is_disabled()
            page.locator("#modelSearch").fill("vllm")
            page.locator('#modelsSelect input[value="vllm/org/code"]').check()
            page.locator("#modelSearch").fill("")
            assert model.is_checked()
            page.locator("#refreshModelsBtn").click()
            playwright.expect(page.locator("#modelSelectionSummary")).to_contain_text("2 selected")
            page.locator("#projectFolderInput").set_input_files(project_dir)
            playwright.expect(page.locator("#projectImportReview")).to_be_visible()
            assert page.locator("#importSpec").input_value() == "my requirements.md"
            assert page.locator("#importHeaders").input_value() == "headers"
            page.locator("#confirmProjectImport").click()
            playwright.expect(page.locator("#status")).to_contain_text("Imported project")
            page.locator("#runBtn").click()
            playwright.expect(page.locator("#status")).to_contain_text("Run completed")
            assert submitted[0]["llms_used"] == ["openai/gpt-5", "vllm/org/code"]
            assert Path(submitted[0]["natural_spec_path"]).name == "my requirements.md"
            assert "nested/constants.h" in submitted[0]["headers_manifest"]

            page.goto(f"{base}/results")
            playwright.expect(page.locator("#runTitle")).to_contain_text("Needs attention")
            playwright.expect(page.locator(".analytics-figure")).to_have_count(11)
            assert "3 / 4 proved" in page.locator("#evidenceSummary").inner_text()
            with page.expect_download() as download:
                page.locator(".analytics-figure button").first.click()
            assert download.value.suggested_filename == "critic-outcomes.svg"
            assert download.value.path()
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(tmp_path / "results.png"), full_page=True)

            page.goto((tmp_path / "output/reports/last-run.html").as_uri())
            playwright.expect(page.locator(".analytics-figure")).to_have_count(11)
            assert page.locator("#tab-analytics").is_visible()
            page.goto(f"{base}/verify")
            page.locator(".picker-btn").first.click()
            playwright.expect(page.locator("#pickerUpload")).to_be_visible()
            page.keyboard.press("Escape")
            assert not page.locator("#filePickerModal").is_visible()
            assert not errors
            page.wait_for_load_state("networkidle")
            page.context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
