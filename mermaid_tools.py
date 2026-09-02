"""mermaid-tools - stdlib-only help for writing Mermaid diagrams that actually render.

Two tools:
* ``mermaid_reference`` - a compact cheat sheet of diagram types and minimal templates,
  so the model doesn't have to guess syntax from memory.
* ``mermaid_lint`` - regex-level sanity checks (known diagram type, balanced
  brackets/quotes, non-empty body) on every ```mermaid fenced block in a file. It is not
  a real parser: it catches the errors that most often break rendering, nothing more.
"""
from __future__ import annotations

import re
from pathlib import Path

import mermaid_versions as versions

DIAGRAM_TYPES = {
    "graph": "graph TD\n    A[Start] --> B{Decision}\n    B -->|yes| C[Do it]\n    B -->|no| D[Skip]",
    "flowchart": "flowchart LR\n    A[Start] --> B[End]",
    "sequenceDiagram": "sequenceDiagram\n    Alice->>Bob: Hello\n    Bob-->>Alice: Hi",
    "classDiagram": "classDiagram\n    Animal <|-- Dog\n    Animal : +String name",
    "stateDiagram-v2": "stateDiagram-v2\n    [*] --> Idle\n    Idle --> Running\n    Running --> [*]",
    "erDiagram": 'erDiagram\n    CUSTOMER ||--o{ ORDER : places\n    ORDER {\n        int id\n        string status\n    }',
    "journey": "journey\n    title User signs up\n    section Sign up\n      Visit site: 5: User\n      Fill form: 3: User",
    "gantt": "gantt\n    title Plan\n    section Phase 1\n    Task A :a1, 2024-01-01, 3d",
    "pie": 'pie title Traffic\n    "Direct" : 40\n    "Referral" : 60',
    "mindmap": "mindmap\n  root((Idea))\n    Branch A\n    Branch B",
}

_FENCE = re.compile(r"```mermaid\n(.*?)```", re.S)
# Derived rather than hand-maintained: the version table in mermaid_versions is the list of
# diagram types that exist, so a type added there is recognised here automatically. A stale
# hand-written list rejected valid diagrams like block-beta as "unknown", which is the worst
# kind of lint failure - it is wrong about working syntax.
_ALWAYS_AVAILABLE = ("graph", "flowchart", "sequenceDiagram", "classDiagram", "gantt", "pie",
                     "gitGraph", "zenuml")
_KNOWN_TYPES = tuple(sorted(set(DIAGRAM_TYPES) | set(versions.DIAGRAM_MIN_VERSION)
                            | set(_ALWAYS_AVAILABLE), key=len, reverse=True))
_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}

# Words the sequenceDiagram grammar owns. Using one as a participant name is a parse error,
# not a style problem - `participant Loop` collides with the `loop ... end` block. Confirmed
# by running these through mermaid 11.17.2 rather than inferred from the docs.
_SEQUENCE_RESERVED = {"loop", "alt", "else", "opt", "par", "and", "critical", "break",
                      "rect", "note", "end", "activate", "deactivate", "autonumber"}
_PARTICIPANT = re.compile(r"^\s*(?:participant|actor)\s+([A-Za-z_][\w-]*)", re.M)
# A message's text runs to end of line, except that ";" ends the statement early.
_SEQUENCE_MESSAGE = re.compile(r"^\s*\w[\w-]*\s*-?-?>>?\+?-?[->]*\s*\w[\w-]*\s*:(.*)$", re.M)
# Lowercase "end" as a flowchart node id closes the enclosing subgraph instead. "End" is fine.
# Only an "end" that is an edge endpoint or carries a shape is a node - a bare "end" on its
# own line is the legitimate subgraph terminator and must not be flagged.
_ARROW = r"(?:-\.-+>|--+>|==+>|--+)"
_FLOWCHART_END_NODE = re.compile(rf"{_ARROW}\s*end\b|\bend\s*(?:{_ARROW}|\[|\(|\{{)", re.M)


