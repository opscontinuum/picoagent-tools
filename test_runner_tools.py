"""test-runner-tools - stdlib-only detection and execution of a project's test suite.

One tool:
* ``run_tests`` - detects the right test command from marker files in the project root
  (pytest config, a ``tests/`` dir, ``package.json``, ``Cargo.toml``, ``go.mod``) and runs it
  via picoagent.core.tools' spawn_shell/kill_process_tree - the same PowerShell-on-Windows /
  sh-on-POSIX dispatch and timeout/process-tree-kill handling the built-in ``shell`` tool uses,
  reused here rather than duplicated.

``detect_command`` is kept as a pure function (no subprocess, no external toolchain) so the
detection heuristics can be unit tested in isolation from actually running anything.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

_DEFAULT_TIMEOUT = 120
_MAX_OUTPUT_BYTES = 50_000
_MAX_OUTPUT_LINES = 2000

_COMMAND_LABELS = {
    "python3 -m pytest -q": "pytest",
    "python3 -m unittest discover -s tests -v": "unittest",
    "npm test": "npm",
    "cargo test": "cargo",
    "go test ./...": "go",
}

_NO_DETECTION_MESSAGE = (
    "No test command could be detected. Checked (in this order) for: pytest.ini; "
    "pyproject.toml containing [tool.pytest.ini_options]; setup.cfg containing "
    "[tool:pytest]; a tests/ directory; package.json; Cargo.toml; go.mod. "
    "None of those were found under the project root. Pass `command` explicitly to "
    "run a specific test command."
)


def _read_text(path: Path) -> str:
    """Best-effort read; an unreadable marker file is treated as not matching, not an error."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _looks_like_pytest_project(cwd: Path) -> bool:
    """True when a pytest-specific marker is present, checked before the generic tests/ dir."""
    if (cwd / "pytest.ini").is_file():
        return True
    pyproject = cwd / "pyproject.toml"
    if pyproject.is_file() and "[tool.pytest.ini_options]" in _read_text(pyproject):
        return True
    setup_cfg = cwd / "setup.cfg"
    if setup_cfg.is_file() and "[tool:pytest]" in _read_text(setup_cfg):
        return True
    return False


def detect_command(cwd: Path) -> str | None:
    """Pick a test command from project marker files. Returns None if nothing recognized."""
    if _looks_like_pytest_project(cwd):
        return "python3 -m pytest -q"
    if (cwd / "tests").is_dir():
        return "python3 -m unittest discover -s tests -v"
    if (cwd / "package.json").is_file():
        return "npm test"
    if (cwd / "Cargo.toml").is_file():
        return "cargo test"
    if (cwd / "go.mod").is_file():
        return "go test ./..."
    return None


def _extract_unittest_summary(output: str) -> str | None:
    ran = re.search(r"Ran \d+ tests? in [\d.]+s", output) or re.search(r"Ran \d+ tests?", output)
    if not ran:
        return None
    status = re.search(r"^OK(?: \([^)]*\))?$", output, re.M) or re.search(r"^FAILED \([^)]*\)$", output, re.M)
    return f"{ran.group(0)} - {status.group(0)}" if status else ran.group(0)


def _extract_pytest_summary(output: str) -> str | None:
    parts = [f"{m.group(1)} {label}" for label in ("passed", "failed", "error")
             if (m := re.search(rf"(\d+) {label}", output))]
    return ", ".join(parts) if parts else None


def _extract_npm_summary(output: str) -> str | None:
    parts = [f"{m.group(1)} {label}" for label in ("passing", "failing")
             if (m := re.search(rf"(\d+) {label}", output))]
    return ", ".join(parts) if parts else None


def _extract_cargo_summary(output: str) -> str | None:
    match = re.search(r"test result: (?:ok|FAILED)\.[^\n]*", output)
    return match.group(0) if match else None


