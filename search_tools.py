"""search-tools - stdlib-only regex search across a directory tree.

One tool:
* ``grep_search`` - walk a directory, run a Python regex against every text line, and
  report ``path:line_no: line_text`` hits. Skips ``.git/`` and a handful of common heavy
  directories outright, and additionally honours a *basic subset* of a root-level
  ``.gitignore`` (plain glob lines and trailing-``/`` directory markers matched with
  ``fnmatch``) -- it does not implement negation (``!pattern``) or the full gitignore
  spec, and does not read nested ``.gitignore`` files. No network access, ever.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

ALWAYS_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".tar",
    ".gz", ".bz2", ".xz", ".7z", ".so", ".pyc", ".pyo", ".exe", ".dll", ".dylib",
    ".bin", ".class", ".jar", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
    ".avi", ".mov", ".sqlite", ".db",
}
DEFAULT_MAX_RESULTS = 200
_BINARY_SNIFF_BYTES = 8192


def _resolve(cwd: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else cwd / path


def _display_path(file_path: Path, cwd: Path) -> str:
    """Show paths relative to cwd when possible; falls back to the raw path otherwise."""
    try:
        return str(file_path.relative_to(cwd))
    except ValueError:
        return str(file_path)


def _load_gitignore(root: Path) -> list[tuple[str, bool]]:
    """Parse a root-level ``.gitignore`` into ``(pattern, dir_only)`` pairs.

    Comment and blank lines are dropped; negation (``!pattern``) is not supported and such
    lines are silently skipped, matching the "basic subset" limitation stated in the tool's
    description.
    """
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns = []
    for raw_line in gitignore.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        dir_only = line.endswith("/")
        if dir_only:
            line = line.rstrip("/")
        if line:
            patterns.append((line, dir_only))
    return patterns


def _is_ignored(rel_path: Path, is_dir: bool, patterns: list[tuple[str, bool]]) -> bool:
    """Match ``rel_path`` against the parsed gitignore patterns (full path or basename)."""
    rel_str = rel_path.as_posix()
    for pattern, dir_only in patterns:
        if dir_only and not is_dir:
            continue
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_path.name, pattern):
            return True
    return False


def _looks_binary(path: Path) -> bool:
    """Cheap binary detection: a known extension, or a null byte in the first few KB."""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\0" in chunk


def _iter_files(root: Path, include: str | None) -> list[Path]:
    """List searchable files under ``root``, pruning skipped/ignored directories as we go."""
    if root.is_file():
        return [root]
    gitignore_patterns = _load_gitignore(root)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        kept_dirs = []
        for name in dirnames:
            if name in ALWAYS_SKIP_DIRS:
                continue
            rel = (dirpath_p / name).relative_to(root)
            if _is_ignored(rel, True, gitignore_patterns):
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            if include and not fnmatch.fnmatch(name, include):
                continue
            rel = (dirpath_p / name).relative_to(root)
            if _is_ignored(rel, False, gitignore_patterns):
                continue
            files.append(dirpath_p / name)
    files.sort()
    return files


class GrepSearchTool:
    name = "grep_search"
    description = (
        "Search files under a directory for a Python regex, line by line. Reports "
        "'path:line_no: line_text' for each hit. Always skips .git/ plus common heavy "
        "dirs (__pycache__, node_modules, .venv, venv), and additionally honours a "
        "BASIC SUBSET of a root-level .gitignore (plain glob lines, trailing '/' for "
        "directory-only) -- negation ('!pattern') and the full gitignore spec are NOT "
        "implemented, and nested .gitignore files are not read. Skips obviously-binary "
        "files. Stops after max_results hits and says so. No network access."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex to search for"},
            "path": {"type": "string", "description": "File or directory to search (default '.')"},
            "include": {"type": "string", "description": "Glob to filter filenames, e.g. '*.py'"},
            "case_insensitive": {"type": "boolean", "description": "Case-insensitive match"},
            "max_results": {"type": "integer",
                            "description": f"Stop after this many hits (default {DEFAULT_MAX_RESULTS})"},
        },
        "required": ["pattern"],
    }

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult

        try:
            regex = re.compile(args["pattern"], re.I if args.get("case_insensitive") else 0)
        except re.error as exc:
            return ToolResult(ctx.tool_call_id, str(exc), is_error=True)

        root = _resolve(ctx.cwd, args.get("path") or ".")
        if not root.exists():
            return ToolResult(ctx.tool_call_id, f"Path not found: {root}", is_error=True)

        max_results = int(args.get("max_results") or DEFAULT_MAX_RESULTS)
        include = args.get("include")

        matches: list[str] = []
        stopped = False
        for file_path in _iter_files(root, include):
            if _looks_binary(file_path):
                continue
            try:
                text = file_path.read_text(errors="replace")
            except OSError:
                continue
            display = _display_path(file_path, ctx.cwd)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{display}:{line_no}: {line}")
                    if len(matches) >= max_results:
                        stopped = True
                        break
            if stopped:
                break

        if not matches:
            return ToolResult(ctx.tool_call_id, f"No matches for {args['pattern']!r} under {root}")

        body = "\n".join(matches)
        if stopped:
            body += f"\n[stopped after {max_results} results]"
        return ToolResult(ctx.tool_call_id, body, details={"count": len(matches), "truncated": stopped})


def register(api):
    api.register_tool(GrepSearchTool())
