import tempfile
import unittest
from pathlib import Path

from src.core_pipeline.session_gate import check_required_sessions, summarize_session_status


class SessionGateTests(unittest.TestCase):
    def test_missing_weibo_and_xiaohongshu_sessions_require_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = check_required_sessions(Path(tmp))

            self.assertEqual(result["weibo"], "login_required")
            self.assertEqual(result["xiaohongshu"], "login_required")

    def test_existing_non_empty_state_files_are_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "weibo.json").write_text('{"cookies":[{"name":"a"}]}', encoding="utf-8")
            (root / "xiaohongshu.json").write_text('{"cookies":[{"name":"b"}]}', encoding="utf-8")

            result = check_required_sessions(root)

            self.assertEqual(result["weibo"], "ok")
            self.assertEqual(result["xiaohongshu"], "ok")

    def test_summarize_session_status_lists_missing_platforms(self):
        summary = summarize_session_status({"weibo": "login_required", "xiaohongshu": "ok"})

        assert summary["ok"] == ["xiaohongshu"]
        assert summary["missing"] == ["weibo"]
        assert "uv run python -m src.browser.session_manager login weibo" in summary["login_commands"]

    def test_summarize_session_status_handles_all_ok(self):
        summary = summarize_session_status({"weibo": "ok", "xiaohongshu": "ok"})

        assert summary["ok"] == ["weibo", "xiaohongshu"]
        assert summary["missing"] == []
        assert summary["login_commands"] == []

    def test_summarize_session_status_handles_empty(self):
        summary = summarize_session_status({})

        assert summary["ok"] == []
        assert summary["missing"] == []
        assert summary["login_commands"] == []


if __name__ == "__main__":
    unittest.main()
