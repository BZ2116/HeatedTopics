"""v2 pipeline tests for sina_news (and later netease_news in Task 5).

Confirms the v2 architectural alignment with toutiao:
  - hard cap of 5 keywords
  - default top_n = 10
  - output_root/users/{profile_id}/{date}/run_{ts}/ layout
  - Path A dedup wins over Path B
  - 404 single-article regression preserved
"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from heated_topics_v3.hot_board_cache import utc8_today
from heated_topics_v3.pipeline import run_netease_news_pipeline, run_sina_news_pipeline
from heated_topics_v3.providers.netease_news import NETEASE_HOT_URL, NETEASE_SEARCH_URL
from heated_topics_v3.providers.sina_news import SINA_HOT_URL, SINA_SEARCH_URL


SINA_HOT_RAW = """var data = {"data": [
    {"title": "AI 大爆发", "url": "https://news.sina.com.cn/c/ai.shtml", "top_num": "9,999", "ext4": "ai123",
     "media": "新浪", "cat_name": "科技", "create_date": "2026-07-25", "create_time": "10:00:00"},
    {"title": "汽车补贴新政", "url": "https://news.sina.com.cn/c/car.shtml", "top_num": "5,000", "ext4": "car456",
     "media": "新浪", "cat_name": "财经", "create_date": "2026-07-25", "create_time": "09:00:00"}
]};"""

SINA_SEARCH_RAW = json.dumps({
    "code": 0, "message": "ok",
    "data": {"list": [
        {"title": "AI 大爆发", "url": "https://news.sina.com.cn/c/ai.shtml", "dataid": "comos:ai123"},
    ]},
})

SINA_ARTICLE_HTML = "<html><body><div class='article-content-left'><p>这是真实正文第一段。</p><p>第二段。</p></div></body></html>"

# Two-result search payload used by the live-article 404 regression test.
SINA_SEARCH_TWO_RESULTS = json.dumps({
    "code": 0, "message": "ok",
    "data": {"list": [
        {"title": "AI 大爆发", "url": "https://news.sina.com.cn/c/ai999.shtml", "dataid": "comos:ai999"},
        {"title": "AI 大爆发 第二篇", "url": "https://news.sina.com.cn/c/ai888.shtml", "dataid": "comos:ai888"},
    ]},
})

SINA_ARTICLE_HTML_888 = "<html><body><div class='article-content-left'><p>这是真实正文ai888第一段。</p><p>第二段。</p></div></body></html>"


def _make_sina_fetcher():
    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url == SINA_HOT_URL:
            return SINA_HOT_RAW
        if url.startswith(SINA_SEARCH_URL):
            return SINA_SEARCH_RAW
        if "news.sina.com.cn" in url:
            return SINA_ARTICLE_HTML
        raise AssertionError(f"unexpected sina URL: {url}")
    return fetcher


def _sina_profile(tmp_path: Path, *, profile_id: str = "sina_v2_test",
                  core_keywords=("AI",)) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "profile_id": profile_id, "display_name": "v2 test",
        "domains": [], "audience": [], "content_modes": [],
        "preferred_platforms": ["sina_news"], "core_keywords": list(core_keywords),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_sina_v2_truncates_core_keywords_to_5(tmp_path: Path):
    """Hard cap: 7 core_keywords → fetcher sees only 5 search calls."""
    seen_keywords: list[str] = []
    profile = _sina_profile(tmp_path, core_keywords=("AI", "汽车", "体育", "娱乐", "财经", "教育", "国际"))

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url.startswith(SINA_SEARCH_URL):
            qs = parse_qs(urlparse(url).query)
            seen_keywords.append(qs.get("q", ["?"])[0])
            return SINA_SEARCH_RAW
        if url == SINA_HOT_URL:
            return SINA_HOT_RAW
        if "news.sina.com.cn" in url:
            return SINA_ARTICLE_HTML
        raise AssertionError(f"unexpected sina URL: {url}")

    run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
    )
    assert len(seen_keywords) == 5, (
        f"sina v2 must cap at 5 keywords, fetcher saw {len(seen_keywords)}: {seen_keywords}"
    )
    assert seen_keywords == ["AI", "汽车", "体育", "娱乐", "财经"]


def test_sina_v2_default_top_n_is_10(tmp_path: Path):
    """top_n default is 10, not 30. Confirm via the returned result."""
    profile = _sina_profile(tmp_path)
    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_sina_fetcher(),
    )
    assert result.top_n == 10, (
        f"default top_n must be 10, got {result.top_n}"
    )
    assert result.kept_total <= 10


def test_sina_v2_uses_users_profile_id_date_layout(tmp_path: Path):
    """Output path: output_root/users/{profile_id}/{date}/run_{ts}/"""
    profile = _sina_profile(tmp_path, profile_id="sina_layout")
    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_sina_fetcher(),
    )
    expected_root = tmp_path / "out" / "users" / "sina_layout" / utc8_today()
    assert str(result.run_dir).startswith(str(expected_root)), (
        f"run_dir must live under {expected_root}, got {result.run_dir}"
    )
    assert "run_" in result.run_dir.name
    assert (result.run_dir / "report.md").exists()
    assert (result.run_dir / "focused.json").exists()
    assert (result.run_dir / "raw" / "article_info.json").exists()
    # raw/search_*.json: only 1 search keyword ("AI") ran, so 1 file.
    search_files = list((result.run_dir / "raw").glob("search_*.json"))
    assert len(search_files) == 1, (
        f"expected 1 search_*.json for 1 keyword, got {len(search_files)}: {search_files}"
    )


def test_sina_v2_dedups_board_and_search_overlap(tmp_path: Path):
    """Path A board item with ext4=ai123 wins over Path B search dataid=comos:ai123."""
    profile = _sina_profile(tmp_path, profile_id="sina_dedup")
    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_sina_fetcher(),
    )
    focused = json.loads((result.run_dir / "focused.json").read_text(encoding="utf-8"))
    # Both board and search hit ``https://news.sina.com.cn/c/ai.shtml``;
    # the dedup key (bare id ``ai123``) collapses them into a single row
    # whose ``source_path`` carries ``A`` (board wins).
    ai_rows = [r for r in focused["results"] if r["url"].endswith("/c/ai.shtml")]
    assert len(ai_rows) == 1, (
        f"expected 1 deduped ai.shtml row, got {len(ai_rows)}: "
        f"{[r['url'] for r in ai_rows]}"
    )
    kept = ai_rows[0]
    # Path A wins: source_path contains "A" (and possibly "B" merged in).
    assert "A" in kept["source_path"], (
        f"Path A board must win dedup, got source_path={kept['source_path']}"
    )
    assert kept["hot_value"] == 9999  # top_num from board


def test_sina_v2_survives_single_article_404(tmp_path: Path):
    """Regression: single article 404 must NOT abort the run."""
    profile = _sina_profile(tmp_path, profile_id="sina_404")

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url == SINA_HOT_URL:
            return """var data = {"data": []};"""
        if url.startswith(SINA_SEARCH_URL):
            return SINA_SEARCH_TWO_RESULTS
        if "ai999" in url:
            raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)
        if "ai888" in url:
            return SINA_ARTICLE_HTML_888
        raise AssertionError(f"unexpected sina URL: {url}")

    result = run_sina_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
    )
    assert (result.run_dir / "report.md").exists()
    assert (result.run_dir / "focused.json").exists()
    articles_dir = result.run_dir / "articles"
    txt_files = list(articles_dir.glob("*.txt"))
    assert any("ai888" in p.read_text(encoding="utf-8") for p in txt_files), (
        f"ai888 body must appear in some articles/*.txt, got: {[p.name for p in txt_files]}"
    )


NETEASE_HOT_RAW = json.dumps({
    "code": 0,
    "data": {"items": [
        {"type": "doc", "contentId": "DOC123", "title": "AI 改变生活",
         "url": "https://www.163.com/dy/article/DOC123.html",
         "hotValue": 10000, "click": 5000, "commentCount": 100,
         "votecount": 50, "threadVote": 5, "source": "网易",
         "category": "科技", "ptime": "2026-07-25 10:00:00"}
    ]},
})

NETEASE_SEARCH_RAW = json.dumps({
    "code": 0,
    "data": {"result": [
        {"docid": "DOC123", "title": "AI 改变生活",
         "url": "https://www.163.com/dy/article/DOC123.html",
         "source": "网易", "replyCount": 100, "vote": 50, "ptime": "2026-07-25 10:00:00"}
    ]},
})

NETEASE_SEARCH_TWO_RESULTS = json.dumps({
    "code": 0,
    "data": {"result": [
        {"docid": "DOC123", "title": "AI 改变生活",
         "url": "https://www.163.com/dy/article/DOC123.html",
         "source": "网易", "replyCount": 100, "vote": 50, "ptime": "2026-07-25 10:00:00"},
        {"docid": "DOC456", "title": "AI 改变生活 第二篇",
         "url": "https://www.163.com/dy/article/DOC456.html",
         "source": "网易", "replyCount": 80, "vote": 40, "ptime": "2026-07-25 11:00:00"},
    ]},
})

NETEASE_ARTICLE_HTML = "<html><body><div class='post_body'><p>网易真实正文第一段。</p><p>第二段。</p></div></body></html>"
NETEASE_ARTICLE_HTML_456 = "<html><body><div class='post_body'><p>网易真实正文DOC456第一段。</p><p>第二段。</p></div></body></html>"


def _make_netease_fetcher():
    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url == NETEASE_HOT_URL:
            return NETEASE_HOT_RAW
        if url.startswith(NETEASE_SEARCH_URL):
            return NETEASE_SEARCH_RAW
        if "163.com/dy/article" in url:
            return NETEASE_ARTICLE_HTML
        raise AssertionError(f"unexpected netease URL: {url}")
    return fetcher


def _netease_profile(tmp_path: Path, *, profile_id: str = "netease_v2_test",
                     core_keywords=("AI",)) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "profile_id": profile_id, "display_name": "v2 test",
        "domains": [], "audience": [], "content_modes": [],
        "preferred_platforms": ["netease_news"], "core_keywords": list(core_keywords),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_netease_v2_truncates_core_keywords_to_5(tmp_path: Path):
    seen_keywords: list[str] = []
    profile = _netease_profile(tmp_path, core_keywords=("AI", "汽车", "体育", "娱乐", "财经", "教育", "国际"))

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url.startswith(NETEASE_SEARCH_URL):
            qs = parse_qs(urlparse(url).query)
            seen_keywords.append(qs.get("query", ["?"])[0])
            return NETEASE_SEARCH_RAW
        if url == NETEASE_HOT_URL:
            return NETEASE_HOT_RAW
        if "163.com/dy/article" in url:
            return NETEASE_ARTICLE_HTML
        raise AssertionError(f"unexpected netease URL: {url}")

    run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
    )
    assert len(seen_keywords) == 5, (
        f"netease v2 must cap at 5 keywords, fetcher saw {len(seen_keywords)}: {seen_keywords}"
    )
    assert seen_keywords == ["AI", "汽车", "体育", "娱乐", "财经"]


def test_netease_v2_default_top_n_is_10(tmp_path: Path):
    profile = _netease_profile(tmp_path)
    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_netease_fetcher(),
    )
    assert result.top_n == 10
    assert result.kept_total <= 10


def test_netease_v2_uses_users_profile_id_date_layout(tmp_path: Path):
    profile = _netease_profile(tmp_path, profile_id="netease_layout")
    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_netease_fetcher(),
    )
    expected_root = tmp_path / "out" / "users" / "netease_layout" / utc8_today()
    assert str(result.run_dir).startswith(str(expected_root))
    assert "run_" in result.run_dir.name
    assert (result.run_dir / "report.md").exists()
    assert (result.run_dir / "focused.json").exists()
    assert (result.run_dir / "raw" / "article_info.json").exists()
    search_files = list((result.run_dir / "raw").glob("search_*.json"))
    assert len(search_files) == 1, (
        f"expected 1 search_*.json for 1 keyword, got {len(search_files)}: {search_files}"
    )


def test_netease_v2_dedups_board_and_search_overlap(tmp_path: Path):
    profile = _netease_profile(tmp_path, profile_id="netease_dedup")
    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", offline=False,
        fetcher=_make_netease_fetcher(),
    )
    focused = json.loads((result.run_dir / "focused.json").read_text(encoding="utf-8"))
    doc123_rows = [r for r in focused["results"] if "DOC123" in r["url"]]
    assert len(doc123_rows) == 1, (
        f"expected 1 deduped DOC123 row, got {len(doc123_rows)}: "
        f"{[r['url'] for r in doc123_rows]}"
    )
    kept = doc123_rows[0]
    assert "A" in kept["source_path"], (
        f"Path A board must win dedup, got source_path={kept['source_path']}"
    )
    assert kept["hot_value"] == 10000


def test_netease_v2_survives_single_article_404(tmp_path: Path):
    profile = _netease_profile(tmp_path, profile_id="netease_404")

    def fetcher(url: str, timeout_seconds: int = 20) -> str:
        if url == NETEASE_HOT_URL:
            return json.dumps({"code": 0, "data": {"items": []}})
        if url.startswith(NETEASE_SEARCH_URL):
            return NETEASE_SEARCH_TWO_RESULTS
        if "DOC123" in url:
            raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)
        if "DOC456" in url:
            return NETEASE_ARTICLE_HTML_456
        raise AssertionError(f"unexpected netease URL: {url}")

    result = run_netease_news_pipeline(
        profile_path=profile, output_root=tmp_path / "out",
        fetched_at="2026-07-25T00:00:00+08:00",
        cache_root=tmp_path / "cache", top_n=10, offline=False, fetcher=fetcher,
    )
    assert (result.run_dir / "report.md").exists()
    assert (result.run_dir / "focused.json").exists()
    articles_dir = result.run_dir / "articles"
    txt_files = list(articles_dir.glob("*.txt"))
    assert any("DOC456" in p.read_text(encoding="utf-8") for p in txt_files), (
        f"DOC456 body must appear in some articles/*.txt, got: {[p.name for p in txt_files]}"
    )


# --- CLI integration tests (Task 6): --top-n default 10 + v2 print format ---
import subprocess
import sys


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "heated_topics_v3.cli", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60,
    )


def _cli_cwd() -> Path:
    # Project root = two parents up from this test file (tests/ -> project root).
    return Path(__file__).resolve().parent.parent


def _top_n_line(help_text: str) -> str:
    # argparse renders "--top-n TOP_N" possibly wrapped; grab the line owning it.
    for line in help_text.splitlines():
        if "--top-n" in line:
            return line
    return ""


def test_sina_news_help_shows_top_n_default_10():
    result = _run_cli(["sina-news", "--help"], _cli_cwd())
    assert result.returncode == 0, f"stderr: {result.stderr}"
    help_text = result.stdout
    assert "--top-n" in help_text
    assert "default: 10" in help_text, (
        f"expected 'default: 10' in help, got:\n{help_text}"
    )
    assert "default: 30" not in help_text, "default must not be 30"


def test_netease_news_help_shows_top_n_default_10():
    result = _run_cli(["netease-news", "--help"], _cli_cwd())
    assert result.returncode == 0, f"stderr: {result.stderr}"
    help_text = result.stdout
    assert "--top-n" in help_text
    assert "default: 10" in help_text, (
        f"expected 'default: 10' in help, got:\n{help_text}"
    )
    assert "default: 30" not in help_text, "default must not be 30"