def _extract_go_summary(output: str) -> str | None:
    lines = re.findall(r"^(?:ok|FAIL)\s+\S+.*$", output, re.M)
    return "; ".join(lines) if lines else None


_EXTRACTORS = {
    "unittest": _extract_unittest_summary,
    "pytest": _extract_pytest_summary,
    "npm": _extract_npm_summary,
    "cargo": _extract_cargo_summary,
    "go": _extract_go_summary,
}


def extract_summary(output: str, detected: str) -> str | None:
    """Try the extractor matching ``detected`` first, then fall back to the others.

    ``detected`` is one of the known labels or ``"custom"`` (an explicit command override,
    whose framework we don't know) - in that case every extractor is tried in turn.
    """
    order = [detected] + [key for key in _EXTRACTORS if key != detected]
    for key in order:
        extractor = _EXTRACTORS.get(key)
        summary = extractor(output) if extractor else None
        if summary:
            return summary
    return None


def _truncate_tail(text: str) -> tuple[str, bool]:
    """Keep the tail of ``text`` - for test output the summary is usually at the end."""
    lines = text.splitlines(keepends=True)
    truncated = False
    if len(lines) > _MAX_OUTPUT_LINES:
        lines = lines[-_MAX_OUTPUT_LINES:]
        truncated = True
    out = "".join(lines)
    raw = out.encode()
    if len(raw) > _MAX_OUTPUT_BYTES:
        raw = raw[-_MAX_OUTPUT_BYTES:]
        out = raw.decode(errors="ignore")
        truncated = True
    return out, truncated


class RunTestsTool:
    name = "run_tests"
    description = (
        "Run the project's test suite. Auto-detects the command from marker files "
        "(pytest config, a tests/ directory, package.json, Cargo.toml, go.mod) unless "
        "`command` is given explicitly. Returns the (possibly truncated) output plus a "
        "one-line pass/fail summary when one can be extracted."
    )
    parameters = {"type": "object", "properties": {
        "command": {"type": "string",
                    "description": "Explicit test command; skips auto-detection when given."},
        "timeout": {"type": "integer",
                    "description": f"Seconds before the command is killed (default {_DEFAULT_TIMEOUT})."}},
        "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.tools import kill_process_tree, spawn_shell
        from picoagent.core.types import ToolResult

        explicit_command = args.get("command")
        if explicit_command:
            command, detected = explicit_command, "custom"
        else:
            command = detect_command(ctx.cwd)
            if command is None:
                return ToolResult(ctx.tool_call_id, _NO_DETECTION_MESSAGE, is_error=True,
                                  details={"command": None, "exit_code": None, "detected": None})
            detected = _COMMAND_LABELS.get(command, "custom")

        timeout = int(args.get("timeout") or _DEFAULT_TIMEOUT)
        # spawn_shell/kill_process_tree (from picoagent.core.tools) dispatch to the platform's
        # real shell - PowerShell on Windows, sh on Linux/macOS - and know how to kill the whole
        # process tree on either; reused here rather than re-duplicating that platform logic.
        proc = await spawn_shell(command, ctx.cwd, {**os.environ, "PICOAGENT": "1"})
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await kill_process_tree(proc)
            details = {"command": command, "exit_code": None, "detected": detected}
            return ToolResult(ctx.tool_call_id, f"Command '{command}' timed out after {timeout}s",
                              is_error=True, details=details)

        output = stdout.decode(errors="replace")
        exit_code = proc.returncode
        summary = extract_summary(output, detected)
        body, truncated = _truncate_tail(output)
        if truncated:
            body += "\n[output truncated; showing tail]"

        header = f"Ran: {command}\n"
        if summary:
            header += f"Summary: {summary}\n"
        content = f"{header}{body}\n[exit code {exit_code}]"
        return ToolResult(ctx.tool_call_id, content, is_error=exit_code != 0,
                          details={"command": command, "exit_code": exit_code, "detected": detected})


def register(api):
    api.register_tool(RunTestsTool())
