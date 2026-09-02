import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
from git_tools import GitDiffTool, GitLogTool, GitPrSummaryTool, GitStatusTool


def run(coro):
    return asyncio.run(coro)


def _git(cwd: Path, *args: str) -> None:
    """Run a git command with an isolated identity so this doesn't depend on global config."""
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _init_repo(tmp: Path) -> None:
    _git(tmp, "init", "-q", "-b", "main")


def _commit(tmp: Path, filename: str, content: str, message: str) -> None:
    (tmp / filename).write_text(content)
    _git(tmp, "add", filename)
    _git(tmp, "commit", "-q", "-m", message)


class GitToolsRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _init_repo(self.tmp)
        _commit(self.tmp, "README.md", "hello\n", "initial commit")

    # -- git_status ---------------------------------------------------------

    def test_status_reports_clean_tree(self):
        result = run(GitStatusTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("clean", result.content.lower())
        self.assertTrue(result.details["clean"])

    def test_status_reports_staged_unstaged_and_untracked(self):
        # unstaged: modify the tracked file
        (self.tmp / "README.md").write_text("hello\nmodified\n")
        # staged: add a new file to the index
        (self.tmp / "staged.txt").write_text("new\n")
        _git(self.tmp, "add", "staged.txt")
        # untracked: a file nobody has touched with git yet
        (self.tmp / "untracked.txt").write_text("who knows\n")

        result = run(GitStatusTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("README.md", result.content)
        self.assertIn("staged.txt", result.content)
        self.assertIn("untracked.txt", result.content)
        self.assertIn("untracked.txt", result.details["untracked"][0])
        self.assertTrue(any("staged.txt" in e for e in result.details["staged"]))
        self.assertTrue(any("README.md" in e for e in result.details["unstaged"]))

    # -- git_diff -------------------------------------------------------------

    def test_diff_shows_unstaged_added_line(self):
        (self.tmp / "README.md").write_text("hello\nbrand new line\n")
        result = run(GitDiffTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("+brand new line", result.content)

    def test_diff_staged_differs_from_unstaged(self):
        (self.tmp / "README.md").write_text("hello\nstaged line\n")
        _git(self.tmp, "add", "README.md")
        (self.tmp / "extra.txt").write_text("unstaged only\n")

        staged_result = run(GitDiffTool().execute({"staged": True}, tool_ctx(self.tmp)))
        unstaged_result = run(GitDiffTool().execute({}, tool_ctx(self.tmp)))

        self.assertIn("+staged line", staged_result.content)
        self.assertNotIn("unstaged only", staged_result.content)
        # extra.txt is untracked, so plain `git diff` won't show it either - use a
        # tracked-file edit to prove the staged/unstaged split instead.
        (self.tmp / "README.md").write_text("hello\nstaged line\nfurther unstaged edit\n")
        unstaged_result = run(GitDiffTool().execute({}, tool_ctx(self.tmp)))
        self.assertIn("+further unstaged edit", unstaged_result.content)
        self.assertNotIn("further unstaged edit", staged_result.content)

    def test_diff_no_changes_reports_none(self):
        result = run(GitDiffTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("No differences", result.content)

    def test_diff_scoped_to_path(self):
        (self.tmp / "README.md").write_text("hello\nchanged\n")
        (self.tmp / "other.txt").write_text("tracked too\n")
        _git(self.tmp, "add", "other.txt")
        _git(self.tmp, "commit", "-q", "-m", "add other.txt")
        (self.tmp / "other.txt").write_text("tracked too\nedited\n")

        result = run(GitDiffTool().execute({"path": "other.txt"}, tool_ctx(self.tmp)))
        self.assertIn("other.txt", result.content)
        self.assertNotIn("README.md", result.content)

    def test_diff_truncates_long_output(self):
        lines = "\n".join(f"line {i}" for i in range(500))
        (self.tmp / "README.md").write_text(lines + "\n")
        result = run(GitDiffTool().execute({"max_lines": 10}, tool_ctx(self.tmp)))
        self.assertIn("truncated", result.content)
        self.assertTrue(result.details["truncated"])

    # -- git_log --------------------------------------------------------------

    def test_log_contains_real_commit_message(self):
        _commit(self.tmp, "second.txt", "content\n", "add second file")
        result = run(GitLogTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("add second file", result.content)
        self.assertIn("initial commit", result.content)

    def test_log_count_is_respected(self):
        for i in range(5):
            _commit(self.tmp, f"f{i}.txt", "x\n", f"commit {i}")
        result = run(GitLogTool().execute({"count": 2}, tool_ctx(self.tmp)))
        self.assertEqual(len(result.content.splitlines()), 2)

    def test_log_count_is_clamped(self):
        result = run(GitLogTool().execute({"count": 999999}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)  # doesn't blow up; just returns what exists

    # -- git_pr_summary ---------------------------------------------------------

    def test_pr_summary_lists_commits_ahead_of_explicit_base(self):
        _git(self.tmp, "checkout", "-q", "-b", "feature")
        _commit(self.tmp, "feature.txt", "feature work\n", "add feature work")

        result = run(GitPrSummaryTool().execute({"base": "main"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("add feature work", result.content)
        self.assertIn("feature.txt", result.content)
        self.assertEqual(result.details["base"], "main")

    def test_pr_summary_autodetects_main_as_base(self):
        _git(self.tmp, "checkout", "-q", "-b", "feature")
        _commit(self.tmp, "feature.txt", "feature work\n", "add feature work")

        result = run(GitPrSummaryTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.details["base"], "main")
        self.assertIn("add feature work", result.content)

    def test_pr_summary_unknown_base_is_an_error(self):
        result = run(GitPrSummaryTool().execute({"base": "no-such-ref"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("no-such-ref", result.content)

    def test_pr_summary_no_resolvable_base_lists_what_was_tried(self):
        # A repo with no main/master branch at all (we're still on it, just renamed).
        _git(self.tmp, "branch", "-m", "main", "trunk")
        result = run(GitPrSummaryTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("origin/main", result.content)
        self.assertIn("origin/master", result.content)
        self.assertIn("main", result.content)
        self.assertIn("master", result.content)


class GitToolsNotARepoTests(unittest.TestCase):
    """None of the four tools should crash outside a git repository - they should error cleanly."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())  # deliberately never `git init`-ed

    def test_status_errors_cleanly(self):
        result = run(GitStatusTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertTrue(result.content.strip())

    def test_diff_errors_cleanly(self):
        result = run(GitDiffTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertTrue(result.content.strip())

    def test_log_errors_cleanly(self):
        result = run(GitLogTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertTrue(result.content.strip())

    def test_pr_summary_errors_cleanly(self):
        result = run(GitPrSummaryTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertTrue(result.content.strip())


if __name__ == "__main__":
    unittest.main()
