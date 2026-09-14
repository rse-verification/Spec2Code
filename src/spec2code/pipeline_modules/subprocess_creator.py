import subprocess
import shlex
import re
import os
import signal
import threading


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

def run_command(command: str, timeout: int, cwd: str | None = None, stream: bool = True) -> tuple:
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
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []

    # Drain both pipes concurrently so verbose tools cannot block, while
    # forwarding completed lines to the CLI when a caller requests it.
    def _reader(pipe, parts: list[bytes]) -> None:
        try:
            for line in iter(pipe.readline, b""):
                parts.append(line)
                if stream:
                    print(line.decode("utf-8", errors="replace"), end="", flush=True)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(target=_reader, args=(process.stdout, stdout_parts), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=(process.stderr, stderr_parts), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        process.wait(timeout=timeout)
        stdout_thread.join()
        stderr_thread.join()
        stdout = b"".join(stdout_parts).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_parts).decode("utf-8", errors="replace")
        stderr_text, timing = _extract_time_metrics(stderr)
        return stdout, stderr_text, True, process.returncode, timing
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        # Reap the process and let both pipe readers finish after terminating it.
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        return "", "Timeout", False, None, {}
