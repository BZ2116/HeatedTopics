import tempfile
import unittest
from pathlib import Path

from src.core_pipeline.json_store import read_json_list, write_json_list, write_jsonl


class JsonStoreTests(unittest.TestCase):
    def test_write_json_list_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "records.json"

            write_json_list(path, [{"id": "one"}])

            self.assertEqual(read_json_list(path), [{"id": "one"}])

    def test_read_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"

            self.assertEqual(read_json_list(path), [])

    def test_write_jsonl_writes_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "records.jsonl"

            write_jsonl(path, [{"id": "one"}, {"id": "two"}])

            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), ['{"id": "one"}', '{"id": "two"}'])


if __name__ == "__main__":
    unittest.main()
