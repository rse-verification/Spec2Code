from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from spec2code.pipeline_modules import llms
from spec2code.pipeline_modules.critics.critics_registry import (
    DEFAULT_VERNFR_CONTROL_SCRIPT,
    DEFAULT_VERNFR_DATA_SCRIPT,
    GUI_CRITICS_CATALOG,
)
from spec2code.pipeline_modules.critics.critics_runner import build_critics_from_names, run_critics_on_artifacts

REPO_ROOT = Path(__file__).resolve().parents[3]
GUI_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.getenv("SPEC2CODE_OUTPUT_ROOT", str(REPO_ROOT.parent / "spec2code_output"))).resolve()
CASE_STUDIES_ROOT = Path(
    os.getenv("SPEC2CODE_CASE_STUDIES_ROOT", str(REPO_ROOT.parent / "spec2code_case_studies"))
).resolve()
REPORTS_DIR = OUTPUT_ROOT / "reports"
GUI_TMP_DIR = OUTPUT_ROOT / "gui_tmp"
GUI_TEMPLATES_DIR = REPO_ROOT / "config" / "gui_templates"
MODELS_CACHE_FILE = GUI_TMP_DIR / "models_cache.json"

ALLOWED_RUNTIME_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}

GUI_SESSION_ENV_OVERRIDES: dict[str, str] = {}
_MODELS_CACHE_LOCK = threading.Lock()
_MODELS_CACHE: dict[str, Any] = {
    "by_key": {},
    "last_key": "",
}

_RUN_JOBS_LOCK = threading.Lock()
_RUN_JOBS: dict[str, dict[str, Any]] = {}

MOCK_MODELS = [
    "test-llm-shutdown",
]


def _parse_why3_solvers(output: str) -> list[str]:
    mapping = [
        ("Alt-Ergo", ["alt-ergo", "alt_ergo"]),
        ("CVC5", ["cvc5"]),
        ("CVC4", ["cvc4"]),
        ("Z3", ["z3"]),
        ("Vampire", ["vampire"]),
        ("Eprover", ["eprover", "e-prover"]),
        ("Coq", ["coq"]),
    ]
    found: list[str] = []
    seen: set[str] = set()
    text = (output or "").lower()
    for canonical, needles in mapping:
        if any(n in text for n in needles):
            if canonical not in seen:
                seen.add(canonical)
                found.append(canonical)
    return found


