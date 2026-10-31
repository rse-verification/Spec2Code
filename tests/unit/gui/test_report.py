import json

from spec2code.gui import report


def test_offline_report_contains_analytics_assets_and_uses_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEC2CODE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.delenv("SPEC2CODE_OUTPUT_ROOT", raising=False)
    sample = tmp_path / "output.json"
    sample.write_text(json.dumps({"critics_results": [], "code": "</script>"}), encoding="utf-8")
    report.render_last_run_report(latest_output_json=sample)
    directory = tmp_path / "workspace" / "output" / "reports"
    html = (directory / "last-run.html").read_text(encoding="utf-8")
    assert 'id="criticAnalytics"' in html
    assert "<\\/script>" in html
    for asset in ("analytics.js", "analytics.css", "app.js", "styles.css"):
        assert (directory / asset).is_file()
        assert asset in html
