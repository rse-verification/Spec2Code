from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


PROJECT_MANIFEST = "spec2code.project.json"
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    projects: Path
    output: Path
    reports: Path
    tmp: Path
    input: Path
    case_studies: Path

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: Path,
        env: Optional[Mapping[str, str]] = None,
    ) -> "WorkspacePaths":
        values = os.environ if env is None else env
        configured = str(values.get("SPEC2CODE_WORKSPACE_ROOT", "") or "").strip()
        root = _absolute(configured, repo_root) if configured else (repo_root.parent / "spec2code_workspace").resolve()
        default_output = root / "output" if configured else repo_root.parent / "spec2code_output"
        default_input = root / "input" if configured else repo_root.parent / "spec2code_input"
        default_cases = root / "projects" if configured else repo_root.parent / "spec2code_case_studies"
        output = _absolute(values.get("SPEC2CODE_OUTPUT_ROOT", ""), repo_root) if values.get("SPEC2CODE_OUTPUT_ROOT") else default_output.resolve()
        input_root = _absolute(values.get("SPEC2CODE_INPUT_ROOT", ""), repo_root) if values.get("SPEC2CODE_INPUT_ROOT") else default_input.resolve()
        case_root = (
            _absolute(values.get("SPEC2CODE_CASE_STUDIES_ROOT", ""), repo_root)
            if values.get("SPEC2CODE_CASE_STUDIES_ROOT")
            else default_cases.resolve()
        )
        return cls(
            root=root,
            projects=root / "projects",
            output=output,
            reports=output / "reports",
            tmp=output / "gui_tmp",
            input=input_root,
            case_studies=case_root,
        )

    def ensure(self) -> None:
        for path in (self.root, self.projects, self.output, self.reports, self.tmp, self.input):
            path.mkdir(parents=True, exist_ok=True)

    def project_candidates(self, project_id: str) -> list[Path]:
        validate_project_id(project_id)
        candidates = [self.projects / project_id, self.case_studies / project_id, self.input / project_id]
        unique: list[Path] = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in unique:
                unique.append(resolved)
        return unique

    def resolve_project(self, project_id: str) -> Path:
        candidates = self.project_candidates(project_id)
        return next((path for path in candidates if path.is_dir()), candidates[0])


@dataclass(frozen=True)
class ProjectLayout:
    project_id: str
    root: Path
    spec: Optional[Path]
    interface: Optional[Path]
    headers: Optional[Path]
    verification_header: Optional[Path]
    include_dirs: tuple[Path, ...]
    prompt_headers: dict[str, str]
    manifest_path: Optional[Path]

    @property
    def ready(self) -> bool:
        return bool(self.spec and self.interface and self.headers)

    @property
    def missing(self) -> list[str]:
        missing = []
        if not self.spec:
            missing.append("natural specification")
        if not self.interface:
            missing.append("interface (.is)")
        if not self.headers:
            missing.append("headers directory")
        return missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.project_id,
            "root": str(self.root),
            "ready": self.ready,
            "missing": self.missing,
            "spec": str(self.spec) if self.spec else "",
            "interface": str(self.interface) if self.interface else "",
            "headers": str(self.headers) if self.headers else "",
            "verification_header": str(self.verification_header) if self.verification_header else "",
            "include_dirs": [str(path) for path in self.include_dirs],
            "prompt_headers": self.prompt_headers,
            "manifest": str(self.manifest_path) if self.manifest_path else "",
        }


def validate_project_id(project_id: str) -> str:
    value = str(project_id or "").strip()
    if not _PROJECT_ID_RE.fullmatch(value):
        raise ValueError("Project name must contain only letters, numbers, '.', '_' or '-'.")
    return value


