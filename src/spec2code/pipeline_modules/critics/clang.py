import re
from typing import Dict, List

from spec2code.pipeline_modules.subprocess_creator import run_command


def verify_clang_static(
    c_file_path: str,
    clang_args: List[str] | None = None,
    timeout: int = 60,
) -> Dict[str, object]:
    """
    Runs Clang's static analyzer on a C file using `clang --analyze`.

    Args:
        c_file_path: Path to the C source file.
        clang_args: Extra arguments for clang (e.g. include paths, defines).
        timeout: Timeout for the command in seconds.

    Returns:
        Dict[str, object]:
            - "verify_success" (bool): True if no warnings/errors were reported.
            - "verify_message" (str): Summary of diagnostics or success message.
            - "clang_warnings" (int): Number of warnings.
            - "clang_errors" (int): Number of errors.
            - "clang_raw_output" (str): Full clang output.
    """
    if clang_args is None:
        clang_args = []

    # Build the clang command
    # Example: clang --analyze -Wall file.c
    args_str = " ".join(clang_args)
    clang_cmd = f"clang --analyze {args_str} '{c_file_path}'".strip()

    res = run_command(clang_cmd, timeout)
    if isinstance(res, tuple) and len(res) == 4:
        stdout_str, stderr_str, completed, _exit_code = res
    else:
        stdout_str, stderr_str, completed = res  # type: ignore[misc]
    output = stdout_str + "\n" + stderr_str

    if not completed:
        return {
            "verify_success": False,
            "verify_message": f"clang --analyze timeout or error.\n{output}",
            "clang_warnings": 0,
            "clang_errors": 0,
            "clang_raw_output": output,
        }

    return analyze_clang_output(output, c_file_path)


def analyze_clang_output(output: str, c_file_path: str) -> Dict[str, object]:
    """
    Parses clang output and counts warnings/errors for the given file.
    """
    lines = output.splitlines()

    warning_lines: List[str] = []
    error_lines: List[str] = []

    # Simple heuristic: filter diagnostics mentioning the file and containing 'warning:' or 'error:'
    file_hint = c_file_path.split("/")[-1]  # just the basename for robustness

    for line in lines:
        if "warning:" in line and file_hint in line:
            warning_lines.append(line)
        elif "error:" in line and file_hint in line:
            error_lines.append(line)

    num_warnings = len(warning_lines)
    num_errors = len(error_lines)

    success = (num_warnings == 0 and num_errors == 0)

    if success:
        message = "Clang static analysis: no warnings or errors."
    else:
        message_parts = ["Clang static analysis diagnostics:"]
        if error_lines:
            message_parts.append("\nErrors:")
            message_parts.extend(error_lines)
        if warning_lines:
            message_parts.append("\nWarnings:")
            message_parts.extend(warning_lines)
        message = "\n".join(message_parts)

    return {
        "verify_success": success,
        "verify_message": message,
        "clang_warnings": num_warnings,
        "clang_errors": num_errors,
        "clang_raw_output": output,
    }
