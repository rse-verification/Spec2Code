import subprocess
import shlex
import re
import os
import signal


_TIME_RX = re.compile(r"^\s*(real|user|sys)\s+([0-9]+(?:\.[0-9]+)?)\s*$")


def _wrap_with_time(command: str) -> str:
    # Force POSIX /usr/bin/time output for real/user/sys metrics.
    if os.name == "nt" or not os.path.exists("/usr/bin/time"):
        return command
    return f"/usr/bin/time -p bash -lc {shlex.quote(command)}"


def _extract_time_metrics(stderr_text: str) -> tuple[str, dict[str, float]]:
    metrics: dict[str, float] = {}
    kept_lines: list[str] = []
    for line in (stderr_text or "").splitlines():
        m = _TIME_RX.match(line)
        if m:
            key = m.group(1)
            try:
                metrics[key] = float(m.group(2))
            except Exception:
                pass
            continue
        kept_lines.append(line)
    cleaned = "\n".join(kept_lines)
    if stderr_text.endswith("\n") and cleaned:
        cleaned += "\n"
    return cleaned, metrics

def run_command(command: str, timeout: int, cwd: str | None = None) -> tuple:
    """
    Runs a shell command with a specified timeout.
    
    Args:
        command (str): The command to execute.
        timeout (int): The maximum time in seconds the command can run.

    Returns:
        tuple: (str, str, bool, int | None, dict[str, float])
            - Standard output from the command.
            - Standard error from the command.
            - True if command completed (even with non-zero exit code), False if it timed out.
            - Process exit code when completed, otherwise None.
            - Process timing metrics from `/usr/bin/time -p` with keys: real, user, sys.
    """
    timed_command = _wrap_with_time(command)
    process = subprocess.Popen(
        timed_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        cwd=cwd,
        # The command string is executed through a shell. Give it a distinct
        # process group so that a timeout can stop the shell and its children.
        start_new_session=(os.name != "nt"),
    )
    try:
        # communicate() drains both pipes while the child is running. Using
        # wait() first can deadlock when a verbose tool (such as Frama-C WP)
        # fills stdout or stderr before it exits.
        stdout, stderr = process.communicate(timeout=timeout)
        stderr_text, timing = _extract_time_metrics(stderr.decode("utf-8", errors="replace"))
        return stdout.decode("utf-8", errors="replace"), stderr_text, True, process.returncode, timing
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        # Reap the process and close the pipes after terminating it.
        process.communicate()
        return "", "Timeout", False, None, {}