def discover_project(project_root: Path, project_id: Optional[str] = None) -> ProjectLayout:
    root = project_root.expanduser().resolve()
    identifier = validate_project_id(project_id or root.name)
    manifest_path = root / PROJECT_MANIFEST
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{PROJECT_MANIFEST} must contain a JSON object.")
        manifest = loaded

    spec = _manifest_file(root, manifest.get("spec"), "spec") or _first_file(
        root,
        ["nlspec.txt", "spec.txt", "requirements.txt"],
        recursive=True,
    )
    interface = _manifest_file(root, manifest.get("interface"), "interface") or _single_match(root, "*.is")
    headers = _manifest_dir(root, manifest.get("headers"), "headers")
    if headers is None:
        conventional = root / "headers"
        headers = conventional if conventional.is_dir() else None
    if headers is None and interface and interface.parent != root and any(interface.parent.glob("*.h")):
        headers = interface.parent

    verification = _manifest_file(root, manifest.get("verification_header"), "verification_header")
    if verification is None and "verification_header" not in manifest:
        verification = _single_match(headers or root, "*_ver.h")

    include_values = manifest.get("include_dirs")
    include_dirs: list[Path] = []
    if include_values is not None:
        if not isinstance(include_values, list) or not all(isinstance(item, str) for item in include_values):
            raise ValueError("Project manifest 'include_dirs' must be a list of paths.")
        include_dirs = [_safe_child(root, item, "include_dirs") for item in include_values]
    elif headers:
        include_dirs = [headers]

    prompt_value = manifest.get("prompt_headers")
    if prompt_value is not None:
        if not isinstance(prompt_value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in prompt_value.items()):
            raise ValueError("Project manifest 'prompt_headers' must be an object of filename-to-description values.")
        if headers is None:
            raise ValueError("Project manifest 'prompt_headers' requires a headers directory.")
        prompt_headers = {}
        for filename, description in prompt_value.items():
            header_path = _safe_child(headers, filename, "prompt_headers")
            prompt_headers[header_path.relative_to(headers).as_posix()] = description
    elif headers:
        prompt_headers = {
            path.relative_to(headers).as_posix(): ""
            for path in sorted(headers.rglob("*.h"))
            if path != verification
        }
    else:
        prompt_headers = {}

    return ProjectLayout(
        project_id=identifier,
        root=root,
        spec=spec,
        interface=interface,
        headers=headers,
        verification_header=verification,
        include_dirs=tuple(include_dirs),
        prompt_headers=prompt_headers,
        manifest_path=manifest_path if manifest_path.is_file() else None,
    )


def apply_project_defaults(
    config: Mapping[str, Any],
    *,
    base_dir: Path,
    repo_root: Path,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    result = dict(config)
    project_id = str(result.get("project") or result.get("case_study") or "").strip()
    project_dir_value = str(result.get("project_dir") or "").strip()
    if not project_dir_value and not result.get("project"):
        return result

    workspace = WorkspacePaths.from_env(repo_root=repo_root, env=env)
    if project_dir_value:
        project_root = Path(project_dir_value).expanduser()
        if not project_root.is_absolute():
            project_root = base_dir / project_root
        project_root = project_root.resolve()
        if not project_id:
            project_id = project_root.name
    else:
        project_id = validate_project_id(project_id)
        project_root = workspace.resolve_project(project_id)

    if not project_root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_root}")
    layout = discover_project(project_root, project_id)
    if not layout.ready:
        raise ValueError(f"Project '{project_id}' is incomplete: missing {', '.join(layout.missing)}.")

    result.setdefault("case_study", project_id)
    result.setdefault("name", f"config_{project_id}")
    run_name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(result["name"])).strip("-._") or "run"
    result.setdefault("natural_spec_path", str(layout.spec))
    result.setdefault("interface_path", str(layout.interface))
    result.setdefault("headers_dir", str(layout.headers))
    result.setdefault("include_dirs", [str(path) for path in layout.include_dirs])
    result.setdefault("headers_manifest", layout.prompt_headers)
    result.setdefault("output_folder", str(workspace.output / project_id / run_name))
    if layout.verification_header:
        result.setdefault("verification_header_path", str(layout.verification_header))
    return result


def _absolute(value: str, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _safe_child(root: Path, value: str, label: str) -> Path:
    candidate = (root / str(value)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Project manifest '{label}' must stay inside the project directory.") from exc
    return candidate


def _manifest_file(root: Path, value: Any, label: str) -> Optional[Path]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"Project manifest '{label}' must be a path string.")
    path = _safe_child(root, value, label)
    if not path.is_file():
        raise FileNotFoundError(f"Project manifest '{label}' file not found: {path}")
    return path


def _manifest_dir(root: Path, value: Any, label: str) -> Optional[Path]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"Project manifest '{label}' must be a path string.")
    path = _safe_child(root, value, label)
    if not path.is_dir():
        raise FileNotFoundError(f"Project manifest '{label}' directory not found: {path}")
    return path


def _first_file(root: Path, names: list[str], *, recursive: bool) -> Optional[Path]:
    for name in names:
        direct = root / name
        if direct.is_file():
            return direct
    if recursive:
        for name in names:
            matches = sorted(root.rglob(name))
            if matches:
                return matches[0]
    return None


def _single_match(root: Path, pattern: str) -> Optional[Path]:
    if not root.is_dir():
        return None
    matches = sorted(path for path in root.rglob(pattern) if path.is_file())
    return matches[0] if len(matches) == 1 else None
