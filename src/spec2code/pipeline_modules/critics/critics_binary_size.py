from __future__ import annotations
import os
import shlex
from typing import Any, Dict, List

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult
from src.spec2code.pipeline_modules.subprocess_creator import run_command


class BinarySizeCritic:
    name = "binary_size"

    def __init__(
        self,
        binary_size_limit_bytes: int = 1024,
    ):
        self.binary_size_limit_bytes = binary_size_limit_bytes

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx = dict(inp.get("context", {}))

        workdir = os.path.dirname(c_file_path) or None

        object_file_output_path = os.path.join(workdir or ".", "bin_size_object.o")

        def _delete_object_file() -> None:
            try:
                if os.path.exists(object_file_output_path):
                    os.remove(object_file_output_path)
            except OSError:
                pass
        
        # Use for all returns to make sure object file is deleted
        def _finish(result: CriticResult) -> CriticResult:
            _delete_object_file()
            return result

        include_dirs: List[str] = list(ctx.get("include_dirs", []))
        defines: List[str] = list(ctx.get("defines", []))
        extra_args: List[str] = list(inp.get("extra_args", []))
        gcc_flags: List[str] = list(ctx.get("gcc_flags", []))
        gcc_flags.append("-c")

        if not os.path.exists(c_file_path):
            msg = f"File does not exist: {c_file_path}"
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Failed to create object file, C-file not found.",
                "metrics": {"message": msg},
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": msg,
            })

        # Remove old object files
        try:
            if os.path.exists(object_file_output_path):
                os.remove(object_file_output_path)
        except OSError as exc:
            msg = f"Failed to remove stale object file: {exc}"
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Failed to create object file.",
                "metrics": {"message": msg, "object_file_output_path": object_file_output_path},
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": object_file_output_path},
                    "rule": None,
                }],
                "raw_output": msg,
            })
        
        inc_args = [f"-I{d}" for d in include_dirs]
        def_args = [f"-D{d}" for d in defines]
        
        cmd_parts: List[str] = (
            ["gcc"]
            + gcc_flags
            + def_args
            + inc_args
            + [c_file_path, "-o", object_file_output_path]
            + extra_args
        )

        compile_cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        res = run_command(compile_cmd, timeout, workdir)

        timing: Dict[str, float] = {}

        exit_code = None
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]

        raw_output_compile = (stdout_str or "") + "\n" + (stderr_str or "")

        if not completed:
            msg = "Binary size compile step timed out."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Binary size compile step timed out.",
                "metrics": {
                    "message": msg,
                    "command": compile_cmd,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": raw_output_compile.strip() or msg,
            })

        if exit_code not in (0, None):
            msg = "Failed to compile object file."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": msg,
                "metrics": {
                    "message": msg,
                    "command": compile_cmd,
                    "exit_code": exit_code,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": raw_output_compile.strip() or msg,
            })
        
        if not os.path.exists(object_file_output_path):
            msg = "Failed to compile object file."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Failed to compile object file.",
                "metrics": {
                    "message": msg,
                    "command": compile_cmd,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": object_file_output_path},
                    "rule": None,
                }],
                "raw_output": raw_output_compile.strip() or msg,
            })
        
        cmd_parts: List[str] = (
            ["size"]
            + [object_file_output_path]
        )

        size_cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        res = run_command(size_cmd, timeout, workdir)

        timing: Dict[str, float] = {}

        exit_code = None
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]

        raw_output = (stdout_str or "") + "\n" + (stderr_str or "")

        if not completed:
            msg = "Binary size command timeout."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": msg,
                "metrics": {
                    "message": msg,
                    "command": size_cmd,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": object_file_output_path},
                    "rule": None,
                }],
                "raw_output": raw_output.strip() or msg,
            })

        if exit_code not in (0, None):
            msg = "Binary size command failed."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": msg,
                "metrics": {
                    "message": msg,
                    "command": size_cmd,
                    "exit_code": exit_code,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": object_file_output_path},
                    "rule": None,
                }],
                "raw_output": raw_output.strip() or msg,
            })
        
        size_bytes = self._parse_size(stdout_str)

        if size_bytes is None:
            msg = "Failed to parse binary size output."
            return _finish({
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": msg,
                "metrics": {
                    "message": msg,
                    "command": size_cmd,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": object_file_output_path},
                    "rule": None,
                }],
                "raw_output": raw_output.strip() or msg,
            })

        ok = size_bytes <= self.binary_size_limit_bytes
        summary = (
            f"Binary size {size_bytes} bytes is within limit {self.binary_size_limit_bytes} bytes."
            if ok
            else f"Binary size {size_bytes} bytes exceeds limit {self.binary_size_limit_bytes} bytes."
        )
        findings = [] if ok else [{
            "tool": self.name,
            "severity": "error",
            "message": summary,
            "location": {"file": object_file_output_path},
            "rule": "binary_size_limit",
        }]

        return _finish({
            "tool": self.name,
            "success": ok,
            "score": 1.0 if ok else 0.0,
            "summary": summary,
            "metrics": {
                "binary_size_bytes": size_bytes,
                "binary_size_limit_bytes": self.binary_size_limit_bytes,
                "command": size_cmd,
                "timeout": timeout,
                "process_real_s": timing.get("real"),
                "process_user_s": timing.get("user"),
                "process_sys_s": timing.get("sys"),
            },
            "findings": findings,
            "raw_output": raw_output.strip(),
        })

    @staticmethod
    def _parse_size(size_stdout: str) -> int | None:
        size_bytes = None

        for line in reversed(size_stdout.splitlines()):
            parts = line.split()
            if len(parts) >= 4 and parts[0].isdigit() and parts[3].isdigit():
                size_bytes = int(parts[3])
                break
        
        return size_bytes
