import asyncio
import tempfile
import unittest
from pathlib import Path

from helpers import tool_ctx
from structured_data_tools import StructuredDataTool


def run(coro):
    return asyncio.run(coro)


class StructuredDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content)
        return path

    # ---------------------------------------------------------------- JSON

    def test_valid_json_round_trip_no_query(self):
        self._write("data.json", '{"name": "widget", "count": 3}')
        result = run(StructuredDataTool().execute({"path": "data.json"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn('"name": "widget"', result.content)
        self.assertIn('"count": 3', result.content)

    def test_valid_json_query_into_nested_dict(self):
        self._write("data.json", '{"service": {"web": {"port": 8080}}}')
        result = run(StructuredDataTool().execute(
            {"path": "data.json", "query": "service.web.port"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.content.strip(), "8080")

    def test_valid_json_query_into_list_index(self):
        self._write("data.json", '{"services": {"web": {"ports": [80, 443, 8080]}}}')
        result = run(StructuredDataTool().execute(
            {"path": "data.json", "query": "services.web.ports[0]"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.content.strip(), "80")

    def test_query_missing_key_gives_clear_error_naming_segment(self):
        self._write("data.json", '{"service": {"web": {"port": 8080}}}')
        result = run(StructuredDataTool().execute(
            {"path": "data.json", "query": "service.database.port"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn(".database", result.content)
        self.assertIn("web", result.content)  # available keys mentioned

    def test_query_index_out_of_range(self):
        self._write("data.json", '{"ports": [80, 443]}')
        result = run(StructuredDataTool().execute(
            {"path": "data.json", "query": "ports[5]"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("[5]", result.content)
        self.assertIn("length 2", result.content)

    def test_query_indexing_into_non_list(self):
        self._write("data.json", '{"service": {"web": {"port": 8080}}}')
        result = run(StructuredDataTool().execute(
            {"path": "data.json", "query": "service.web.port[0]"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("[0]", result.content)
        self.assertIn("expects a list", result.content)

    def test_malformed_json_is_an_error_with_useful_detail(self):
        self._write("bad.json", '{"name": "widget", }')
        result = run(StructuredDataTool().execute({"path": "bad.json"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("line", result.content.lower())
        self.assertIn("column", result.content.lower())

    # ---------------------------------------------------------------- TOML

    def test_valid_toml_round_trip_no_query(self):
        self._write("data.toml", 'name = "widget"\ncount = 3\n')
        result = run(StructuredDataTool().execute({"path": "data.toml"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn('"name": "widget"', result.content)

    def test_valid_toml_query(self):
        self._write("data.toml", "[service.web]\nport = 8080\n")
        result = run(StructuredDataTool().execute(
            {"path": "data.toml", "query": "service.web.port"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertEqual(result.content.strip(), "8080")

    def test_toml_datetime_is_serialised_via_default_str(self):
        self._write("data.toml", "created = 2024-01-15T10:00:00Z\n")
        result = run(StructuredDataTool().execute({"path": "data.toml"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn("2024-01-15", result.content)

    def test_malformed_toml_is_an_error(self):
        self._write("bad.toml", "name = \n")
        result = run(StructuredDataTool().execute({"path": "bad.toml"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)

    # ---------------------------------------------------------------- YAML

    def test_yaml_returns_raw_text_unparsed_not_an_error(self):
        raw = "name: widget\ncount: 3\n"
        self._write("data.yaml", raw)
        result = run(StructuredDataTool().execute({"path": "data.yaml"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn(raw.strip(), result.content)
        self.assertIn("unparsed", result.content.lower())
        self.assertIn("YAML", result.content)

    def test_yml_extension_also_returns_raw_text(self):
        raw = "a: 1\n"
        self._write("data.yml", raw)
        result = run(StructuredDataTool().execute({"path": "data.yml"}, tool_ctx(self.tmp)))
        self.assertFalse(result.is_error)
        self.assertIn(raw.strip(), result.content)

    # ---------------------------------------------------------------- misc

    def test_unsupported_extension_is_an_error(self):
        self._write("data.txt", "hello\n")
        result = run(StructuredDataTool().execute({"path": "data.txt"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("unsupported extension", result.content.lower())

    def test_nonexistent_file_is_an_error(self):
        result = run(StructuredDataTool().execute({"path": "nope.json"}, tool_ctx(self.tmp)))
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.content.lower())


if __name__ == "__main__":
    unittest.main()
