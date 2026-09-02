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
_KNOWN_TYPES = tuple(DIAGRAM_TYPES) + ("timeline", "quadrantChart", "gitGraph", "requirementDiagram", "C4Context")
_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}


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
    description = ("Sanity-check every ```mermaid fenced block in a markdown file: known diagram "
                   "type, balanced brackets/quotes, non-empty body. Not a real parser - catches "
                   "the common breakage, not everything. Run this after writing diagrams.")
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    async def execute(self, args: dict, ctx) -> "ToolResult":
        from picoagent.core.types import ToolResult
        path = _resolve(ctx.cwd, args["path"])
        if not path.exists():
            return ToolResult(ctx.tool_call_id, f"File not found: {path}", is_error=True)
        text = path.read_text(errors="replace")
        blocks = _FENCE.findall(text)
        if not blocks:
            return ToolResult(ctx.tool_call_id, f"No ```mermaid blocks found in {path}")

        lines, any_issue = [], False
        for i, block in enumerate(blocks, start=1):
            issues = _check_block(block)
            if issues:
                any_issue = True
                lines.append(f"Diagram {i}: FAIL\n  - " + "\n  - ".join(issues))
            else:
                lines.append(f"Diagram {i}: ok")
        summary = f"{len(blocks)} diagram(s) checked in {path}\n" + "\n".join(lines)
        return ToolResult(ctx.tool_call_id, summary, is_error=any_issue)


def register(api):
    api.register_tool(MermaidReferenceTool())
    api.register_tool(MermaidLintTool())
