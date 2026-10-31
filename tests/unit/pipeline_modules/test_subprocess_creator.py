from __future__ import annotations

import sys
import time

import pytest

from spec2code.pipeline_modules import subprocess_creator


def _python(code):
    return [sys.executable, "-c", code]


@pytest.mark.unit
def test_run_command_returns_exit_code_on_success():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command(
        _python("print('ok')"),
        timeout=5,
    )

    assert completed is True
    assert exit_code == 0
    assert "ok" in stdout
    assert stderr == ""
    assert timing.get("real", 0.0) >= 0.0


@pytest.mark.unit
def test_run_command_returns_nonzero_exit_code():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command(
        _python("import sys; sys.exit(7)"),
        timeout=5,
    )

    assert completed is True
    assert exit_code == 7
    assert stdout == ""
    assert stderr == ""
    assert timing.get("real", 0.0) >= 0.0


@pytest.mark.unit
def test_run_command_timeout_returns_incomplete_and_none_exit_code():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command(
        _python("import time; time.sleep(20)"),
        timeout=1,
    )

    assert completed is False
    assert exit_code is None
    assert stdout == ""
    assert stderr == "Timeout"
    assert timing == {}


@pytest.mark.unit
def test_run_command_drains_large_output_without_timing_out():
    stdout, stderr, completed, exit_code, timing = subprocess_creator.run_command(
        _python("import sys; sys.stdout.buffer.write(b'X' * 200000); sys.stderr.buffer.write(b'Y' * 200000 + b'\\n')"),
        timeout=3,
        stream=False,
    )

    assert completed is True
    assert exit_code == 0
    assert len(stdout) == 200000
    assert stderr == "Y" * 200000 + "\n"
    assert timing.get("real", 0.0) >= 0.0


@pytest.mark.unit
def test_run_command_streams_output_while_retaining_it(capsys):
    stdout, stderr, completed, exit_code, _timing = subprocess_creator.run_command(
        _python("import sys; print('out'); print('err', file=sys.stderr)"),
        timeout=5,
        stream=True,
    )

    captured = capsys.readouterr()
    assert completed is True
    assert exit_code == 0
    assert stdout.splitlines() == ["out"]
    assert stderr.splitlines() == ["err"]
    assert "out" in captured.out.splitlines()
    assert "err" in captured.out.splitlines()


@pytest.mark.unit
def test_argument_list_preserves_spaces_and_shell_metacharacters(tmp_path):
    value = "a space & semicolon; literal $HOME"
    stdout, stderr, completed, exit_code, _ = subprocess_creator.run_command(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", value], timeout=5, cwd=str(tmp_path), stream=False,
    )
    assert completed and exit_code == 0
    assert stdout.strip() == value
    assert stderr == ""


@pytest.mark.unit
def test_shell_command_strings_remain_supported():
    stdout, _, completed, exit_code, _ = subprocess_creator.run_command("echo shell-ok", timeout=5, stream=False)
    assert completed and exit_code == 0
    assert stdout.strip() == "shell-ok"


@pytest.mark.unit
def test_timeout_stops_children_that_inherit_output_pipes():
    started = time.monotonic()
    result = subprocess_creator.run_command(_python(
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "time.sleep(30)"
    ), timeout=1, stream=False)
    assert result[2:4] == (False, None)
    assert time.monotonic() - started < 10
