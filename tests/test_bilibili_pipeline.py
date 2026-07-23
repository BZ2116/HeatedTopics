import json
from pathlib import Path

from heated_topics_v3.pipeline import run_bilibili_pipeline

_NAV = json.dumps({"data": {"wbi_img": {
    "img_url": "https://i0.hdslb.com/bfs/wbi/" + "a" * 32 + ".png",
    "sub_url": "https://i0.hdslb.com/bfs/wbi/" + "b" * 32 + ".png",
}}})

_SEARCH = json.dumps({"code": 0, "data": {"result": [
    {"id": 123, "title": "AI Agent 指南", "desc": "d", "view": 1000, "like": 50,
     "reply": 8, "pub_time": 1700000000, "mid": 9, "author": "作者A"},
]}}, ensure_ascii=False)

_ARTICLE = (
    '<html><script>window.__INITIAL_STATE__='
    '{"readInfo":{"title":"AI Agent 指南","author":{"name":"作者A"},'
    '"stats":{"view":1000,"like":50,"coin":5,"favorite":20,"reply":8},'
    '"content":"<p>这是关于 AI Agent 的正文。</p>"}};</script></html>'
)


def _profile(tmp_path: Path) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "tech_ai_creator", "display_name": "Tech AI",
        "domains": ["tech"], "audience": ["devs"], "content_modes": ["analysis"],
        "preferred_platforms": ["bilibili"], "core_keywords": ["AI Agent"],
        "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    return p


def _fetcher(url: str, timeout_seconds: int) -> str:
    if "web-interface/nav" in url:
        return _NAV
    if "wbi/search/type" in url:
        return _SEARCH
    if "/read/cv" in url:
        return _ARTICLE
    raise AssertionError(f"unexpected url {url}")


def test_run_bilibili_pipeline_writes_outputs(tmp_path: Path):
    outputs = run_bilibili_pipeline(
        profile_path=_profile(tmp_path),
        output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00",
        cache_root=tmp_path / "cache",
        top_n=10,
        fetcher=_fetcher,
    )
    assert set(outputs) == {"article_texts", "hot_items", "report"}
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert len(hot_items) == 1
    assert hot_items[0]["item"]["title"] == "AI Agent 指南"
    assert hot_items[0]["detail"]["fetch_status"] == "success"
    report = outputs["report"].read_text(encoding="utf-8")
    assert "# B站专栏日报" in report


def test_bilibili_no_match_is_transparent(tmp_path: Path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "x", "display_name": "X", "domains": ["cooking"],
        "audience": ["a"], "content_modes": ["m"], "preferred_platforms": ["bilibili"],
        "core_keywords": ["红烧肉"], "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    outputs = run_bilibili_pipeline(
        profile_path=p, output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=_fetcher,
    )
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []


def test_bilibili_second_run_hits_cache(tmp_path: Path):
    calls = {"n": 0}

    def counting(url: str, timeout_seconds: int) -> str:
        calls["n"] += 1
        return _fetcher(url, timeout_seconds)

    kwargs = dict(
        profile_path=_profile(tmp_path), output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=counting,
    )
    run_bilibili_pipeline(**kwargs)
    first = calls["n"]
    run_bilibili_pipeline(**kwargs)
    # 第二次 search/article 命中缓存；nav 每次都会拉（不缓存），故新增调用应远少于首轮
    assert calls["n"] - first < first


def test_bilibili_skips_when_keywords_empty(tmp_path: Path):
    """对齐 Toutiao：B 站无 board 兜底，core_keywords 为空 → 跳过整个 pipeline。"""
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "profile_id": "x", "display_name": "X", "domains": ["tech"],
        "audience": ["a"], "content_modes": ["m"], "preferred_platforms": ["bilibili"],
        "core_keywords": [], "entity_keywords": [], "excluded_keywords": [],
    }), encoding="utf-8")
    calls = {"n": 0}

    def counting(url: str, timeout_seconds: int) -> str:
        calls["n"] += 1
        return _fetcher(url, timeout_seconds)

    outputs = run_bilibili_pipeline(
        profile_path=p, output_root=tmp_path / "outputs",
        fetched_at="2026-07-22T20:00:00+08:00", cache_root=tmp_path / "cache",
        top_n=10, fetcher=counting,
    )
    # 无 fetch 调用（nav / search / article 全跳过）
    assert calls["n"] == 0
    hot_items = json.loads(outputs["hot_items"].read_text(encoding="utf-8"))
    assert hot_items == []
    report = outputs["report"].read_text(encoding="utf-8")
    assert "# B站专栏日报" in report
    assert "本次未抓到任何条目" in report