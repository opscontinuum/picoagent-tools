"""git-tools - stdlib-only, read-only introspection of a local git repository.

Four tools, all strictly non-mutating: they only ever invoke local, read-only ``git``
subcommands (``status``, ``diff``, ``log``, ``rev-parse``) via ``asyncio.create_subprocess_exec``
with a fixed argument list (never a shell string built from model input, and never a
subcommand that writes to the repo or talks to a remote - no ``fetch``/``pull``/``push``/
``commit``/``add``/``reset``/``checkout``). The point is to hand the model real facts
(what changed, what the history looks like) so *it* can write commit messages and PR
descriptions - not to synthesize or apply anything itself.

* ``git_status`` - a parsed, human-readable summary of ``git status --porcelain=v1 --branch``.
* ``git_diff`` - working-tree or staged diff, optionally scoped to one path, truncated.
* ``git_log`` - the last N commits, one line each.
* ``git_pr_summary`` - raw facts only (commit list + diffstat) between an autodetected or
  given base ref and HEAD. Does not write prose; that's the calling model's job.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 15
DEFAULT_DIFF_MAX_LINES = 1000
DEFAULT_LOG_COUNT = 10
MAX_LOG_COUNT = 200
CANDIDATE_BASES = ("origin/main", "origin/master", "main", "master")


@dataclass
class _GitRun:
    """Outcome of invoking the local git binary. ``ok`` is False for any failure mode."""
    ok: bool
    stdout: str = ""
    stderr: str = ""
    message: str = ""   # set when ok is False: what went wrong, ready to show the model


async def _run_git(cwd: Path, args: list[str], timeout: int = DEFAULT_TIMEOUT) -> _GitRun:
    """Run ``git <args>`` in ``cwd`` and capture output. Never raises.

    Distinguishes three failure modes so the caller can report something useful: git isn't
    installed, the command timed out, or git itself exited non-zero (most commonly "not a
    git repository").
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return _GitRun(ok=False, message="git is not installed (or not found on PATH)")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return _GitRun(ok=False, message=f"git {' '.join(args)} timed out after {timeout}s")

    out, err = stdout.decode(errors="replace"), stderr.decode(errors="replace")
    if proc.returncode != 0:
        return _GitRun(ok=False, stdout=out, stderr=err,
                       message=err.strip() or f"git {' '.join(args)} failed (exit {proc.returncode})")
    return _GitRun(ok=True, stdout=out, stderr=err)


def _resolve_path(cwd: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else cwd / path


def _truncate_lines(text: str, max_lines: int) -> tuple[str, int, bool]:
    """Keep the head of ``text`` (the start of a diff usually matters most).

    Returns ``(kept_text, total_line_count, was_truncated)``.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, len(lines), False
    return "\n".join(lines[:max_lines]), len(lines), True


def _parse_status(porcelain: str) -> tuple[str, list[str], list[str], list[str]]:
    """Split ``git status --porcelain=v1 --branch`` output into branch header + three buckets.

    Status codes: column 1 is the staged (index) state, column 2 the unstaged (worktree)
    state, ``??`` marks an untracked path. A path can appear in both staged and unstaged
    (e.g. staged then edited again).
    """
    lines = porcelain.splitlines()
    branch = ""
    entries = lines
    if lines and lines[0].startswith("## "):
        branch = lines[0][3:]
        entries = lines[1:]

    staged, unstaged, untracked = [], [], []
    for line in entries:
        if not line:
            continue
        code, path = line[:2], line[3:]
        if code == "??":
            untracked.append(path)
            continue
        x, y = code[0], code[1]
        if x != " ":
            staged.append(f"{x} {path}")
        if y != " ":
            unstaged.append(f"{y} {path}")
    return branch, staged, unstaged, untracked


class GitStatusTool:
    """Human-readable, categorized ``git status``."""
    name = "git_status"
    description = ("Show the working tree status: current branch/tracking info, and staged, "
                   "unstaged and untracked files. Read-only - runs 'git status' only.")
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        run = await _run_git(ctx.cwd, ["status", "--porcelain=v1", "--branch"])
        if not run.ok:
            return ToolResult(ctx.tool_call_id, run.message, is_error=True)

        branch, staged, unstaged, untracked = _parse_status(run.stdout)
        parts = [f"Branch: {branch or '(unknown)'}"]

        def _section(title: str, items: list[str]) -> str:
            if not items:
                return f"{title}: (none)"
            return f"{title} ({len(items)}):\n" + "\n".join(f"  {i}" for i in items)

        parts.append(_section("Staged", staged))
        parts.append(_section("Unstaged", unstaged))
        parts.append(_section("Untracked", untracked))
        clean = not (staged or unstaged or untracked)
        if clean:
            parts.append("Working tree is clean.")
        return ToolResult(ctx.tool_call_id, "\n\n".join(parts),
                          details={"branch": branch, "staged": staged, "unstaged": unstaged,
                                    "untracked": untracked, "clean": clean})


class GitDiffTool:
    """Working-tree or staged diff, optionally scoped to a path."""
    name = "git_diff"
    description = ("Show the diff of uncommitted changes (working tree by default, or staged "
                   "with staged=true), optionally scoped to one path. Long diffs are truncated "
                   "(head kept). Read-only - runs 'git diff' only.")
    parameters = {"type": "object", "properties": {
        "staged": {"type": "boolean", "description": "diff the index instead of the working tree"},
        "path": {"type": "string", "description": "scope the diff to this file or directory"},
        "max_lines": {"type": "integer", "description": f"truncate output past this many lines "
                       f"(default {DEFAULT_DIFF_MAX_LINES})"},
    }, "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        cmd = ["diff", "--staged"] if args.get("staged") else ["diff"]
        if args.get("path"):
            cmd += ["--", args["path"]]

        run = await _run_git(ctx.cwd, cmd)
        if not run.ok:
            return ToolResult(ctx.tool_call_id, run.message, is_error=True)

        if not run.stdout.strip():
            scope = " (staged)" if args.get("staged") else ""
            return ToolResult(ctx.tool_call_id, f"No differences{scope}.")

        max_lines = int(args.get("max_lines") or DEFAULT_DIFF_MAX_LINES)
        body, total_lines, truncated = _truncate_lines(run.stdout, max_lines)
        if truncated:
            body += f"\n\n[truncated: showing first {max_lines} of {total_lines} lines]"
        return ToolResult(ctx.tool_call_id, body, details={"total_lines": total_lines, "truncated": truncated})


class GitLogTool:
    """Recent commit history, one line per commit."""
    name = "git_log"
    description = ("Show recent commit history, one line per commit (most recent first). "
                   "Read-only - runs 'git log --oneline' only.")
    parameters = {"type": "object", "properties": {
        "count": {"type": "integer", "description": f"number of commits (default {DEFAULT_LOG_COUNT}, "
                   f"max {MAX_LOG_COUNT})"},
    }, "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        count = int(args.get("count") or DEFAULT_LOG_COUNT)
        count = max(1, min(count, MAX_LOG_COUNT))

        run = await _run_git(ctx.cwd, ["log", "--oneline", "-n", str(count)])
        if not run.ok:
            return ToolResult(ctx.tool_call_id, run.message, is_error=True)
        if not run.stdout.strip():
            return ToolResult(ctx.tool_call_id, "No commits yet.")
        return ToolResult(ctx.tool_call_id, run.stdout.rstrip("\n"))


class GitPrSummaryTool:
    """Raw facts (commit list + diffstat) between a base ref and HEAD, for the model to write from."""
    name = "git_pr_summary"
    description = ("Return raw facts for writing a PR description: the commit list and diffstat "
                   "between a base branch and HEAD. If 'base' is omitted, autodetects one of "
                   "origin/main, origin/master, main, master (whichever exists first). Does not "
                   "generate any prose itself - just the facts. Read-only - runs 'git log'/'git diff' "
                   "only, no remote operations.")
    parameters = {"type": "object", "properties": {
        "base": {"type": "string", "description": "ref to compare against (e.g. 'origin/main'); "
                  "autodetected if omitted"},
    }, "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        base = args.get("base")
        tried = [base] if base else []

        if base:
            verify = await _run_git(ctx.cwd, ["rev-parse", "--verify", "--quiet", base])
            if not verify.ok:
                return ToolResult(ctx.tool_call_id,
                                  f"Base ref {base!r} does not exist in this repository.", is_error=True)
        else:
            base = None
            for candidate in CANDIDATE_BASES:
                tried.append(candidate)
                verify = await _run_git(ctx.cwd, ["rev-parse", "--verify", "--quiet", candidate])
                if verify.ok:
                    base = candidate
                    break
            if base is None:
                return ToolResult(
                    ctx.tool_call_id,
                    "Could not autodetect a base branch. Tried: " + ", ".join(tried) +
                    ". Pass 'base' explicitly.", is_error=True)

        commits = await _run_git(ctx.cwd, ["log", "--oneline", f"{base}..HEAD"])
        if not commits.ok:
            return ToolResult(ctx.tool_call_id, commits.message, is_error=True)
        diffstat = await _run_git(ctx.cwd, ["diff", f"{base}...HEAD", "--stat"])
        if not diffstat.ok:
            return ToolResult(ctx.tool_call_id, diffstat.message, is_error=True)

        commit_list = commits.stdout.rstrip("\n") or "(no commits ahead of base)"
        stat = diffstat.stdout.rstrip("\n") or "(no changes)"
        body = (f"Base: {base}\n\n"
                f"Commits ahead of base:\n{commit_list}\n\n"
                f"Diffstat ({base}...HEAD):\n{stat}")
        return ToolResult(ctx.tool_call_id, body, details={"base": base})


def register(api):
    api.register_tool(GitStatusTool())
    api.register_tool(GitDiffTool())
    api.register_tool(GitLogTool())
    api.register_tool(GitPrSummaryTool())
