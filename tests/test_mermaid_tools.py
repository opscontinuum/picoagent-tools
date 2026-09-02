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

    def test_multiple_diagrams_are_checked_independently(self):
        self._write("mixed.md", "```mermaid\ngraph TD\n    A --> B\n```\n\n```mermaid\nbogus\n```\n")
        result = run(MermaidLintTool().execute({"path": "mixed.md"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("Diagram 1: ok", result.content)
        self.assertIn("Diagram 2: FAIL", result.content)


if __name__ == "__main__":
    unittest.main()
