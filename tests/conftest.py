from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

# Prevent SDK imports from reading a developer's .env or selecting a desktop keyring.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Directory defaults apply before pytest's -m filtering; explicit kinds win."""
    kinds = {"unit", "integration", "e2e", "contracts"}
    for item in items:
        marks = {marker.name for marker in item.iter_markers()}
        if not marks.intersection(kinds):
            directory = item.path.relative_to(REPO_ROOT / "tests").parts[0]
            if directory not in kinds:
                raise pytest.UsageError(f"Test needs a category marker: {item.nodeid}")
            item.add_marker(getattr(pytest.mark, directory))
        if {"integration", "critics"}.issubset(marks):
            item.add_marker(pytest.mark.native)


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("OPENAI_", "ANTHROPIC_", "VLLM_", "OLLAMA_", "AWS_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.delenv("SPEC2CODE_LLM_CONFIG", raising=False)


@pytest.fixture(autouse=True)
def local_connections_only(monkeypatch):
    """SDK stubs and browser/HTTP fixtures use loopback; cloud calls are test bugs."""
    attempted = []
    for method in ("connect", "connect_ex"):
        original = getattr(socket.socket, method)

        def connect(sock, address, _original=original):
            if sock.family in {socket.AF_INET, socket.AF_INET6} and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                attempted.append(address[0])
                raise AssertionError("External network call in a test; use a local fixture or SDK stub.")
            return _original(sock, address)

        monkeypatch.setattr(socket.socket, method, connect)
    yield
    assert not attempted, f"Unexpected external network attempts: {attempted}"
