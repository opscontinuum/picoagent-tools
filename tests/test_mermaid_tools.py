import asyncio
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
from mermaid_tools import MermaidLintTool, MermaidReferenceTool, DIAGRAM_TYPES


def run(coro):
    return asyncio.run(coro)


class MermaidReferenceTests(unittest.TestCase):
    def test_returns_a_template_for_every_documented_diagram_type(self):
        result = run(MermaidReferenceTool().execute({}, tool_ctx(Path("."))))
        for name in DIAGRAM_TYPES:
            self.assertIn(name, result.content)
        self.assertFalse(result.is_error)


class MermaidLintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content)
        return path

    def test_missing_file_is_an_error(self):
        result = run(MermaidLintTool().execute({"path": "nope.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.content)

    def test_no_mermaid_blocks_is_not_an_error(self):
        self._write("plain.md", "# Just prose\nno diagrams here\n")
        result = run(MermaidLintTool().execute({"path": "plain.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("No", result.content)

    def test_valid_diagram_passes(self):
        self._write("good.md", "# Doc\n```mermaid\ngraph TD\n    A --> B\n```\n")
        result = run(MermaidLintTool().execute({"path": "good.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("Diagram 1: ok", result.content)

    def test_unknown_diagram_type_fails(self):
        self._write("bad.md", "```mermaid\nnotarealtype\n    A --> B\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("known diagram type", result.content)

    def test_unbalanced_brackets_fail(self):
        self._write("bad.md", "```mermaid\ngraph TD\n    A[Start --> B\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("unbalanced", result.content)

    def test_empty_block_fails(self):
        self._write("bad.md", "```mermaid\n\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("empty", result.content)

    # Every case below was verified against mermaid 11.17.2 itself. The linter passed all of
    # them before these rules existed, which is how two broken diagrams reached the docs.

    def test_reserved_participant_name_is_rejected(self):
        self._write("bad.md", "```mermaid\nsequenceDiagram\n    participant Loop as AgentLoop\n"
                              "    User->>Loop: go\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("sequenceDiagram keyword", result.content)

    def test_every_sequence_keyword_is_caught_as_a_participant(self):
        for word in ("loop", "alt", "opt", "par", "note", "end"):
            self._write("w.md", f"```mermaid\nsequenceDiagram\n    participant {word}\n"
                                f"    A->>{word}: go\n```\n")
            result = run(MermaidLintTool().execute({"path": "w.md"}, tool_ctx(self.tmp)))
            self.assertTrue(result.is_error, f"{word} should be rejected")

    def test_a_safe_participant_name_still_passes(self):
        self._write("ok.md", "```mermaid\nsequenceDiagram\n    participant Agent as AgentLoop\n"
                             "    User->>Agent: go\n```\n")
        result = run(MermaidLintTool().execute({"path": "ok.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)

    def test_semicolon_in_a_sequence_message_is_rejected(self):
        self._write("bad.md", "```mermaid\nsequenceDiagram\n    participant A\n    participant B\n"
                              "    A->>B: execute (parallel; edits serialise)\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("ends the statement early", result.content)

    def test_a_semicolon_elsewhere_is_not_flagged(self):
        self._write("ok.md", "```mermaid\nflowchart TD\n    A[do a; then b] --> B\n```\n")
        result = run(MermaidLintTool().execute({"path": "ok.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)

    def test_lowercase_end_as_a_flowchart_node_is_rejected(self):
        self._write("bad.md", "```mermaid\nflowchart TD\n    start --> end\n```\n")
        result = run(MermaidLintTool().execute({"path": "bad.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("closes the enclosing subgraph", result.content)

    def test_capitalised_end_node_is_allowed(self):
        self._write("ok.md", "```mermaid\nflowchart TD\n    start --> End\n```\n")
        result = run(MermaidLintTool().execute({"path": "ok.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)

    def test_subgraph_end_keyword_is_not_mistaken_for_a_node(self):
        self._write("ok.md", "```mermaid\nflowchart TD\n    subgraph one\n        A --> B\n"
                             "    end\n    B --> C\n```\n")
        result = run(MermaidLintTool().execute({"path": "ok.md"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error, result.content)

    def test_multiple_diagrams_are_checked_independently(self):
        self._write("mixed.md", "```mermaid\ngraph TD\n    A --> B\n```\n\n```mermaid\nbogus\n```\n")
        result = run(MermaidLintTool().execute({"path": "mixed.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("Diagram 1: ok", result.content)
        self.assertIn("Diagram 2: FAIL", result.content)


if __name__ == "__main__":
    unittest.main()
