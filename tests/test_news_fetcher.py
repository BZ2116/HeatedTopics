"""Tests for make_sina_news_fetcher / make_netease_news_fetcher."""
import urllib.request
from pathlib import Path

from heated_topics_v3.baidu_retry import BaiduRetryPolicy
from heated_topics_v3.fetcher_factory import (
    BILIBILI_DESKTOP_UA,
    make_sina_news_fetcher,
    make_netease_news_fetcher,
)


def test_make_sina_news_fetcher_sends_zh_headers_and_returns_body(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=20):
        captured["url"] = req.full_url
        captured["ua"] = req.headers.get("User-agent")
        captured["lang"] = req.headers.get("Accept-language")
        captured["referer"] = req.headers.get("Referer")
        from io import BytesIO
        return _FakeResp(b"OK")

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body
        def read(self) -> bytes:
            return self._body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetcher = make_sina_news_fetcher()
    body = fetcher("https://top.news.sina.com.cn/ws/GetTopDataList.php", 15)
    assert body == "OK"
    assert captured["url"].startswith("https://top.news.sina.com.cn/")
    assert captured["ua"] == BILIBILI_DESKTOP_UA
    assert captured["lang"] == "zh-CN,zh;q=0.9"
    assert captured["referer"] == "https://news.sina.com.cn/"


def test_make_netease_news_fetcher_sends_zh_headers(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=20):
        captured["url"] = req.full_url
        captured["ua"] = req.headers.get("User-agent")
        captured["referer"] = req.headers.get("Referer")
        class R:
            def read(self_inner): return b"OK"
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetcher = make_netease_news_fetcher()
    body = fetcher("https://gw.m.163.com/nc-main/api/v1/hqc/no-repeat-hot-list", 15)
    assert body == "OK"
    assert captured["url"].startswith("https://gw.m.163.com/")
    assert captured["ua"] == BILIBILI_DESKTOP_UA
    assert captured["referer"] == "https://www.163.com/"
