from __future__ import annotations

import json
import os
import shlex
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding
from spec2code.pipeline_modules.subprocess_creator import run_command


_FORBIDDEN_NODE_KINDS = {
    "ForStmt": ("for loop", "no_for_loop"),
    "WhileStmt": ("while loop", "no_while_loop"),
    "DoStmt": ("do-while loop", "no_do_while_loop"),
    "GotoStmt": ("goto statement", "no_goto"),
    "IndirectGotoStmt": ("computed goto statement", "no_computed_goto"),
}


class NoLoopsCritic:
    """Reject loop constructs, goto statements, and statically resolvable recursion."""

    name = "no-loops"

    def __init__(self, *, clang: str = "clang", timeout: int = 60):
        self.clang = clang
        self.timeout = timeout

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", self.timeout))
        context = dict(inp.get("context", {}))
        if not os.path.isfile(c_file_path):
            return self._failure(c_file_path, "Generated C file does not exist.", "")

        command = self._ast_command(c_file_path, context)
        result = run_command(command, timeout, cwd=os.path.dirname(c_file_path) or None, stream=False)
        stdout, stderr, completed, exit_code, timing = self._unpack_command_result(result)
        command_output = "\n".join(part for part in (stdout, stderr) if part).strip()
        if not completed:
            return self._failure(c_file_path, "Clang AST analysis timed out.", command_output, command, timeout, timing)
        if exit_code not in (0, None):
            return self._failure(c_file_path, "Clang could not parse the generated C source.", command_output, command, timeout, timing)

        try:
            ast = json.loads(stdout)
        except json.JSONDecodeError:
            return self._failure(c_file_path, "Clang did not produce a valid JSON AST.", command_output, command, timeout, timing)

        findings = self._findings(ast, c_file_path)
        success = not findings
        summary = "No prohibited control flow found." if success else f"Found {len(findings)} prohibited control-flow construct(s)."
        return {
            "tool": self.name,
            "success": success,
            "score": 1.0 if success else 0.0,
            "summary": summary,
            "metrics": {
                "command": command,
                "timeout": timeout,
                "prohibited_constructs": len(findings),
                "process_real_s": timing.get("real"),
                "process_user_s": timing.get("user"),
                "process_sys_s": timing.get("sys"),
            },
            "findings": findings,
            "raw_output": (stderr or "").strip(),
        }

    def _ast_command(self, c_file_path: str, context: Dict[str, Any]) -> str:
        include_dirs = [str(path) for path in context.get("include_dirs", [])]
        defines = [str(value) for value in context.get("defines", [])]
        clang_flags = [str(flag) for flag in context.get("clang_flags", [])]
        parts = [self.clang, "-Xclang", "-ast-dump=json", "-fsyntax-only", "-Wno-everything"]
        parts.extend(f"-I{path}" for path in include_dirs)
        parts.extend(f"-D{value}" for value in defines)
        parts.extend(clang_flags)
        parts.append(c_file_path)
        return " ".join(shlex.quote(part) for part in parts)

    def _findings(self, ast: Dict[str, Any], c_file_path: str) -> List[Finding]:
        source_path = os.path.abspath(c_file_path)
        with open(source_path, "rb") as source_file:
            source_bytes = source_file.read()
        functions = self._defined_functions(ast, source_path)
        findings: List[Finding] = []
        calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self._walk(ast, {"file": source_path}, source_path, source_bytes, None, functions, findings, calls)
        findings.extend(self._recursion_findings(calls, source_path))
        return findings

    def _defined_functions(self, ast: Dict[str, Any], source_path: str) -> Set[str]:
        functions: Set[str] = set()
        for node, current_file in self._nodes(ast, source_path):
            if node.get("kind") == "FunctionDecl" and self._has_body(node) and self._same_file(current_file, source_path):
                name = node.get("name")
                if isinstance(name, str):
                    functions.add(name)
        return functions

    def _walk(
        self,
        node: Dict[str, Any],
        inherited_location: Dict[str, Any],
        source_path: str,
        source_bytes: bytes,
        current_function: Optional[str],
        functions: Set[str],
        findings: List[Finding],
        calls: List[Tuple[str, str, Dict[str, Any]]],
    ) -> None:
        location = self._merge_location(inherited_location, self._source_location(node))
        location = self._location_from_offset(location, source_path, source_bytes)
        current_file = str(location.get("file") or source_path)
        kind = node.get("kind")
        if kind == "FunctionDecl" and self._has_body(node):
            current_function = node.get("name") if self._same_file(current_file, source_path) and isinstance(node.get("name"), str) else None
        if current_function and self._same_file(current_file, source_path):
            if kind in _FORBIDDEN_NODE_KINDS:
                description, rule = _FORBIDDEN_NODE_KINDS[kind]
                findings.append(self._finding(source_path, location, f"Prohibited {description}.", rule))
            elif kind == "CallExpr":
                target = self._called_function(node)
                if target is None:
                    findings.append(
                        self._finding(
                            source_path,
                            location,
                            "Indirect function call cannot be proven non-recursive.",
                            "no_unresolved_indirect_call",
                        )
                    )
                elif target in functions:
                    calls.append((current_function, target, location))
        for child in node.get("inner") or []:
            if isinstance(child, dict):
                self._walk(child, location, source_path, source_bytes, current_function, functions, findings, calls)

    def _recursion_findings(self, calls: List[Tuple[str, str, Dict[str, Any]]], source_path: str) -> List[Finding]:
        graph: Dict[str, Set[str]] = defaultdict(set)
        for caller, callee, _location in calls:
            graph[caller].add(callee)
        findings: List[Finding] = []
        for caller, callee, location in calls:
            cycle = self._cycle_path(graph, caller, callee)
            if cycle:
                findings.append(self._finding(source_path, location, f"Recursive call cycle: {' -> '.join(cycle)}.", "no_recursion"))
        return findings

    @staticmethod
    def _cycle_path(graph: Dict[str, Set[str]], caller: str, callee: str) -> List[str]:
        queue: deque[Tuple[str, List[str]]] = deque([(callee, [caller, callee])])
        visited = {callee}
        while queue:
            function, path = queue.popleft()
            if function == caller and len(path) > 1:
                return path
            for target in sorted(graph.get(function, set())):
                if target not in visited or target == caller:
                    visited.add(target)
                    queue.append((target, path + [target]))
        return []

    @staticmethod
    def _called_function(node: Dict[str, Any]) -> Optional[str]:
        stack = list(node.get("inner") or [])
        while stack:
            current = stack.pop(0)
            if not isinstance(current, dict):
                continue
            if current.get("kind") == "DeclRefExpr":
                referenced = current.get("referencedDecl") or {}
                if referenced.get("kind") == "FunctionDecl" and isinstance(referenced.get("name"), str):
                    return referenced["name"]
            stack.extend(current.get("inner") or [])
        return None

    @staticmethod
    def _has_body(node: Dict[str, Any]) -> bool:
        return any(isinstance(child, dict) and child.get("kind") == "CompoundStmt" for child in node.get("inner") or [])

    @staticmethod
    def _same_file(first: str, second: str) -> bool:
        if not first or not second:
            return False
        first_path = first if os.path.isabs(first) else os.path.join(os.path.dirname(second), first)
        return os.path.normcase(os.path.abspath(first_path)) == os.path.normcase(os.path.abspath(second))

    @classmethod
    def _source_location(cls, node: Dict[str, Any]) -> Dict[str, Any]:
        location = node.get("loc") or (node.get("range") or {}).get("begin") or {}
        return cls._location_point(location)

    @classmethod
    def _location_point(cls, location: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(location, dict):
            return {}
        # For macro-generated control flow, report the invocation in generated source.
        if isinstance(location.get("expansionLoc"), dict):
            return cls._location_point(location["expansionLoc"])
        if isinstance(location.get("spellingLoc"), dict):
            return cls._location_point(location["spellingLoc"])
        point: Dict[str, Any] = {}
        if location.get("file") is not None:
            point["file"] = str(location["file"])
        if location.get("line") is not None:
            point["line"] = int(location["line"])
        if location.get("col") is not None:
            point["col"] = int(location["col"])
        if location.get("offset") is not None:
            point["offset"] = int(location["offset"])
        return point

    @staticmethod
    def _merge_location(inherited: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(current)
        for key in ("file", "line"):
            if merged.get(key) is None and inherited.get(key) is not None:
                merged[key] = inherited[key]
        return merged

    @classmethod
    def _location_from_offset(
        cls,
        location: Dict[str, Any],
        source_path: str,
        source_bytes: bytes,
    ) -> Dict[str, Any]:
        if location.get("line") is not None or location.get("offset") is None:
            return location
        if not cls._same_file(str(location.get("file") or source_path), source_path):
            return location
        offset = max(0, min(int(location["offset"]), len(source_bytes)))
        prefix = source_bytes[:offset]
        previous_newline = prefix.rfind(b"\n")
        enriched = dict(location)
        enriched["line"] = prefix.count(b"\n") + 1
        if enriched.get("col") is None:
            enriched["col"] = offset + 1 if previous_newline < 0 else offset - previous_newline
        return enriched

    @staticmethod
    def _finding(source_path: str, location: Dict[str, Any], message: str, rule: str) -> Finding:
        finding_location: Dict[str, Any] = {"file": source_path}
        if location.get("line") is not None:
            finding_location["line"] = int(location["line"])
        if location.get("col") is not None:
            finding_location["column"] = int(location["col"])
        return {"tool": "no-loops", "severity": "error", "message": message, "location": finding_location, "rule": rule}

    def _failure(
        self,
        c_file_path: str,
        message: str,
        raw_output: str,
        command: Optional[str] = None,
        timeout: Optional[int] = None,
        timing: Optional[Dict[str, float]] = None,
    ) -> CriticResult:
        metrics: Dict[str, Any] = {"message": message}
        if command is not None:
            metrics["command"] = command
        if timeout is not None:
            metrics["timeout"] = timeout
        if timing:
            metrics.update({"process_real_s": timing.get("real"), "process_user_s": timing.get("user"), "process_sys_s": timing.get("sys")})
        return {
            "tool": self.name,
            "success": False,
            "score": 0.0,
            "summary": message,
            "metrics": metrics,
            "findings": [{"tool": self.name, "severity": "error", "message": message, "location": {"file": c_file_path}, "rule": "clang_ast"}],
            "raw_output": raw_output or message,
        }

    @staticmethod
    def _unpack_command_result(result: Any) -> Tuple[str, str, bool, Optional[int], Dict[str, float]]:
        if isinstance(result, tuple) and len(result) >= 5:
            return result[0] or "", result[1] or "", bool(result[2]), result[3], dict(result[4] or {})
        if isinstance(result, tuple) and len(result) == 4:
            return result[0] or "", result[1] or "", bool(result[2]), result[3], {}
        stdout, stderr, completed = result
        return stdout or "", stderr or "", bool(completed), None, {}

    def _nodes(self, node: Dict[str, Any], inherited_file: str) -> Iterable[Tuple[Dict[str, Any], str]]:
        location = self._source_location(node)
        current_file = str(location.get("file") or inherited_file)
        yield node, current_file
        for child in node.get("inner") or []:
            if isinstance(child, dict):
                yield from self._nodes(child, current_file)
