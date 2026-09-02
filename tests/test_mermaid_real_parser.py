"""Optional check of diagrams against Mermaid's own parser. Skipped unless opted in.

Why this exists: `mermaid_lint` is a regex, and it has been demonstrably wrong. Validating
this project's diagrams against real Mermaid found two the linter had passed and that do not
parse. Regex rules were added for both, but the general point stands - only the real parser
knows the grammar.

Why it is off by default, and stays off:

* It needs Node and the `mermaid`/`jsdom` packages, and this repo is stdlib-only with no
  third-party runtime dependencies. That property is worth keeping.
* Running it means executing a JavaScript runtime, which not every environment permits.

**Nothing here is reachable from the `mermaid_lint` tool.** The tool the model calls never
spawns Node, never shells out, and never touches the network - that is unchanged by this file.
This is developer/CI tooling that only runs when a person points it at a Node install they
provisioned themselves. See dev/README.md for exactly what gets executed.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dev" / "mermaid_parse_check.mjs"

#: The opt-in lives in a file under the user's home, not an environment variable.
#:
#: An env var would be no gate at all against the agent: the shell tool runs commands as the
#: user, and `VAR=x command` sets a variable for the child regardless of what the parent
#: environment allows. That was measured, not assumed. A file is not a boundary either (a
#: shell can write files), but it is at least refused by the *file* tools, and it cannot be
#: set for the duration of one command. See dev/README.md for what this does and does not buy.
GATE_FILE = Path.home() / ".picoagent" / "dev-tools.toml"


def _read_gate() -> dict[str, str]:
    """Parse the opt-in file. Missing or unreadable means "not enabled", never an error."""
    if not GATE_FILE.is_file():
        return {}
    try:
        import tomllib
        with GATE_FILE.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return {}
    section = data.get("mermaid_parser")
    return section if isinstance(section, dict) else {}


_GATE = _read_gate()
MODULES_DIR = _GATE.get("modules_dir")
DOC_PATHS = _GATE.get("paths", str(REPO))


def _reason_to_skip() -> str | None:
    if not MODULES_DIR:
        return f"not enabled in {GATE_FILE} (see dev/README.md)"
    modules = Path(MODULES_DIR).expanduser() / "node_modules"
    for package in ("mermaid", "jsdom"):
        if not (modules / package).is_dir():
            return f"{package} is not installed in {modules}"
    return None


@unittest.skipIf(_reason_to_skip() is not None, _reason_to_skip() or "")
class RealParserTests(unittest.TestCase):
    """Runs only when a developer has explicitly provisioned a Node install and opted in."""

    def test_every_diagram_parses(self):
        result = subprocess.run(
            ["node", str(SCRIPT), "--modules", str(Path(MODULES_DIR).expanduser()),
             *DOC_PATHS.split(os.pathsep)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0,
                         f"mermaid rejected at least one diagram:\n{result.stdout}\n{result.stderr}")

    def test_a_known_bad_diagram_is_rejected(self):
        """Proves the harness reports failures rather than passing everything silently.

        `Loop` collides with the sequenceDiagram `loop ... end` block - one of the two real
        diagrams our regex linter waved through.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.md"
            bad.write_text("```mermaid\nsequenceDiagram\n    participant Loop\n"
                           "    A->>Loop: go\n```\n")
            result = subprocess.run(
                ["node", str(SCRIPT), "--modules", str(Path(MODULES_DIR).expanduser()), str(bad)],
                capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
