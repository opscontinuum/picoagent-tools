import asyncio
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
from search_tools import GrepSearchTool


def run(coro):
    return asyncio.run(coro)


class GrepSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_no_matches_is_not_an_error(self):
        self._write("a.txt", "nothing interesting here\n")
        result = run(GrepSearchTool().execute({"pattern": "needle"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("No matches", result.content)

    def test_matches_are_formatted_as_path_line_text(self):
        self._write("a.txt", "first line\nsecond needle line\nthird line\n")
        result = run(GrepSearchTool().execute({"pattern": "needle"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("a.txt:2: second needle line", result.content)

    def test_case_insensitive_flag(self):
        self._write("a.txt", "NEEDLE in a haystack\n")
        no_flag = run(GrepSearchTool().execute({"pattern": "needle"}, tool_ctx(self.tmp)))
        self.assertIn("No matches", no_flag.content)

        with_flag = run(GrepSearchTool().execute(
            {"pattern": "needle", "case_insensitive": True}, tool_ctx(self.tmp)))
        self.assertFalse(with_flag.is_error)
        self.assertIn("a.txt:1:", with_flag.content)

    def test_include_glob_filters_filenames(self):
        self._write("match.py", "target\n")
        self._write("match.txt", "target\n")
        result = run(GrepSearchTool().execute(
            {"pattern": "target", "include": "*.py"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("match.py:1:", result.content)
        self.assertNotIn("match.txt", result.content)

    def test_gitignore_excludes_matching_file(self):
        self._write(".gitignore", "ignored.txt\n")
        self._write("ignored.txt", "target here\n")
        self._write("kept.txt", "target here\n")
        result = run(GrepSearchTool().execute({"pattern": "target"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("kept.txt:1:", result.content)
        self.assertNotIn("ignored.txt", result.content)

    def test_gitignore_directory_marker_excludes_whole_dir(self):
        self._write(".gitignore", "build/\n")
        self._write("build/output.txt", "target here\n")
        self._write("src/output.txt", "target here\n")
        result = run(GrepSearchTool().execute({"pattern": "target"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("output.txt:1:", result.content)
        self.assertNotIn("build", result.content)

    def test_invalid_regex_is_an_error(self):
        result = run(GrepSearchTool().execute({"pattern": "("}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertTrue(result.content)  # exact re.error message, non-empty

    def test_max_results_truncation_is_flagged(self):
        self._write("a.txt", "\n".join(f"needle {i}" for i in range(10)) + "\n")
        result = run(GrepSearchTool().execute(
            {"pattern": "needle", "max_results": 3}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(3, result.content.count("needle"))
        self.assertIn("[stopped after 3 results]", result.content)

    def test_missing_path_is_an_error(self):
        result = run(GrepSearchTool().execute(
            {"pattern": "x", "path": "does/not/exist"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.content)

    def test_git_directory_is_always_skipped(self):
        self._write(".git/config", "target\n")
        self._write("kept.txt", "target\n")
        result = run(GrepSearchTool().execute({"pattern": "target"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("kept.txt:1:", result.content)
        self.assertNotIn(".git", result.content)

    def test_binary_extension_is_skipped(self):
        self._write("kept.txt", "target\n")
        binary_path = self.tmp / "image.png"
        binary_path.write_bytes(b"target" + bytes([0, 1, 2, 3]))
        result = run(GrepSearchTool().execute({"pattern": "target"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("kept.txt:1:", result.content)
        self.assertNotIn("image.png", result.content)


if __name__ == "__main__":
    unittest.main()
