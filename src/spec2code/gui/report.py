from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)


def find_latest_sample_output(output_root: str) -> str | None:
    latest_path = None
    latest_mtime = -1.0

    for root, _, files in os.walk(output_root):
        if "output.json" not in files:
            continue

        base = os.path.basename(root)
        if not base.startswith("sample_"):
            continue

        path = os.path.join(root, "output.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path

    return latest_path


def write_last_run_html(*, index_path: Path, output_path: Path, data: dict, asset_version: str | None = None) -> None:
    with index_path.open("r", encoding="utf-8") as f:
        html = f.read()

    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("</script>", "<\\/script>")
    injection = f"<script>window.__PIPELINE_DATA__ = {payload};</script>\n"

    if "</head>" in html:
        html = html.replace("</head>", injection + "</head>", 1)
    else:
        html = injection + html

    if asset_version:
        html = html.replace('href="styles.css"', f'href="styles.css?v={asset_version}"')
        html = html.replace('src="app.js"', f'src="app.js?v={asset_version}"')

    with output_path.open("w", encoding="utf-8") as f:
        f.write(html)


def open_in_browser(url: str) -> bool:
    try:
        opened = webbrowser.open(url)
        if opened:
            return True
    except Exception:
        pass

    candidates = [
        ["wslview", url],
        ["xdg-open", url],
        ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"],
        ["cmd.exe", "/c", "start", "", url],
    ]

    for cmd in candidates:
        try:
            subprocess.run(cmd, check=False)
            return True
        except Exception:
            continue

    return False


def render_last_run_report(
    *,
    latest_output_json: Path,
    open_in_browser: bool = False,
) -> None:
    gui_dir = Path(__file__).resolve().parent
    repo_root = Path(__file__).resolve().parents[3]
    reports_dir = repo_root / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    index_path = gui_dir / "index.html"
    output_path = reports_dir / "last-run.html"

    if not index_path.exists():
        logger.warning("GUI index.html not found at %s", index_path)
        return

    try:
        with latest_output_json.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Keep report assets next to generated HTML so it works outside gui_dir.
        shutil.copy2(gui_dir / "styles.css", reports_dir / "styles.css")
        shutil.copy2(gui_dir / "app.js", reports_dir / "app.js")

        write_last_run_html(
            index_path=index_path,
            output_path=output_path,
            data=data,
            asset_version=str(int(time.time())),
        )

        if open_in_browser:
            url = output_path.resolve().as_uri()
            if globals()["open_in_browser"](url):
                logger.info("Opened GUI: %s", url)
            else:
                logger.info("Open this file manually: %s", output_path)
        else:
            logger.info("Report written to: %s", output_path)

    except Exception as exc:
        logger.exception("Failed to generate or open GUI report: %s", exc)
