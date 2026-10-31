from __future__ import annotations

import base64
import io
import json
import threading
import urllib.request
import zipfile
from pathlib import Path

import pytest

from spec2code.gui import run_server


def _create_project(root: Path, name: str = "demo") -> Path:
    project = root / name
    headers = project / "headers"
    headers.mkdir(parents=True)
    (project / "nlspec.txt").write_text("Requirement", encoding="utf-8")
    (project / f"{name}.is").write_text("interface", encoding="utf-8")
    (headers / "types.h").write_text("typedef int value_t;", encoding="utf-8")
    return project


def _zip_payload(files: dict[str, str]) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


@pytest.mark.unit
def test_import_project_folder_copies_into_managed_workspace(tmp_path):
    source = _create_project(tmp_path / "source", "demo")
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")}

    project = run_server._import_project_folder(source_path=str(source), runtime_env=env)

    destination = tmp_path / "workspace" / "projects" / "demo"
    assert project["ready"] is True
    assert project["root"] == str(destination)
    assert (destination / "headers" / "types.h").is_file()


@pytest.mark.unit
def test_import_project_zip_accepts_single_wrapper_directory(tmp_path):
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")}
    payload = _zip_payload(
        {
            "wrapped/nlspec.txt": "Requirement",
            "wrapped/controller.is": "interface",
            "wrapped/headers/types.h": "typedef int value_t;",
        }
    )

    project = run_server._import_project_zip(
        filename="controller.zip",
        content_b64=payload,
        runtime_env=env,
    )

    assert project["id"] == "controller"
    assert project["ready"] is True
    assert Path(project["root"]) == tmp_path / "workspace" / "projects" / "controller"


@pytest.mark.unit
def test_import_project_zip_rejects_path_traversal(tmp_path):
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")}
    payload = _zip_payload({"../escape.txt": "not allowed"})

    with pytest.raises(ValueError, match="Unsafe path"):
        run_server._import_project_zip(
            filename="unsafe.zip",
            content_b64=payload,
            runtime_env=env,
        )

    assert not (tmp_path / "workspace" / "escape.txt").exists()


@pytest.mark.unit
def test_list_projects_reports_ready_and_incomplete_projects(tmp_path):
    workspace = tmp_path / "workspace"
    _create_project(workspace / "projects", "ready")
    (workspace / "projects" / "incomplete").mkdir(parents=True)

    projects = run_server._list_managed_projects({"SPEC2CODE_WORKSPACE_ROOT": str(workspace)})

    by_id = {project["id"]: project for project in projects}
    assert by_id["ready"]["ready"] is True
    assert by_id["incomplete"]["ready"] is False
    assert by_id["ready"]["source"] == "managed"


@pytest.mark.unit
def test_import_rejects_duplicate_project_name(tmp_path):
    source = _create_project(tmp_path / "source", "demo")
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")}
    run_server._import_project_folder(source_path=str(source), runtime_env=env)

    with pytest.raises(FileExistsError, match="already exists"):
        run_server._import_project_folder(source_path=str(source), runtime_env=env)


@pytest.mark.unit
def test_folder_import_rejects_workspace_ancestor(tmp_path):
    workspace = tmp_path / "workspace"
    _create_project(workspace, "source-project")
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(workspace)}

    with pytest.raises(ValueError, match="contains the managed projects"):
        run_server._import_project_folder(source_path=str(workspace), project_name="copy", runtime_env=env)


@pytest.mark.unit
def test_native_import_tokens_are_single_use(tmp_path):
    source = _create_project(tmp_path / "source", "demo")
    token = run_server._register_native_import_path(str(source))

    assert run_server._consume_native_import_path(token) == source.resolve()
    with pytest.raises(ValueError, match="expired"):
        run_server._consume_native_import_path(token)


@pytest.mark.unit
def test_projects_http_api_imports_and_lists_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEC2CODE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("SPEC2CODE_OUTPUT_ROOT", str(tmp_path / "workspace" / "output"))
    payload = {
        "filename": "api-demo.zip",
        "content_b64": _zip_payload(
            {
                "nlspec.txt": "Requirement",
                "api-demo.is": "interface",
                "headers/types.h": "typedef int value_t;",
            }
        ),
    }
    server = run_server.ThreadingHTTPServer(("127.0.0.1", 0), run_server._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(
            f"{base_url}/api/projects/import",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            imported = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(f"{base_url}/api/projects", timeout=5) as response:
            listed = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert imported["project"]["id"] == "api-demo"
    assert any(project["id"] == "api-demo" and project["ready"] for project in listed["projects"])


def _browser_files(contents):
    return [{"path": path, "content_b64": base64.b64encode(content.encode()).decode()} for path, content in contents.items()]


def test_browser_file_import_preserves_names_and_selected_roles(tmp_path):
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path / "workspace")}
    project = run_server._import_project_files(
        project_name="controller", runtime_env=env,
        files=_browser_files({
            "docs/my requirements.md": "Keep temperature below limit",
            "controller.is": "interface", "include/types.h": "typedef int value_t;",
            "include/nested/constants.h": "#define LIMIT 3", "include/controller_ver.h": "contract",
        }),
        selections={"spec": "docs/my requirements.md", "interface": "controller.is", "headers": "include", "verification_header": ""},
    )
    assert project["ready"]
    assert project["spec"].endswith("my requirements.md")
    assert project["verification_header"] == ""
    assert "nested/constants.h" in project["prompt_headers"]
    assert (Path(project["root"]) / "include/types.h").read_text() == "typedef int value_t;"
    assert project["include_dirs"] == [project["headers"]]


@pytest.mark.parametrize("path", ["../escape.c", "/outside.c", "C:/outside.c", "nested/../../bad.c", "nested\\..\\bad.c"])
def test_browser_file_import_rejects_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError, match="Unsafe"):
        run_server._import_project_files(project_name="demo", runtime_env={"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path)}, files=_browser_files({path: "bad"}))
    assert not (tmp_path / "projects" / "demo").exists()


def test_browser_file_import_failure_is_atomic_and_detects_duplicate_names(tmp_path):
    env = {"SPEC2CODE_WORKSPACE_ROOT": str(tmp_path)}
    with pytest.raises(ValueError, match="Duplicate"):
        run_server._import_project_files(project_name="demo", runtime_env=env, files=_browser_files({"a.h": "", "A.h": ""}))
    with pytest.raises(ValueError, match="incomplete"):
        run_server._import_project_files(project_name="demo", runtime_env=env, files=_browser_files({"types.h": ""}))
    assert not (tmp_path / "projects" / "demo").exists()


def test_uploaded_interface_keeps_basename(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "GUI_TMP_DIR", tmp_path)
    path, error = run_server._stage_uploaded_picker_file(filename="controller.is", content_b64=base64.b64encode(b"interface").decode())
    assert error is None
    assert Path(path).name == "controller.is"
