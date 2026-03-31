from __future__ import annotations

import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


try:
    import boto3  # type: ignore  # noqa: F401
except Exception:
    boto3_stub = types.ModuleType("boto3")

    class _Session:  # pragma: no cover - test bootstrap shim
        def __init__(self, *args, **kwargs):
            pass

        def client(self, *args, **kwargs):
            raise RuntimeError("boto3 is not installed in test environment")

    setattr(boto3_stub, "Session", _Session)
    sys.modules["boto3"] = boto3_stub