def _detect_why3_solvers() -> list[str]:
    commands = [
        ["why3", "config", "--list-provers"],
        ["why3", "--list-provers"],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
            parsed = _parse_why3_solvers((proc.stdout or "") + "\n" + (proc.stderr or ""))
            if parsed:
                return parsed
        except Exception:
            continue
    return []


def _build_critics_catalog() -> tuple[list[dict[str, Any]], list[str]]:
    catalog = copy.deepcopy(GUI_CRITICS_CATALOG)
    detected = _detect_why3_solvers()
    default_solvers = ",".join(detected) if detected else "Alt-Ergo"

    for critic in catalog:
        if critic.get("name") != "framac-wp":
            continue
        for opt in critic.get("options", []):
            if opt.get("key") == "solvers":
                opt["default"] = default_solvers
                break
        break

    return catalog, detected


def _find_latest_sample_output(root: Path) -> Path | None:
    latest: Path | None = None
    latest_mtime = -1.0
    for dirpath, _, files in os.walk(root):
        if "output.json" not in files:
            continue
        p = Path(dirpath) / "output.json"
        if not p.parent.name.startswith("sample_"):
            continue
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > latest_mtime:
            latest_mtime = m
            latest = p
    return latest


def _latest_verify_report_path() -> Path:
    return REPORTS_DIR / "latest-verify.json"


def _write_latest_verify_report(payload: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    p = _latest_verify_report_path()
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_runtime_path(path: str, *, base_dir: Path | None = None) -> Path:
    raw = str(path or "").strip()
    if not raw:
        return Path("")

    if os.path.isabs(raw):
        return Path(os.path.normpath(raw)).resolve()

    normalized = raw.replace("\\", "/")

    if normalized.startswith("case_studies/"):
        repo_candidate = (REPO_ROOT / raw).resolve()
        if repo_candidate.exists():
            return repo_candidate
        suffix = normalized.split("/", 1)[1]
        return (CASE_STUDIES_ROOT / suffix).resolve()

    if normalized.startswith("output/"):
        repo_candidate = (REPO_ROOT / raw).resolve()
        if repo_candidate.exists():
            return repo_candidate
        suffix = normalized.split("/", 1)[1]
        return (OUTPUT_ROOT / suffix).resolve()

    if base_dir is not None and (
        normalized.startswith("../")
        or normalized.startswith("./")
        or normalized.startswith("..\\")
        or normalized.startswith(".\\")
    ):
        return (base_dir / raw).resolve()

    return (REPO_ROOT / raw).resolve()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except Exception:
        pass
    try:
        rel = resolved.relative_to(OUTPUT_ROOT.resolve()).as_posix()
        return f"<SPEC2CODE_OUTPUT_ROOT>/{rel}"
    except Exception:
        pass
    try:
        rel = resolved.relative_to(CASE_STUDIES_ROOT.resolve()).as_posix()
        return f"<SPEC2CODE_CASE_STUDIES_ROOT>/{rel}"
    except Exception:
        return str(resolved)


def _json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    body = text.encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _serve_file(handler: BaseHTTPRequestHandler, file_path: Path, content_type: str) -> None:
    if not file_path.is_file():
        _text_response(handler, "Not found", status=404)
        return

    data = file_path.read_bytes()
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _list_templates() -> list[str]:
    out: set[str] = set()
    roots = [GUI_TEMPLATES_DIR]
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.json")):
            try:
                out.add(p.relative_to(REPO_ROOT).as_posix())
            except Exception:
                continue
    return sorted(out)


def _list_models() -> list[str]:
    names = set(llms.available_model_names())
    names.update(MOCK_MODELS)
    return sorted(names)


def _default_gui_models() -> list[str]:
    return sorted(MOCK_MODELS)


def _invalidate_models_cache() -> None:
    with _MODELS_CACHE_LOCK:
        _MODELS_CACHE["by_key"] = {}
        _MODELS_CACHE["last_key"] = ""
    try:
        MODELS_CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _models_cache_key(env: dict[str, str]) -> str:
    # Do not persist raw secrets in cache keys.
    relevant_env = {
        "AWS_PROFILE": str(env.get("AWS_PROFILE", "")),
        "AWS_REGION": str(env.get("AWS_REGION", "") or env.get("AWS_DEFAULT_REGION", "")),
        "HAS_ANTHROPIC_KEY": bool(str(env.get("ANTHROPIC_API_KEY", "")).strip()),
        "HAS_OPENAI_KEY": bool(str(env.get("OPENAI_API_KEY", "")).strip()),
        "HAS_AWS_KEYPAIR": bool(str(env.get("AWS_ACCESS_KEY_ID", "")).strip() and str(env.get("AWS_SECRET_ACCESS_KEY", "")).strip()),
    }
    fetch_flag = str(os.getenv("SPEC2CODE_GUI_FETCH_BEDROCK", "1"))
    return json.dumps({"env": relevant_env, "fetch_bedrock": fetch_flag}, sort_keys=True)


def _load_models_cache_from_disk() -> dict[str, Any]:
    if not MODELS_CACHE_FILE.is_file():
        return {"by_key": {}, "last_key": ""}
    try:
        raw = json.loads(MODELS_CACHE_FILE.read_text(encoding="utf-8"))
        by_key = dict(raw.get("by_key") or {})
        last_key = str(raw.get("last_key") or "")
        return {"by_key": by_key, "last_key": last_key}
    except Exception:
        return {"by_key": {}, "last_key": ""}


def _save_models_cache_to_disk(payload: dict[str, Any]) -> None:
    try:
        GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _compute_models_payload(env: dict[str, str]) -> dict[str, Any]:
    default_models = _default_gui_models()
    credential_models, unavailable = _credential_ready_models(env)
    all_models = set(credential_models)
    bedrock_models, bedrock_note = _list_bedrock_models(env)
    has_profiles = any(str(m).startswith("bedrock-profile/") for m in bedrock_models)
    if has_profiles:
        # When inference profiles are available, hide raw foundation model IDs
        # to avoid selecting non-invokable on-demand Bedrock model names.
        all_models = {m for m in all_models if not str(m).startswith("bedrock/")}
        bedrock_models = [m for m in bedrock_models if str(m).startswith("bedrock-profile/")]
    all_models.update(bedrock_models)

    notes = ["Model list includes credential-ready providers and discovered Bedrock entries."]
    if bedrock_models:
        notes.append(f"Detected {len(bedrock_models)} Bedrock model(s) from AWS.")
    if has_profiles:
        notes.append("Using Bedrock inference profiles; hidden raw bedrock/<modelId> entries to prevent on-demand invocation errors.")
    if bedrock_note:
        notes.append(bedrock_note)
    if unavailable:
        notes.append(
            f"Hidden {len(unavailable)} model(s) due to missing credentials/provider setup."
        )

    return {
        "models": default_models,
        "all_models": sorted(all_models),
        "note": " ".join(notes),
    }


def _models_payload_cached(env: dict[str, str], *, force_refresh: bool = False) -> dict[str, Any]:
    key = _models_cache_key(env)
    with _MODELS_CACHE_LOCK:
        by_key = dict(_MODELS_CACHE.get("by_key") or {})
        last_key = str(_MODELS_CACHE.get("last_key") or "")

    if not by_key:
        disk_cache = _load_models_cache_from_disk()
        by_key = dict(disk_cache.get("by_key") or {})
        last_key = str(disk_cache.get("last_key") or "")
        with _MODELS_CACHE_LOCK:
            _MODELS_CACHE["by_key"] = by_key
            _MODELS_CACHE["last_key"] = last_key

    if not force_refresh:
        cached_payload = by_key.get(key)
        if cached_payload is None and last_key:
            cached_payload = by_key.get(last_key)
        if cached_payload is not None:
            cached = dict(cached_payload or {})
            note = str(cached.get("note") or "").strip()
            cached["note"] = (note + " ").strip() + "Model list served from cache."
            return cached

    payload = _compute_models_payload(env)
    by_key[key] = payload
    last_key = key
    with _MODELS_CACHE_LOCK:
        _MODELS_CACHE["by_key"] = by_key
        _MODELS_CACHE["last_key"] = last_key
    _save_models_cache_to_disk({"by_key": by_key, "last_key": last_key})
    return dict(payload)


def _sanitize_env_overrides(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw in payload.items():
        if key not in ALLOWED_RUNTIME_ENV_KEYS:
            continue
        val = str(raw).strip()
        if val:
            out[key] = val
    return out


def _effective_runtime_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(GUI_SESSION_ENV_OVERRIDES)
    if extra:
        env.update(extra)
    return env


def _has_aws_credentials(env: dict[str, str]) -> bool:
    if str(env.get("AWS_PROFILE", "")).strip():
        return True
    key = str(env.get("AWS_ACCESS_KEY_ID", "")).strip()
    secret = str(env.get("AWS_SECRET_ACCESS_KEY", "")).strip()
    return bool(key and secret)


def _provider_ready(provider_spec: dict[str, Any], env: dict[str, str]) -> tuple[bool, str | None]:
    p_type = str(provider_spec.get("type", "")).strip()
    if p_type == "ollama":
        return True, None
    if p_type == "bedrock":
        if not _has_aws_credentials(env):
            return False, "missing AWS credentials/profile"
        return True, None
    if p_type == "openai-compatible":
        api_key = provider_spec.get("api_key")
        if not api_key and provider_spec.get("api_key_env"):
            api_key = env.get(str(provider_spec["api_key_env"]))
        if not api_key:
            api_key = env.get("OPENAI_API_KEY")
        if not api_key:
            return False, "missing API key"
        return True, None
    return True, None


def _credential_ready_models(env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    available: list[str] = []
    unavailable: dict[str, str] = {}
    providers, specs = llms._available_specs()  # type: ignore[attr-defined]

    for name in _list_models():
        if name in MOCK_MODELS:
            available.append(name)
            continue
        if name.startswith("bedrock/"):
            continue

        spec = specs.get(name)
        if not isinstance(spec, dict):
            unavailable[name] = "model spec not found"
            continue

        if "provider" in spec:
            provider_name = str(spec["provider"])
            provider_spec = providers.get(provider_name)
            if not isinstance(provider_spec, dict):
                unavailable[name] = f"unknown provider: {provider_name}"
                continue
            ok, reason = _provider_ready(provider_spec, env)
            if not ok:
                unavailable[name] = reason or "provider not ready"
                continue
            available.append(name)
            continue

        model_type = str(spec.get("type", "llm"))
        if model_type == "llm":
            key_env = spec.get("key_env")
            if key_env and not str(env.get(str(key_env), "")).strip():
                unavailable[name] = f"missing {key_env}"
                continue
            available.append(name)
            continue

        if model_type == "bedrock":
            if not _has_aws_credentials(env):
                unavailable[name] = "missing AWS credentials/profile"
                continue
            available.append(name)
            continue

        available.append(name)

    return sorted(set(available)), unavailable


def _extract_bedrock_model_names(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in payload.get("modelSummaries", []) or []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("modelId") or "").strip()
        if not model_id:
            continue
        normalized = f"bedrock/{model_id}"
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return sorted(out)


def _extract_bedrock_inference_profile_names(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in payload.get("inferenceProfileSummaries", []) or []:
        if not isinstance(item, dict):
            continue
        profile_ref = str(item.get("inferenceProfileArn") or item.get("inferenceProfileId") or "").strip()
        if not profile_ref:
            continue
        normalized = f"bedrock-profile/{profile_ref}"
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return sorted(out)


def _list_bedrock_models(env: dict[str, str]) -> tuple[list[str], str | None]:
    fetch_enabled = str(os.getenv("SPEC2CODE_GUI_FETCH_BEDROCK", "1")).strip().lower() not in {"0", "false", "no"}
    if not fetch_enabled:
        return [], None

    try:
        import boto3  # lazy import to keep optional behavior

        region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "eu-west-1"
        profile = env.get("AWS_PROFILE")
        session_kwargs: dict[str, Any] = {"region_name": region}
        if profile:
            session_kwargs["profile_name"] = profile
        access_key = env.get("AWS_ACCESS_KEY_ID")
        secret_key = env.get("AWS_SECRET_ACCESS_KEY")
        session_token = env.get("AWS_SESSION_TOKEN")
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                session_kwargs["aws_session_token"] = session_token
        session = boto3.Session(**session_kwargs)
        client = session.client("bedrock", region_name=region)

        profile_payload: dict[str, Any] = {"inferenceProfileSummaries": []}
        next_token = None
        while True:
            kwargs: dict[str, Any] = {}
            if next_token:
                kwargs["nextToken"] = next_token
            resp_profiles = client.list_inference_profiles(**kwargs)
            profile_payload["inferenceProfileSummaries"].extend(resp_profiles.get("inferenceProfileSummaries", []) or [])
            next_token = resp_profiles.get("nextToken")
            if not next_token:
                break

        profile_names = _extract_bedrock_inference_profile_names(profile_payload)
        if profile_names:
            return profile_names, None

        # Fallback: show foundation model ids when no inference profiles are available.
        # These may still fail for models that require an inference profile ARN.
        resp = client.list_foundation_models(byOutputModality="TEXT")
        names = _extract_bedrock_model_names(resp or {})
        if not names:
            return [], "AWS reachable, but no Bedrock text models/profiles were returned."
        return names, "No Bedrock inference profiles found; showing foundation model IDs as fallback."
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        return [], (
            "Bedrock models unavailable (credentials/session not ready). "
            "Run `aws sso login --profile <your-profile>` and export AWS_PROFILE/AWS_REGION. "
            f"Details: {msg}"
        )


def _is_safe_repo_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
        return True
    except Exception:
        return False


def _is_safe_path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _is_safe_runtime_path(path: Path) -> bool:
    return any(
        _is_safe_path_under(path, root)
        for root in (REPO_ROOT, OUTPUT_ROOT, CASE_STUDIES_ROOT)
    )


def _list_repo_entries(
    *,
    kind: str,
    query: str = "",
    exts: list[str] | None = None,
    limit: int = 200,
) -> list[str]:
    kind_norm = (kind or "file").strip().lower()
    if kind_norm not in {"file", "dir"}:
        kind_norm = "file"

    query_norm = (query or "").strip().lower()
    exts_norm = [e if e.startswith(".") else f".{e}" for e in (exts or []) if str(e).strip()]

    max_items = max(1, min(int(limit or 200), 1000))
    out: list[str] = []

    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "output"}

    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        root_path = Path(root)

        if kind_norm == "dir":
            rel = root_path.relative_to(REPO_ROOT).as_posix() if root_path != REPO_ROOT else "."
            if rel != ".":
                if (not query_norm) or (query_norm in rel.lower()):
                    out.append(rel)
                    if len(out) >= max_items:
                        break
            continue

        for name in files:
            p = root_path / name
            rel = p.relative_to(REPO_ROOT).as_posix()
            if exts_norm and p.suffix not in exts_norm:
                continue
            if query_norm and query_norm not in rel.lower():
                continue
            out.append(rel)
            if len(out) >= max_items:
                break
        if len(out) >= max_items:
            break

    out.sort()
    return out[:max_items]


def _run_pipeline_from_template(payload: dict[str, Any], *, defer_execute: bool = False) -> dict[str, Any]:
    template_rel = str(payload.get("template", "")).strip()
    if not template_rel:
        return {"ok": False, "error": "Missing 'template'."}

    template_path = (REPO_ROOT / template_rel).resolve()
    if not _is_safe_repo_path(template_path) or not template_path.is_file():
        return {"ok": False, "error": f"Invalid template path: {template_rel}"}

    raw_models = payload.get("models", [])
    if not isinstance(raw_models, list):
        return {"ok": False, "error": "'models' must be a list."}
    selected_models = [str(x).strip() for x in raw_models if str(x).strip()]

    manual_models_raw = str(payload.get("manual_models", "")).strip()
    if manual_models_raw:
        for x in manual_models_raw.split(","):
            m = x.strip()
            if m:
                selected_models.append(m)

    selected_models = sorted(set(selected_models))
    if not selected_models:
        return {"ok": False, "error": "Select at least one model."}

    try:
        n_programs = int(payload.get("n_programs_generated", 1))
        if n_programs < 1:
            raise ValueError
    except Exception:
        return {"ok": False, "error": "'n_programs_generated' must be an integer >= 1."}

    try:
        temperature = float(payload.get("temperature", 0.7))
    except Exception:
        return {"ok": False, "error": "'temperature' must be numeric."}

    try:
        data = json.loads(template_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"Failed to parse template JSON: {exc}"}

    if not isinstance(data, list) or not data:
        return {"ok": False, "error": "Template config must be a non-empty JSON array."}

    template_base_dir = template_path.parent

    def abs_if_rel(p: str) -> str:
        p = str(p).strip()
        if not p:
            return p
        return os.path.normpath(str(_resolve_runtime_path(p, base_dir=template_base_dir)))

    for cfg in data:
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "Each pipeline config must be a JSON object."}
        cfg["llms_used"] = selected_models
        cfg["n_programs_generated"] = n_programs
        cfg["temperature"] = temperature

        # Normalize common path fields against repo root so GUI templates can
        # live outside input/ without relative-path breakage.
        for key in [
            "output_folder",
            "natural_spec_path",
            "interface_path",
            "verification_header_path",
            "headers_dir",
        ]:
            if key in cfg and isinstance(cfg[key], str):
                cfg[key] = abs_if_rel(cfg[key])
        if isinstance(cfg.get("include_dirs"), list):
            cfg["include_dirs"] = [abs_if_rel(x) if isinstance(x, str) else x for x in cfg["include_dirs"]]

        # Normalize known critic option paths as well, so template-relative
        # paths (e.g. ../case_studies/...) keep working when GUI writes a temp config.
        crit_opts = cfg.get("critic_options")
        if isinstance(crit_opts, dict):
            path_keys = {
                "verification_header_template_path",
                "misra_rules_path",
                "formal_c_path",
                "interface_path",
                "control_script_path",
                "data_script_path",
                "script_path",
            }
            for _critic_name, opts in crit_opts.items():
                if not isinstance(opts, dict):
                    continue
                for k, v in list(opts.items()):
                    if k in path_keys and isinstance(v, str):
                        opts[k] = abs_if_rel(v)

    tmp_path: Path
    GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="spec2code-gui-",
        suffix=".json",
        delete=False,
        mode="w",
        encoding="utf-8",
        dir=str(GUI_TMP_DIR),
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path = Path(f.name)

    if defer_execute:
        return {"ok": True, "config_path": str(tmp_path)}

    try:
        env_overrides = _sanitize_env_overrides(payload.get("env_overrides", {}))
        return _run_pipeline_with_config_path(tmp_path, env_overrides=env_overrides)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _run_pipeline_with_config_path(config_path: Path, *, env_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    env = _effective_runtime_env(env_overrides)
    py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"src{os.pathsep}{py_path}" if py_path else "src"

    cmd = [
        sys.executable,
        "-m",
        "spec2code.cli.run_pipeline",
        "--config",
        str(config_path),
        "--no-open-report",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    report_rel = "reports/last-run.html"
    report_path = REPORTS_DIR / "last-run.html"

    warnings: list[str] = []
    noisy = "Error executing Why3 command"
    stdout_lines = [ln for ln in proc.stdout.splitlines()]
    filtered_stdout: list[str] = []
    for ln in stdout_lines:
        if noisy in ln:
            warnings.append("Why3 not found in PATH; proof-related checks may be limited.")
        else:
            filtered_stdout.append(ln)

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": "\n".join(filtered_stdout),
        "stderr": proc.stderr,
        "warnings": warnings,
        "report": report_rel if report_path.is_file() else None,
    }


def _start_pipeline_job(*, config_path: Path, env_overrides: dict[str, str] | None = None) -> str:
    run_id = uuid.uuid4().hex
    with _RUN_JOBS_LOCK:
        _RUN_JOBS[run_id] = {
            "status": "running",
            "stdout": "",
            "stderr": "",
            "warnings": [],
            "returncode": None,
            "ok": False,
            "report": None,
            "error": None,
        }

    def _append(stream_key: str, text: str) -> None:
        if not text:
            return
        with _RUN_JOBS_LOCK:
            job = _RUN_JOBS.get(run_id)
            if job is None:
                return
            job[stream_key] = str(job.get(stream_key, "")) + text

    def _worker() -> None:
        env = _effective_runtime_env(env_overrides)
        py_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"src{os.pathsep}{py_path}" if py_path else "src"
        cmd = [
            sys.executable,
            "-m",
            "spec2code.cli.run_pipeline",
            "--config",
            str(config_path),
            "--no-open-report",
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )

            def _reader(pipe, key: str) -> None:
                try:
                    if pipe is None:
                        return
                    for line in iter(pipe.readline, ""):
                        _append(key, line)
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
            t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
            t_out.start()
            t_err.start()
            proc.wait()
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

            with _RUN_JOBS_LOCK:
                job = _RUN_JOBS.get(run_id)
                if job is None:
                    return
                warnings: list[str] = []
                filtered_stdout: list[str] = []
                for ln in str(job.get("stdout", "")).splitlines():
                    if "Error executing Why3 command" in ln:
                        warnings.append("Why3 not found in PATH; proof-related checks may be limited.")
                    else:
                        filtered_stdout.append(ln)
                report_rel = "reports/last-run.html"
                report_path = REPORTS_DIR / "last-run.html"
                job["status"] = "done"
                job["returncode"] = int(proc.returncode)
                job["ok"] = proc.returncode == 0
                job["stdout"] = "\n".join(filtered_stdout)
                job["warnings"] = warnings
                job["report"] = report_rel if report_path.is_file() else None
        except Exception as exc:
            with _RUN_JOBS_LOCK:
                job = _RUN_JOBS.get(run_id)
                if job is not None:
                    job["status"] = "done"
                    job["ok"] = False
                    job["error"] = str(exc)
        finally:
            try:
                config_path.unlink(missing_ok=True)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()
    return run_id


def _run_job_status(run_id: str) -> dict[str, Any]:
    with _RUN_JOBS_LOCK:
        job = _RUN_JOBS.get(run_id)
        if job is None:
            return {"ok": False, "error": "Unknown run id."}
        return {
            "ok": True,
            "run_id": run_id,
            "status": job.get("status", "done"),
            "done": job.get("status") == "done",
            "stdout": job.get("stdout", ""),
            "stderr": job.get("stderr", ""),
            "warnings": list(job.get("warnings", [])),
            "returncode": job.get("returncode"),
            "report": job.get("report"),
            "error": job.get("error"),
        }


def _run_pipeline_from_custom(payload: dict[str, Any], *, defer_execute: bool = False) -> dict[str, Any]:
    config_text = str(payload.get("config_json", ""))
    if not config_text.strip():
        return {"ok": False, "error": "Missing 'config_json'."}

    try:
        data = json.loads(config_text)
    except Exception as exc:
        return {"ok": False, "error": f"Invalid JSON: {exc}"}

    if not isinstance(data, list) or not data:
        return {"ok": False, "error": "Config JSON must be a non-empty array."}

    def abs_if_rel(p: str) -> str:
        p = str(p).strip()
        if not p:
            return p
        return os.path.normpath(str(_resolve_runtime_path(p)))

    # Normalize common path fields against repo root so custom mode does not
    # depend on input/ relative path layout.
    for cfg in data:
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "Each config item must be an object."}
        for key in [
            "output_folder",
            "natural_spec_path",
            "interface_path",
            "verification_header_path",
            "headers_dir",
        ]:
            if key in cfg and isinstance(cfg[key], str):
                cfg[key] = abs_if_rel(cfg[key])
        if isinstance(cfg.get("include_dirs"), list):
            cfg["include_dirs"] = [abs_if_rel(x) if isinstance(x, str) else x for x in cfg["include_dirs"]]

    GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix="spec2code-gui-custom-",
        suffix=".json",
        delete=False,
        mode="w",
        encoding="utf-8",
        dir=str(GUI_TMP_DIR),
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path = Path(f.name)

    if defer_execute:
        return {"ok": True, "config_path": str(tmp_path)}

    try:
        env_overrides = _sanitize_env_overrides(payload.get("env_overrides", {}))
        return _run_pipeline_with_config_path(tmp_path, env_overrides=env_overrides)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    return [x.strip() for x in text.split(",") if x.strip()]


def _resolve_repo_path(value: Any, *, required: bool = False, label: str = "path") -> tuple[Path | None, str | None]:
    p = str(value or "").strip()
    if not p:
        if required:
            return None, f"Missing required '{label}'."
        return None, None

    path = _resolve_runtime_path(p)

    if not _is_safe_runtime_path(path):
        return None, f"{label} must be inside repository or configured runtime roots: {p}"

    return path, None


def _copy_headers_flat(*, headers_dir: Path, dst_dir: Path) -> tuple[list[str], list[str]]:
    copied: list[str] = []
    created: list[str] = []
    dst_dir.mkdir(parents=True, exist_ok=True)
    for root, _, files in os.walk(headers_dir):
        for name in files:
            src = Path(root) / name
            dst = dst_dir / name
            # No-op when source and destination are the same file.
            if dst.exists():
                try:
                    if os.path.samefile(src, dst):
                        continue
                except OSError:
                    pass
            existed = dst.exists()
            shutil.copy2(src, dst)
            copied.append(str(dst))
            if not existed:
                created.append(str(dst))
    return copied, created


def _extract_c_include_targets(formal_file: Path) -> list[str]:
    try:
        text = formal_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    out: list[str] = []
    for m in re.finditer(r"#\s*include\s*[<\"]([^>\"]+\.c)[>\"]", text):
        val = m.group(1).strip()
        if val and val not in out:
            out.append(val)
    return out


def _infer_main_from_interface_text(text: str) -> str | None:
    if not text.strip():
        return None

    block_m = re.search(r"entry_functions\s*:\s*\{(.*?)\}", text, flags=re.IGNORECASE | re.DOTALL)
    if block_m:
        block = block_m.group(1)
        funcs = re.findall(r"\b([A-Za-z_]\w*)\s*\(", block)
        if funcs:
            return funcs[0]

    proto_rx = re.compile(
        r"(?m)^\s*(?:extern\s+)?(?:static\s+)?[A-Za-z_]\w*(?:\s+[*\w]+)*\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*;\s*$"
    )
    m = proto_rx.search(text)
    if m:
        return m.group(1)
    return None


def _infer_main_from_interface_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return _infer_main_from_interface_text(text)


def _resolve_optional_repo_file(value: Any, *, label: str) -> tuple[Path | None, str | None]:
    if value is None or not str(value).strip():
        return None, None
    p, err = _resolve_repo_path(value, required=False, label=label)
    if err:
        return None, err
    assert p is not None
    if not p.is_file():
        return None, f"{label} not found: {p}"
    return p, None


def _run_verify_files(payload: dict[str, Any]) -> dict[str, Any]:
    c_file_path, err = _resolve_repo_path(payload.get("c_file_path"), required=True, label="c_file_path")
    if err:
        return {"ok": False, "error": err}

    assert c_file_path is not None
    if not c_file_path.is_file():
        return {"ok": False, "error": f"c_file_path not found: {c_file_path}"}

    generated_header_path, err = _resolve_repo_path(
        payload.get("generated_header_path"), required=False, label="generated_header_path"
    )
    if err:
        return {"ok": False, "error": err}
    if generated_header_path is not None and not generated_header_path.is_file():
        return {"ok": False, "error": f"generated_header_path not found: {generated_header_path}"}

    include_dirs_raw = payload.get("include_dirs", [])
    include_dirs: list[str] = []
    for d in _split_csv(include_dirs_raw):
        p, perr = _resolve_repo_path(d, required=False, label="include_dirs")
        if perr:
            return {"ok": False, "error": perr}
        assert p is not None
        if not p.is_dir():
            return {"ok": False, "error": f"include_dirs entry not found: {p}"}
        include_dirs.append(str(p))

    generated_files: list[str] = []
    for p_raw in _split_csv(payload.get("generated_files", [])):
        p, perr = _resolve_repo_path(p_raw, required=False, label="generated_files")
        if perr:
            return {"ok": False, "error": perr}
        assert p is not None
        if not p.is_file():
            return {"ok": False, "error": f"generated_files entry not found: {p}"}
        generated_files.append(str(p))

    headers_dir_values = _split_csv(payload.get("headers_dir", ""))
    if not headers_dir_values:
        # Merged UX: include_dirs also serve as header-copy source dirs.
        headers_dir_values = _split_csv(payload.get("include_dirs", []))
    headers_dirs: list[Path] = []
    for h_raw in headers_dir_values:
        h_path, herr = _resolve_repo_path(h_raw, required=False, label="headers_dir")
        if herr:
            return {"ok": False, "error": herr}
        assert h_path is not None
        if not h_path.is_dir():
            return {"ok": False, "error": f"headers_dir not found: {h_path}"}
        headers_dirs.append(h_path)

    critics = _split_csv(payload.get("critics", ["compile"])) or ["compile"]
    requested_critics = list(critics)
    defines = _split_csv(payload.get("defines", []))

    try:
        timeout = int(payload.get("timeout", 60))
        if timeout <= 0:
            raise ValueError
    except Exception:
        return {"ok": False, "error": "timeout must be a positive integer."}

    remove_compiled = bool(payload.get("remove_compiled", True))
    compiled_output = str(payload.get("compiled_output_path", "")).strip() or f"{c_file_path}.out"
    if not os.path.isabs(compiled_output):
        compiled_output = os.path.normpath(str(REPO_ROOT / compiled_output))

    critic_options = payload.get("critic_options", {})
    if not isinstance(critic_options, dict):
        return {"ok": False, "error": "critic_options must be an object/dict."}

    normalized_critic_options: dict[str, dict[str, Any]] = {
        str(k): dict(v) for k, v in critic_options.items() if isinstance(v, dict)
    }

    temp_dirs: list[Path] = []
    cleanup_files: list[Path] = []
    cleanup_after_verify = bool(payload.get("cleanup_after_verify", False))

    def _ret(payload: dict[str, Any]) -> dict[str, Any]:
        if cleanup_after_verify:
            for f in cleanup_files:
                try:
                    if f.is_file():
                        f.unlink()
                except Exception:
                    pass
            for td in temp_dirs:
                try:
                    shutil.rmtree(td, ignore_errors=True)
                except Exception:
                    pass
        return payload

    framac_opts = dict(normalized_critic_options.get("framac-wp", {}))
    framac_solvers = framac_opts.get("solvers", "Alt-Ergo")
    solvers = _split_csv(framac_solvers) or ["Alt-Ergo"]
    if "solvers" in framac_opts:
        framac_opts.pop("solvers", None)

    spec_c_path: Path | None = None
    formal_path_raw = framac_opts.get("formal_c_path")
    formal_path: Path | None = None
    if formal_path_raw is not None and str(formal_path_raw).strip():
        formal_path, ferr = _resolve_repo_path(formal_path_raw, required=False, label="critic_options[framac-wp][formal_c_path]")
        if ferr:
            return _ret({"ok": False, "error": ferr})
        assert formal_path is not None
        if not formal_path.is_file():
            return _ret({"ok": False, "error": f"formal_c_path not found: {formal_path}"})

    normalized_critic_options["framac-wp"] = framac_opts

    copied_headers: list[str] = []
    run_c_path = c_file_path

    # If we verify against a formal spec, stage everything in one folder and
    # materialize the expected .c include names from the formal file.
    if formal_path is not None:
        GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=f"verify-stage-{int(time.time())}-", dir=str(GUI_TMP_DIR)))
        temp_dirs.append(stage_dir)

        staged_c = stage_dir / c_file_path.name
        shutil.copy2(c_file_path, staged_c)
        run_c_path = staged_c

        staged_formal = stage_dir / formal_path.name
        shutil.copy2(formal_path, staged_formal)
        spec_c_path = staged_formal

        # Copy header-dir contents into staging first (all files, flat).
        if headers_dirs:
            try:
                for h_dir in headers_dirs:
                    copied, _created = _copy_headers_flat(headers_dir=h_dir, dst_dir=stage_dir)
                    copied_headers.extend(copied)
            except Exception as exc:
                return _ret({"ok": False, "error": f"Failed to copy headers: {exc}"})

        # Ensure included .c file names referenced by formal spec exist.
        for inc in _extract_c_include_targets(staged_formal):
            target = stage_dir / inc
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(staged_c, target)
            except Exception as exc:
                return _ret({"ok": False, "error": f"Failed to stage included C target '{inc}': {exc}"})

        if str(stage_dir) not in include_dirs:
            include_dirs.append(str(stage_dir))

    # Avoid mutating source folders: when header copying is requested without a
    # formal-spec staging folder, stage the selected C file first.
    if headers_dirs and formal_path is None:
        GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=f"verify-stage-{int(time.time())}-", dir=str(GUI_TMP_DIR)))
        temp_dirs.append(stage_dir)
        staged_c = stage_dir / c_file_path.name
        shutil.copy2(run_c_path, staged_c)
        run_c_path = staged_c

    if headers_dirs:
        try:
            for h_dir in headers_dirs:
                copied, created = _copy_headers_flat(headers_dir=h_dir, dst_dir=run_c_path.parent)
                copied_headers.extend(copied)
                cleanup_files.extend(Path(p) for p in created)
        except Exception as exc:
            return _ret({"ok": False, "error": f"Failed to copy headers: {exc}"})
        out_dir = str(run_c_path.parent)
        if out_dir not in include_dirs:
            include_dirs.append(out_dir)

    # Vernfr meta-critic expansion (control/data branches) with interface staging.
    if "vernfr" in critics:
        vern_opts = dict(normalized_critic_options.get("vernfr", {}))
        control_enabled = bool(vern_opts.get("control_flow", True))
        data_enabled = bool(vern_opts.get("data_flow", True))
        if not control_enabled and not data_enabled:
            return _ret({"ok": False, "error": "vernfr selected but both control_flow and data_flow are disabled."})

        interface_path, ierr = _resolve_optional_repo_file(
            vern_opts.get("interface_path"),
            label="critic_options[vernfr][interface_path]",
        )
        if ierr:
            return _ret({"ok": False, "error": ierr})
        if interface_path is None:
            return _ret({"ok": False, "error": "vernfr requires critic_options[vernfr][interface_path]."})

        control_script: Path | None = None
        data_script: Path | None = None
        if control_enabled:
            control_script, cerr = _resolve_optional_repo_file(
                vern_opts.get("control_script_path", DEFAULT_VERNFR_CONTROL_SCRIPT),
                label="critic_options[vernfr][control_script_path]",
            )
            if cerr:
                return _ret({"ok": False, "error": cerr})

        if data_enabled:
            data_script, derr = _resolve_optional_repo_file(
                vern_opts.get("data_script_path", DEFAULT_VERNFR_DATA_SCRIPT),
                label="critic_options[vernfr][data_script_path]",
            )
            if derr:
                return _ret({"ok": False, "error": derr})

        vern_modname = str(vern_opts.get("modname", "")).strip() or run_c_path.stem
        vern_main = str(vern_opts.get("main", "")).strip()
        if not vern_main:
            vern_main = _infer_main_from_interface_file(interface_path) or "main"
        vern_timeout = int(vern_opts.get("timeout", timeout))

        GUI_TMP_DIR.mkdir(parents=True, exist_ok=True)
        vern_stage = Path(tempfile.mkdtemp(prefix=f"verify-vernfr-{int(time.time())}-", dir=str(GUI_TMP_DIR)))
        temp_dirs.append(vern_stage)

        staged_c = vern_stage / f"{vern_modname}.c"
        shutil.copy2(run_c_path, staged_c)

        staged_is_primary = vern_stage / f"{vern_modname}.is"
        shutil.copy2(interface_path, staged_is_primary)

        # Also materialize interface aliases for robustness when source name
        # and module name differ (e.g. sgmm_full.is vs sgmm.c).
        source_is_name = interface_path.name
        source_is_target = vern_stage / source_is_name
        if source_is_target != staged_is_primary:
            shutil.copy2(interface_path, source_is_target)

        c_stem_is_target = vern_stage / f"{run_c_path.stem}.is"
        if c_stem_is_target != staged_is_primary and c_stem_is_target != source_is_target:
            shutil.copy2(interface_path, c_stem_is_target)

        if not staged_is_primary.is_file():
            return _ret({"ok": False, "error": f"Failed to stage vernfr interface file: {staged_is_primary}"})

        header_candidates: list[Path] = []
        if generated_header_path is not None:
            header_candidates.append(generated_header_path)
        inferred_h = run_c_path.with_suffix(".h")
        if inferred_h.is_file():
            header_candidates.append(inferred_h)
        for h_dir in headers_dirs:
            candidate = h_dir / f"{vern_modname}.h"
            if candidate.is_file():
                header_candidates.append(candidate)
        parent_h = run_c_path.parent / f"{vern_modname}.h"
        if parent_h.is_file():
            header_candidates.append(parent_h)

        if not header_candidates:
            return _ret({
                "ok": False,
                "error": f"vernfr requires a header '{vern_modname}.h' (provide generated_header_path or headers_dir).",
            })

        shutil.copy2(header_candidates[0], vern_stage / f"{vern_modname}.h")

        # Bring header folder content into vernfr stage for include resolution.
        for h_dir in headers_dirs:
            copied, _created = _copy_headers_flat(headers_dir=h_dir, dst_dir=vern_stage)
            copied_headers.extend(copied)

        expanded: list[str] = []
        for c in critics:
            if c != "vernfr":
                expanded.append(c)
                continue
            if control_enabled:
                expanded.append("vernfr-control-flow")
            if data_enabled:
                expanded.append("vernfr-data-flow")
        critics = expanded

        common_ctx = {
            "timeout": vern_timeout,
            "folder": str(vern_stage),
            "modname": vern_modname,
            "main": vern_main,
        }

        if control_enabled:
            if control_script is None:
                return _ret({"ok": False, "error": "vernfr control_flow enabled but control_script_path is missing."})
            cf_opts = dict(normalized_critic_options.get("vernfr-control-flow", {}))
            cf_opts.update(common_ctx)
            cf_opts["script_path"] = str(control_script)
            normalized_critic_options["vernfr-control-flow"] = cf_opts

        if data_enabled:
            if data_script is None:
                return _ret({"ok": False, "error": "vernfr data_flow enabled but data_script_path is missing."})
            df_opts = dict(normalized_critic_options.get("vernfr-data-flow", {}))
            df_opts.update(common_ctx)
            df_opts["script_path"] = str(data_script)
            normalized_critic_options["vernfr-data-flow"] = df_opts

        normalized_critic_options.pop("vernfr", None)

    critic_context = payload.get("critic_context", {})
    if not isinstance(critic_context, dict):
        return _ret({"ok": False, "error": "critic_context must be an object/dict."})

    if generated_header_path is not None:
        critic_context = dict(critic_context)
        critic_context["generated_header_path"] = str(generated_header_path)
    if generated_files:
        critic_context = dict(critic_context)
        critic_context["generated_files"] = generated_files

    try:
        critic_instances = build_critics_from_names(
            names=critics,
            solvers=solvers,
            timeout=timeout,
            critic_options=normalized_critic_options,
        )
    except Exception as exc:
        return _ret({"ok": False, "error": f"Failed to build critics: {exc}"})

    try:
        result = run_critics_on_artifacts(
            critics=critic_instances,
            raw_c_path=str(run_c_path),
            spec_c_path=str(spec_c_path) if spec_c_path is not None else None,
            compiled_output_path=compiled_output,
            remove_compiled=remove_compiled,
            timeout=timeout,
            base_context=critic_context,
            include_dirs=include_dirs,
            defines=defines,
            critic_targets={"framac-wp": "spec"} if spec_c_path is not None else {},
            critic_configs=normalized_critic_options,
        )
    except Exception as exc:
        return _ret({"ok": False, "error": f"Verification failed: {exc}"})

    response = {
        "ok": True,
        "inputs": {
            "c_file_path": str(c_file_path),
            "run_c_path": str(run_c_path),
            "headers_dir": headers_dir_values,
            "copied_headers": copied_headers,
            "staging_dirs": [str(p) for p in temp_dirs],
            "formal_c_path": str(spec_c_path) if spec_c_path is not None else None,
            "critics": critics,
            "requested_critics": requested_critics,
            "timeout": timeout,
            "solvers": solvers,
            "include_dirs": include_dirs,
            "defines": defines,
            "cleanup_after_verify": cleanup_after_verify,
        },
        "result": result,
    }

    try:
        _write_latest_verify_report({
            "ok": True,
            "created_at": time.time(),
            "data": response,
        })
    except Exception:
        pass

    return _ret(response)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in {"/", "/runner", "/runner.html"}:
            _serve_file(self, GUI_DIR / "runner.html", "text/html; charset=utf-8")
            return
        if path in {"/results", "/results.html"}:
            _serve_file(self, GUI_DIR / "results.html", "text/html; charset=utf-8")
            return
        if path in {"/verify", "/verify.html"}:
            _serve_file(self, GUI_DIR / "verify.html", "text/html; charset=utf-8")
            return
        if path == "/runner.js":
            _serve_file(self, GUI_DIR / "runner.js", "application/javascript; charset=utf-8")
            return
        if path == "/results.js":
            _serve_file(self, GUI_DIR / "results.js", "application/javascript; charset=utf-8")
            return
        if path == "/verify.js":
            _serve_file(self, GUI_DIR / "verify.js", "application/javascript; charset=utf-8")
            return
        if path == "/critics-ui.js":
            _serve_file(self, GUI_DIR / "critics-ui.js", "application/javascript; charset=utf-8")
            return
        if path == "/runner.css":
            _serve_file(self, GUI_DIR / "runner.css", "text/css; charset=utf-8")
            return
        if path == "/api/models":
            env = _effective_runtime_env()
            force_refresh = str((qs.get("force") or [""])[0] or "").strip() in {"1", "true", "True"}
            _json_response(self, _models_payload_cached(env, force_refresh=force_refresh))
            return
        if path == "/api/run-status":
            run_id = str((qs.get("run_id") or [""])[0] or "").strip()
            if not run_id:
                _json_response(self, {"ok": False, "error": "Missing run_id."}, status=400)
                return
            payload = _run_job_status(run_id)
            status = 200 if payload.get("ok") else 404
            _json_response(self, payload, status=status)
            return
        if path == "/api/templates":
            _json_response(self, {"templates": _list_templates()})
            return
        if path in {"/api/critics", "/api/critics/"}:
            catalog, detected = _build_critics_catalog()
            _json_response(self, {"critics": catalog, "detected_solvers": detected})
            return
        if path == "/api/files":
            kind = str((qs.get("kind") or ["file"])[0] or "file")
            q = str((qs.get("q") or [""])[0] or "")
            ext_raw = str((qs.get("ext") or [""])[0] or "")
            exts = [x.strip() for x in ext_raw.split(",") if x.strip()]
            try:
                limit = int((qs.get("limit") or ["200"])[0] or "200")
            except Exception:
                limit = 200
            entries = _list_repo_entries(kind=kind, query=q, exts=exts, limit=limit)
            _json_response(self, {"ok": True, "kind": kind, "entries": entries})
            return
        if path == "/api/latest-result":
            latest = _find_latest_sample_output(OUTPUT_ROOT)
            if latest is None:
                _json_response(self, {"ok": False, "error": "No sample output found yet."}, status=404)
                return
            try:
                data = json.loads(latest.read_text(encoding="utf-8"))
                mtime = latest.stat().st_mtime
            except Exception as exc:
                _json_response(self, {"ok": False, "error": f"Failed to read latest output: {exc}"}, status=500)
                return
            _json_response(
                self,
                {
                    "ok": True,
                    "path": _display_path(latest),
                    "mtime": mtime,
                    "data": data,
                },
            )
            return

        if path == "/api/latest-verify":
            p = _latest_verify_report_path()
            if not p.is_file():
                _json_response(self, {"ok": False, "error": "No verify output found yet."}, status=404)
                return
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                mtime = p.stat().st_mtime
            except Exception as exc:
                _json_response(self, {"ok": False, "error": f"Failed to read latest verify output: {exc}"}, status=500)
                return
            data = payload.get("data", payload)
            _json_response(self, {"ok": True, "path": _display_path(p), "mtime": mtime, "data": data})
            return

        if path.startswith("/reports/"):
            rel = path[len("/reports/") :]
            file_path = REPORTS_DIR / rel
            if not _is_safe_path_under(file_path, REPORTS_DIR):
                _text_response(self, "Forbidden", status=403)
                return
            ctype = "text/html; charset=utf-8"
            if file_path.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif file_path.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif file_path.suffix == ".json":
                ctype = "application/json; charset=utf-8"
            _serve_file(self, file_path, ctype)
            return

        _text_response(self, "Not found", status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in {
            "/api/run",
            "/api/run-custom",
            "/api/run-start",
            "/api/run-custom-start",
            "/api/verify-files",
            "/api/session-env",
        }:
            _text_response(self, "Not found", status=404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json_response(self, {"ok": False, "error": "Invalid Content-Length."}, status=400)
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _json_response(self, {"ok": False, "error": "Invalid JSON body."}, status=400)
            return

        if not isinstance(payload, dict):
            _json_response(self, {"ok": False, "error": "Body must be a JSON object."}, status=400)
            return

        if path == "/api/session-env":
            env_overrides = _sanitize_env_overrides(payload.get("env", {}))
            GUI_SESSION_ENV_OVERRIDES.clear()
            GUI_SESSION_ENV_OVERRIDES.update(env_overrides)
            _json_response(
                self,
                {
                    "ok": True,
                    "saved_keys": sorted(GUI_SESSION_ENV_OVERRIDES.keys()),
                },
                status=200,
            )
            return

        if path == "/api/run-start":
            prep = _run_pipeline_from_template(payload, defer_execute=True)
            if not prep.get("ok"):
                _json_response(self, prep, status=400)
                return
            env_overrides = _sanitize_env_overrides(payload.get("env_overrides", {}))
            run_id = _start_pipeline_job(config_path=Path(str(prep["config_path"])), env_overrides=env_overrides)
            _json_response(self, {"ok": True, "run_id": run_id}, status=200)
            return

        if path == "/api/run-custom-start":
            prep = _run_pipeline_from_custom(payload, defer_execute=True)
            if not prep.get("ok"):
                _json_response(self, prep, status=400)
                return
            env_overrides = _sanitize_env_overrides(payload.get("env_overrides", {}))
            run_id = _start_pipeline_job(config_path=Path(str(prep["config_path"])), env_overrides=env_overrides)
            _json_response(self, {"ok": True, "run_id": run_id}, status=200)
            return

        if path == "/api/run":
            result = _run_pipeline_from_template(payload)
        elif path == "/api/run-custom":
            result = _run_pipeline_from_custom(payload)
        else:
            result = _run_verify_files(payload)
        status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.BAD_REQUEST
        _json_response(self, result, status=int(status))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="spec2code GUI runner server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"spec2code GUI runner available at http://{args.host}:{args.port}/runner")
    print(f"spec2code GUI results available at http://{args.host}:{args.port}/results")
    print(f"spec2code GUI verify available at http://{args.host}:{args.port}/verify")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
