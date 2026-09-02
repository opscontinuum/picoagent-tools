import asyncio
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
from test_runner_tools import RunTestsTool, detect_command, extract_summary


def run(coro):
    return asyncio.run(coro)


class DetectCommandTests(unittest.TestCase):
    """Pure-function tests: no subprocess spawned, no external toolchain required."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_nothing_recognized_returns_none(self):
        self.assertIsNone(detect_command(self.tmp))

    def test_pytest_ini_wins(self):
        (self.tmp / "pytest.ini").write_text("[pytest]\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_pyproject_with_pytest_section(self):
        (self.tmp / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-v'\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_pyproject_without_pytest_section_does_not_match(self):
        (self.tmp / "pyproject.toml").write_text("[tool.black]\nline-length = 100\n")
        self.assertIsNone(detect_command(self.tmp))

    def test_setup_cfg_with_pytest_section(self):
        (self.tmp / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_setup_cfg_without_pytest_section_does_not_match(self):
        (self.tmp / "setup.cfg").write_text("[metadata]\nname = foo\n")
        self.assertIsNone(detect_command(self.tmp))

    def test_tests_dir_alone_means_unittest(self):
        (self.tmp / "tests").mkdir()
        self.assertEqual(detect_command(self.tmp), "python3 -m unittest discover -s tests -v")

    def test_tests_dir_plus_pytest_pyproject_means_pytest(self):
        (self.tmp / "tests").mkdir()
        (self.tmp / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_tests_dir_plus_pytest_ini_means_pytest(self):
        (self.tmp / "tests").mkdir()
        (self.tmp / "pytest.ini").write_text("[pytest]\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_package_json_means_npm(self):
        (self.tmp / "package.json").write_text("{}")
        self.assertEqual(detect_command(self.tmp), "npm test")

    def test_cargo_toml_means_cargo(self):
        (self.tmp / "Cargo.toml").write_text("[package]\nname = \"foo\"\n")
        self.assertEqual(detect_command(self.tmp), "cargo test")

    def test_go_mod_means_go(self):
        (self.tmp / "go.mod").write_text("module example.com/foo\n")
        self.assertEqual(detect_command(self.tmp), "go test ./...")

    def test_precedence_pytest_over_tests_dir_over_package_json(self):
        (self.tmp / "tests").mkdir()
        (self.tmp / "package.json").write_text("{}")
        (self.tmp / "pytest.ini").write_text("[pytest]\n")
        self.assertEqual(detect_command(self.tmp), "python3 -m pytest -q")

    def test_precedence_tests_dir_over_package_json(self):
        (self.tmp / "tests").mkdir()
        (self.tmp / "package.json").write_text("{}")
        self.assertEqual(detect_command(self.tmp), "python3 -m unittest discover -s tests -v")

    def test_precedence_package_json_over_cargo(self):
        (self.tmp / "package.json").write_text("{}")
        (self.tmp / "Cargo.toml").write_text("[package]\n")
        self.assertEqual(detect_command(self.tmp), "npm test")

    def test_precedence_cargo_over_go(self):
        (self.tmp / "Cargo.toml").write_text("[package]\n")
        (self.tmp / "go.mod").write_text("module example.com/foo\n")
        self.assertEqual(detect_command(self.tmp), "cargo test")


class ExtractSummaryTests(unittest.TestCase):
    def test_unittest_ok(self):
        output = (
            "test_foo (tests.test_x) ... ok\n\n"
            "----------------------------------------------------------------------\n"
            "Ran 1 test in 0.001s\n\nOK\n"
        )
        self.assertEqual(extract_summary(output, "unittest"), "Ran 1 test in 0.001s - OK")

    def test_unittest_failed(self):
        output = "Ran 3 tests in 0.010s\n\nFAILED (failures=1)\n"
        self.assertEqual(extract_summary(output, "unittest"), "Ran 3 tests in 0.010s - FAILED (failures=1)")

    def test_pytest_passed(self):
        output = "===== 4 passed in 0.12s ====="
        self.assertEqual(extract_summary(output, "pytest"), "4 passed")

    def test_pytest_mixed(self):
        output = "===== 2 failed, 3 passed, 1 error in 0.12s ====="
        self.assertEqual(extract_summary(output, "pytest"), "3 passed, 2 failed, 1 error")

    def test_npm_passing_failing(self):
        output = "  10 passing (50ms)\n  2 failing\n"
        self.assertEqual(extract_summary(output, "npm"), "10 passing, 2 failing")

    def test_cargo_ok(self):
        output = (
            "running 3 tests\n"
            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
        )
        self.assertEqual(extract_summary(output, "cargo"),
                         "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out")

    def test_go_ok_lines(self):
        output = "ok  \texample.com/foo\t0.005s\nFAIL\texample.com/bar\t0.003s\n"
        self.assertEqual(extract_summary(output, "go"),
                         "ok  \texample.com/foo\t0.005s; FAIL\texample.com/bar\t0.003s")

    def test_no_match_returns_none(self):
        self.assertIsNone(extract_summary("nothing recognizable here", "unittest"))

    def test_custom_tries_every_extractor(self):
        output = "===== 7 passed in 0.02s ====="
        self.assertEqual(extract_summary(output, "custom"), "7 passed")


class RunTestsIntegrationTests(unittest.TestCase):
    """End-to-end: these actually spawn a real subprocess."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_no_marker_files_is_a_clear_error(self):
        result = run(RunTestsTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("No test command could be detected", result.content)
        self.assertIn("tests/ directory", result.content)

    def test_detects_and_runs_a_real_passing_unittest_suite(self):
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_x.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_it_passes(self):\n"
            "        self.assertEqual(1 + 1, 2)\n"
        )
        result = run(RunTestsTool().execute({}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.details["detected"], "unittest")
        self.assertEqual(result.details["exit_code"], 0)
        self.assertIn("python3 -m unittest discover -s tests -v", result.details["command"])
        self.assertIn("OK", result.content)
        self.assertIn("Ran 1 test", result.content)

    def test_detects_and_runs_a_real_failing_unittest_suite(self):
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_x.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_it_fails(self):\n"
            "        self.assertEqual(1 + 1, 3)\n"
        )
        result = run(RunTestsTool().execute({}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertNotEqual(result.details["exit_code"], 0)
        self.assertIn("FAILED", result.content)

    def test_explicit_command_override_skips_detection(self):
        result = run(RunTestsTool().execute(
            {"command": "python3 -c \"print('hello'); import sys; sys.exit(0)\""}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.details["detected"], "custom")
        self.assertIn("hello", result.content)

    def test_explicit_failing_command_is_reported_as_error(self):
        result = run(RunTestsTool().execute(
            {"command": "python3 -c \"import sys; sys.exit(1)\""}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertEqual(result.details["exit_code"], 1)

    def test_timeout_is_reported_clearly_and_does_not_hang(self):
        result = run(RunTestsTool().execute({"command": "sleep 5", "timeout": 1}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("timed out", result.content)


if __name__ == "__main__":
    unittest.main()
