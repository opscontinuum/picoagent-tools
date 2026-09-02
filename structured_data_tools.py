"""structured-data-tools - stdlib-only reading and querying of JSON/TOML/YAML config files.

One tool:
* ``structured_data`` - parse a JSON or TOML file (validating it in the process - the parser's
  own error message, with line/column, is returned verbatim on failure) and optionally walk it
  with a small ``.key`` / ``[N]`` path query. YAML files are **not** parsed: the standard library
  has no YAML support and this project is stdlib-only, so a YAML file's raw text is returned
  as-is with an explicit note that it wasn't parsed. That is a deliberate scope decision, not a
  bug - see the tool's own description.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

_QUERY_SEGMENT = re.compile(r"\.([^.\[\]]+)|\[(-?\d+)\]")


def _resolve(cwd: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else cwd / path


def _parse_query(query: str) -> list[str | int]:
    """Split ``a.b[0].c`` into ``["a", "b", 0, "c"]``.

    The first segment has no leading ``.`` or ``[`` marker, so it's taken as a bare key unless
    it starts with ``[``.
    """
    segments: list[str | int] = []
    remainder = query.strip()
    if not remainder:
        return segments

    # The leading segment may have no "." prefix (e.g. "services.web" starts with "services").
    if not remainder.startswith((".", "[")):
        remainder = "." + remainder

    pos = 0
    while pos < len(remainder):
        match = _QUERY_SEGMENT.match(remainder, pos)
        if not match:
            raise ValueError(
                f"cannot parse query at {remainder[pos:]!r}; only .key and [N] segments are supported"
            )
        key, index = match.group(1), match.group(2)
        segments.append(key if key is not None else int(index))
        pos = match.end()
    return segments


def _describe(value: Any) -> str:
    """A short, useful description of what's actually at this point in the structure."""
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"a dict with keys {keys!r}" if keys else "an empty dict"
    if isinstance(value, list):
        return f"a list of length {len(value)}"
    return f"a {type(value).__name__}: {value!r}"


def _walk(data: Any, segments: list[str | int]) -> tuple[Any, str | None]:
    """Follow ``segments`` into ``data``. Returns ``(result, None)`` or ``(None, error_message)``."""
    current = data
    path_so_far = ""
    for segment in segments:
        segment_label = f"[{segment}]" if isinstance(segment, int) else f".{segment}"
        if isinstance(segment, str):
            if not isinstance(current, dict):
                return None, (
                    f"query segment {segment_label!r} (after {path_so_far or '<root>'}) expects a dict, "
                    f"but found {_describe(current)}"
                )
            if segment not in current:
                return None, (
                    f"query segment {segment_label!r} (after {path_so_far or '<root>'}) not found; "
                    f"available keys: {list(current.keys())!r}"
                )
            current = current[segment]
        else:
            if not isinstance(current, list):
                return None, (
                    f"query segment {segment_label!r} (after {path_so_far or '<root>'}) expects a list, "
                    f"but found {_describe(current)}"
                )
            if segment >= len(current) or segment < -len(current):
                return None, (
                    f"query segment {segment_label!r} (after {path_so_far or '<root>'}) is out of range; "
                    f"list has length {len(current)}"
                )
            current = current[segment]
        path_so_far += segment_label
    return current, None


class StructuredDataTool:
    name = "structured_data"
    description = (
        "Parse and optionally query a JSON or TOML file. JSON/TOML parsing is real (via the "
        "stdlib json/tomllib modules) and a syntax error returns the parser's own message "
        "with line/column. YAML (.yaml/.yml) is NOT parsed - the standard library has no YAML "
        "support - the raw file text is returned unparsed for you to read manually; do not "
        "expect structured querying on YAML files. Optional 'query' walks the parsed JSON/TOML "
        "structure with a limited path syntax: dict keys via '.key' and list indices via '[N]' "
        "only (e.g. 'services.web.ports[0]'); no wildcards, slicing, or filters."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "query": {
                "type": "string",
                "description": "Optional path into the parsed JSON/TOML structure, e.g. 'services.web.ports[0]'.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult

        path = _resolve(ctx.cwd, args["path"])
        if not path.exists():
            return ToolResult(ctx.tool_call_id, f"File not found: {path}", is_error=True)
        if path.is_dir():
            return ToolResult(ctx.tool_call_id, f"{path} is a directory, not a file", is_error=True)

        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            return ToolResult(ctx.tool_call_id, f"Cannot read {path}: {exc}", is_error=True)

        suffix = path.suffix.lower()
        query = args.get("query")

        if suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                return ToolResult(ctx.tool_call_id, f"Invalid JSON in {path}: {exc}", is_error=True)
        elif suffix == ".toml":
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                return ToolResult(ctx.tool_call_id, f"Invalid TOML in {path}: {exc}", is_error=True)
        elif suffix in (".yaml", ".yml"):
            note = (
                f"# {path} is YAML; the standard library has no YAML parser and this tool is "
                "stdlib-only, so the content below is raw, unparsed file text - read it manually "
                "(no structured querying is available for YAML)."
            )
            return ToolResult(ctx.tool_call_id, f"{note}\n\n{text}")
        else:
            return ToolResult(
                ctx.tool_call_id,
                f"Unsupported extension {suffix!r} for {path}; expected .json/.toml/.yaml/.yml",
                is_error=True,
            )

        if not query:
            return ToolResult(ctx.tool_call_id, json.dumps(data, indent=2, default=str))

        try:
            segments = _parse_query(query)
        except ValueError as exc:
            return ToolResult(ctx.tool_call_id, str(exc), is_error=True)

        result, error = _walk(data, segments)
        if error is not None:
            return ToolResult(ctx.tool_call_id, error, is_error=True)
        return ToolResult(ctx.tool_call_id, json.dumps(result, indent=2, default=str))


def register(api):
    api.register_tool(StructuredDataTool())
