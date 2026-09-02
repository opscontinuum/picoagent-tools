"""Test fixtures. Makes ``picoagent`` importable from the sibling checkout for local dev."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SIBLING = ROOT.parent / "picoagent"
if _SIBLING.is_dir() and str(_SIBLING) not in sys.path:
    sys.path.insert(0, str(_SIBLING))


def tool_ctx(cwd: Path, tool_call_id: str = "t1") -> SimpleNamespace:
    """A minimal stand-in for picoagent's ToolContext: only cwd/tool_call_id are used."""
    return SimpleNamespace(cwd=cwd, tool_call_id=tool_call_id)
