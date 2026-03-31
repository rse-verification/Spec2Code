from __future__ import annotations

import pytest

from spec2code.pipeline_modules import subprocess_creator


@pytest.mark.unit
def test_run_command_returns_exit_code_on_success():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command("python -c \"print('ok')\"", timeout=5)

    assert completed is True
    assert exit_code == 0
    assert "ok" in stdout
    assert stderr == ""
    assert timing.get("real", 0.0) >= 0.0


@pytest.mark.unit
def test_run_command_returns_nonzero_exit_code():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command("python -c \"import sys; sys.exit(7)\"", timeout=5)

    assert completed is True
    assert exit_code == 7
    assert stdout == ""
    assert stderr == ""
    assert timing.get("real", 0.0) >= 0.0


@pytest.mark.unit
def test_run_command_timeout_returns_incomplete_and_none_exit_code():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command(
        "python -c \"import time; time.sleep(2)\"",
        timeout=1,
    )

    assert completed is False
    assert exit_code is None
    assert stdout == ""
    assert stderr == "Timeout"
    assert timing == {}
