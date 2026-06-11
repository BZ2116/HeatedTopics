import unittest
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.error import URLError

from src.fetch_hot_lists import FetchIssue, daily_hot_api_bases, fetch_json, fetch_platform


class FetchHotListsTests(unittest.TestCase):
    def test_fetch_json_can_read_localhost_without_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"data": [{"title": "本地热点"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = fetch_json(f"http://127.0.0.1:{server.server_port}/weibo")
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(payload["data"][0]["title"], "本地热点")

    def test_daily_hot_api_base_can_be_configured_from_environment(self):
        with patch.dict("os.environ", {"DAILY_HOT_API_BASE": "http://localhost:6688/"}, clear=True):
            self.assertEqual(daily_hot_api_bases(), ["http://localhost:6688"])

    def test_daily_hot_api_bases_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {"DAILY_HOT_API_BASES": "http://localhost:6688, https://api.example.com/"},
            clear=True,
        ):
            self.assertEqual(daily_hot_api_bases(), ["http://localhost:6688", "https://api.example.com"])

    def test_fetch_platform_tries_next_base_after_network_error(self):
        calls = []

        def fake_fetcher(url):
            calls.append(url)
            if url == "https://broken.example/weibo":
                raise URLError("dns failed")
            return {
                "data": [
                    {
                        "title": "AI 产品发布",
                        "hot": "1000",
                        "url": "https://example.com/ai",
                    }
                ]
            }

        issues: list[FetchIssue] = []
        records = fetch_platform(
            "weibo",
            limit=3,
            api_bases=["https://broken.example", "http://localhost:6688"],
            fetcher=fake_fetcher,
            issues=issues,
        )

        self.assertEqual(calls, ["https://broken.example/weibo", "http://localhost:6688/weibo"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "AI 产品发布")
        self.assertEqual(records[0].platform, "weibo")
        self.assertEqual(len(issues), 1)
        self.assertIn("dns failed", issues[0].error)

    def test_fetch_platform_records_empty_payload_as_issue(self):
        issues: list[FetchIssue] = []

        records = fetch_platform(
            "weibo",
            api_bases=["http://localhost:6688"],
            fetcher=lambda url: {"data": []},
            issues=issues,
        )

        self.assertEqual(records, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].platform, "weibo")
        self.assertEqual(issues[0].url, "http://localhost:6688/weibo")
        self.assertIn("empty data", issues[0].error)


if __name__ == "__main__":
    unittest.main()