def _resolve(cwd: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else cwd / path


def _check_block(body: str) -> list[str]:
    """Return a list of problems found in one diagram body (empty list = clean)."""
    issues = []
    stripped = body.strip()
    if not stripped:
        issues.append("block is empty")
        return issues
    first_line = stripped.splitlines()[0].strip()
    if not first_line.startswith(_KNOWN_TYPES):
        issues.append(f"first line {first_line!r} doesn't start with a known diagram type "
                       f"({', '.join(_KNOWN_TYPES)})")
    for open_ch, close_ch in _BRACKET_PAIRS.items():
        opened, closed = stripped.count(open_ch), stripped.count(close_ch)
        if opened != closed:
            issues.append(f"unbalanced {open_ch}{close_ch}: {opened} open vs {closed} close")
    if stripped.count('"') % 2:
        issues.append("odd number of double quotes (an unterminated label)")
    if len(stripped.splitlines()) < 2:
        issues.append("only a diagram-type line, no actual content")
    issues += _check_reserved_words(stripped, first_line)
    return issues


def _check_reserved_words(body: str, first_line: str) -> list[str]:
    """Catch grammar collisions that look like ordinary text.

    These are the failures balanced-bracket checking cannot see: the diagram is well-formed
    to a regex and still refuses to parse, because a name or a character belongs to the
    grammar. Both rules below were found by running real diagrams through mermaid, not by
    reading the docs - this linter had passed both.
    """
    issues = []
    if first_line.startswith("sequenceDiagram"):
        for name in _PARTICIPANT.findall(body):
            if name.lower() in _SEQUENCE_RESERVED:
                issues.append(f"participant {name!r} is a sequenceDiagram keyword and will not "
                              f"parse - rename it (e.g. {name}Actor)")
        for text in _SEQUENCE_MESSAGE.findall(body):
            if ";" in text:
                issues.append(f"';' in message text ends the statement early: {text.strip()!r}")
    elif first_line.startswith(("flowchart", "graph")):
        if _FLOWCHART_END_NODE.search(body):
            issues.append("lowercase 'end' as a node id closes the enclosing subgraph - "
                          "capitalise it ('End') or rename it")
    return issues


class MermaidReferenceTool:
    name = "mermaid_reference"
    description = ("Look up minimal, correct templates for every common Mermaid diagram type "
                   "(flowchart, sequence, class, state, ER, journey, gantt, pie, mindmap). "
                   "Call this before writing a diagram type you're unsure of.")
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        body = "\n\n".join(f"# {name}\n```mermaid\n{template}\n```" for name, template in DIAGRAM_TYPES.items())
        return ToolResult(ctx.tool_call_id, body)


class MermaidLintTool:
    name = "mermaid_lint"
    description = (
        "Sanity-check every ```mermaid fenced block in a markdown file: known diagram type, "
        "balanced brackets/quotes, non-empty body, and grammar collisions (reserved words as "
        "sequence participants, ';' in message text, lowercase 'end' as a flowchart node). "
        "Pass 'target' to also check what a specific renderer supports - 'gitlab:17.2' or "
        "'mermaid:10.7.0' - which catches diagram types and syntax too new for it, plus "
        "GitLab's size limits. Not a real parser: it catches known breakage, not everything."
    )
    parameters = {"type": "object", "properties": {
        "path": {"type": "string"},
        "target": {"type": "string",
                   "description": "Renderer to check against, e.g. 'gitlab:17.2' or "
                                  "'mermaid:10.7.0'. Omit to check syntax only."}},
        "required": ["path"]}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        path = _resolve(ctx.cwd, args["path"])
        if not path.exists():
            return ToolResult(ctx.tool_call_id, f"File not found: {path}", is_error=True)

        target, mermaid_version = args.get("target"), None
        if target:
            mermaid_version, error = versions.resolve_target(target)
            if error:
                return ToolResult(ctx.tool_call_id, error, is_error=True)

        text = path.read_text(errors="replace")
        blocks = _FENCE.findall(text)
        if not blocks:
            return ToolResult(ctx.tool_call_id, f"No ```mermaid blocks found in {path}")

        lines, any_issue = [], False
        for i, block in enumerate(blocks, start=1):
            issues = _check_block(block)
            if mermaid_version:
                first_line = block.strip().splitlines()[0].strip() if block.strip() else ""
                issues += versions.check_supported(block, first_line, mermaid_version)
                if target.lower().startswith("gitlab"):
                    issues += versions.check_gitlab_limits(block)
            if issues:
                any_issue = True
                lines.append(f"Diagram {i}: FAIL\n  - " + "\n  - ".join(issues))
            else:
                lines.append(f"Diagram {i}: ok")

        if mermaid_version and target.lower().startswith("gitlab"):
            page_issues = versions.check_page_limits(blocks)
            if page_issues:
                any_issue = True
                lines.append("Page totals: FAIL\n  - " + "\n  - ".join(page_issues))

        header = f"{len(blocks)} diagram(s) checked in {path}"
        if mermaid_version:
            header += f" against {target} (Mermaid {mermaid_version})"
        return ToolResult(ctx.tool_call_id, header + "\n" + "\n".join(lines), is_error=any_issue)


#: Opt-in file for the developer-only real-parser check (see dev/README.md). The model has no
#: legitimate reason to touch it, and every reason not to: writing it is how a developer says
#: "it is fine to execute Node on this machine". Guarded below.
DEV_TOOLS_FILE = Path.home() / ".picoagent" / "dev-tools.toml"


async def guard_dev_tools_file(event: dict, rt) -> dict | None:
    """Refuse any tool call whose path argument names the dev-tools opt-in file.

    Applies to every tool rather than a named list, so a tool added later doesn't inherit a
    bypass. This closes the file tools - read, write, edit, grep_search, structured_data.
    It does **not** close the shell: a shell command runs as the user and can write any file
    the user can, which is measured behaviour, not a theoretical gap. dev/README.md says so
    plainly rather than implying containment this doesn't have.
    """
    for key in ("path", "file", "filename", "filepath"):
        raw = event["args"].get(key)
        if not raw:
            continue
        try:
            if Path(str(raw)).expanduser().resolve() == DEV_TOOLS_FILE.resolve():
                return {"block": True,
                        "reason": "dev-tools.toml enables developer-only execution of Node and "
                                  "is not the agent's to read or change"}
        except (OSError, RuntimeError):
            continue
    return None


def register(api):
    api.register_tool(MermaidReferenceTool())
    api.register_tool(MermaidLintTool())
    api.on("tool_call", guard_dev_tools_file)
