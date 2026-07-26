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
from heated_topics_v3.pipeline import run_sina_news_pipeline
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