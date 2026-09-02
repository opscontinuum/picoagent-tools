"""Version targeting: does a diagram render on the renderer the reader actually uses?"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
import mermaid_versions as versions
from mermaid_tools import MermaidLintTool


def run(coro):
    return asyncio.run(coro)


class GitLabBundleTests(unittest.TestCase):
    def test_the_long_pin_covers_its_whole_range(self):
        """16.9 through 18.10 all shipped 10.7.0 - the reason this feature exists."""
        for version in ("16.9", "17.0", "17.11", "18.0", "18.10"):
            self.assertEqual(versions.mermaid_for_gitlab(version), "10.7.0", version)

    def test_19_x_is_mermaid_11(self):
        self.assertEqual(versions.mermaid_for_gitlab("19.0"), "11.13.0")
        self.assertEqual(versions.mermaid_for_gitlab("19.3"), "11.13.0")

    def test_18_11_is_treated_conservatively_as_v10(self):
        """11.13.0 exists there but sits behind use_mermaid_v11; assume the flag is off."""
        self.assertEqual(versions.mermaid_for_gitlab("18.11"), "10.7.0")

    def test_older_releases_resolve(self):
        self.assertEqual(versions.mermaid_for_gitlab("15.0"), "9.1.1")
        self.assertEqual(versions.mermaid_for_gitlab("14.10"), "8.13.10")

    def test_a_version_before_the_table_is_unknown_rather_than_guessed(self):
        self.assertIsNone(versions.mermaid_for_gitlab("12.9"))


class ResolveTargetTests(unittest.TestCase):
    def test_gitlab_target_resolves_to_a_bundled_version(self):
        self.assertEqual(versions.resolve_target("gitlab:17.2"), ("10.7.0", None))

    def test_mermaid_target_is_used_directly(self):
        self.assertEqual(versions.resolve_target("mermaid:10.7.0"), ("10.7.0", None))

    def test_an_unknown_gitlab_version_is_an_error_not_a_guess(self):
        found, error = versions.resolve_target("gitlab:12.1")
        self.assertIsNone(found)
        self.assertIn("no bundled Mermaid version recorded", error)

    def test_a_malformed_target_explains_the_format(self):
        self.assertIn("should look like", versions.resolve_target("17.2")[1])

    def test_an_unknown_kind_is_rejected(self):
        self.assertIn("unknown target kind", versions.resolve_target("github:1.0")[1])


class SupportedSyntaxTests(unittest.TestCase):
    def test_block_beta_is_flagged_on_the_pinned_gitlab_version(self):
        """block-beta landed in 10.8.0, one release after GitLab's long pin at 10.7.0."""
        issues = versions.check_supported("block-beta\n  a", "block-beta", "10.7.0")
        self.assertTrue(any("block-beta needs Mermaid 10.8.0" in i for i in issues))

    def test_xychart_is_allowed_on_the_same_version(self):
        """10.6.0, so it just squeaks in - the boundary that makes the table worth having."""
        self.assertEqual(versions.check_supported("xychart-beta\n  x", "xychart-beta", "10.7.0"), [])

    def test_state_v2_is_matched_before_plain_state(self):
        self.assertEqual(versions.diagram_type_of("stateDiagram-v2"), "stateDiagram-v2")
        self.assertEqual(versions.diagram_type_of("stateDiagram"), "stateDiagram")

    def test_expanded_node_shapes_are_flagged_below_11_3(self):
        body = "flowchart TD\n  A@{ shape: rounded }"
        self.assertTrue(versions.check_supported(body, "flowchart TD", "10.7.0"))
        self.assertEqual(versions.check_supported(body, "flowchart TD", "11.13.0"), [])

    def test_bidirectional_sequence_arrows_are_flagged_below_11(self):
        body = "sequenceDiagram\n  A<<->>B: sync"
        self.assertTrue(versions.check_supported(body, "sequenceDiagram", "10.7.0"))
        self.assertEqual(versions.check_supported(body, "sequenceDiagram", "11.13.0"), [])

    def test_a_plain_flowchart_is_fine_on_every_supported_version(self):
        self.assertEqual(versions.check_supported("flowchart TD\n  A --> B", "flowchart TD", "8.4.8"), [])


class GitLabLimitTests(unittest.TestCase):
    def test_an_oversized_diagram_is_reported_as_a_soft_failure(self):
        issues = versions.check_gitlab_limits("graph TD\n" + "  A --> B\n" * 400)
        self.assertTrue(issues)
        self.assertIn("click-to-render", issues[0])

    def test_a_normal_diagram_is_within_limits(self):
        self.assertEqual(versions.check_gitlab_limits("graph TD\n  A --> B"), [])

    def test_excessive_link_chaining_is_flagged(self):
        issues = versions.check_gitlab_limits("graph TD\n  A --> " + " & ".join("N" * 40))
        self.assertTrue(any("link chainings" in i for i in issues))

    def test_the_page_character_budget_is_a_running_total(self):
        """Each diagram is under the cap; together they are not."""
        blocks = ["graph TD\n" + "  A --> B\n" * 100] * 3
        self.assertTrue(all(len(b) < versions.GITLAB_MAX_CHARS for b in blocks))
        self.assertTrue(any("running total" in i for i in versions.check_page_limits(blocks)))

    def test_too_many_diagrams_on_one_page(self):
        self.assertTrue(any("per page" in i for i in versions.check_page_limits(["graph TD\n A-->B"] * 51)))


class LintToolTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, content: str) -> str:
        (self.tmp / "d.md").write_text(content)
        return "d.md"

    def test_target_flags_a_too_new_diagram_type(self):
        path = self._write("```mermaid\nblock-beta\n  columns 1\n  a\n```\n")
        result = run(MermaidLintTool().execute({"path": path, "target": "gitlab:17.2"},
                                               tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("block-beta needs Mermaid 10.8.0", result.content)
        self.assertIn("Mermaid 10.7.0", result.content)

    def test_the_same_file_passes_against_a_newer_gitlab(self):
        path = self._write("```mermaid\nblock-beta\n  columns 1\n  a\n```\n")
        result = run(MermaidLintTool().execute({"path": path, "target": "gitlab:19.0"},
                                               tool_ctx(self.tmp)))
        self.assertFalse(result.is_error, result.content)

    def test_without_a_target_only_syntax_is_checked(self):
        path = self._write("```mermaid\nblock-beta\n  columns 1\n  a\n```\n")
        result = run(MermaidLintTool().execute({"path": path}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error, result.content)

    def test_a_bad_target_is_reported_before_any_linting(self):
        path = self._write("```mermaid\ngraph TD\n  A --> B\n```\n")
        result = run(MermaidLintTool().execute({"path": path, "target": "gitlab:12.1"},
                                               tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("no bundled Mermaid version recorded", result.content)

    def test_gitlab_page_limits_apply_only_to_a_gitlab_target(self):
        big = "```mermaid\ngraph TD\n" + "  A --> B\n" * 400 + "```\n"   # ~4000 chars, over the 2000 cap
        gitlab = run(MermaidLintTool().execute({"path": self._write(big), "target": "gitlab:19.0"},
                                               tool_ctx(self.tmp)))
        plain = run(MermaidLintTool().execute({"path": self._write(big), "target": "mermaid:11.13.0"},
                                              tool_ctx(self.tmp)))
        self.assertTrue(gitlab.is_error)
        self.assertFalse(plain.is_error, plain.content)


if __name__ == "__main__":
    unittest.main()
