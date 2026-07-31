"""End-to-end test for --source last30days through the CLI.

Mocks `_fetch_last30days_candidates` at the recommender boundary so we
don't need a real last30days subprocess — verifies CLI → dispatcher →
recommender → output envelope pipeline is wired correctly.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from heated_topics_v3.openbiliclaw_integration import cli, recommender


def _build_one_user_users_file(tmp_path: Path) -> Path:
    up = tmp_path / "users.json"
    up.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "u_l30",
                        "display_name": "L30",
                        "interests": [
                            {"name": "AI 大模型", "category": "技术", "weight": 0.9}
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return up


def _fake_l30_articles() -> list[dict]:
    """Article dicts shaped like _fetch_last30days_candidates returns."""
    return [
        {
            "article_id": "weibo:l30_1",
            "title": "AI 微博热议",
            "url": "https://weibo.com/l30/1",
            "body_text": "微博正文",
            "summary": "微博正文摘要",
            "author": "weibo_user",
            "published_at": "",
            "tags": [],
            "heat": {"views": 5000, "likes": 100, "rank": 1},
            "platform": "weibo",
        },
        {
            "article_id": "zhihu:l30_1",
            "title": "AI 知乎讨论",
            "url": "https://zhihu.com/l30/1",
            "body_text": "知乎正文",
            "summary": "知乎摘要",
            "author": "zhihu_user",
            "published_at": "",
            "tags": [],
            "heat": {"voteups": 200, "num_comments": 30, "rank": 1},
            "platform": "zhihu",
        },
    ]


def test_end_to_end_last30days_source(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    users_file = _build_one_user_users_file(tmp_path)
    out = tmp_path / "recs.json"

    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    item = DiscoveredContent(
        title="AI 微博热议",
        content_id="weibo:l30_1",
        content_url="https://weibo.com/l30/1",
        source_platform="weibo",
        body_text="微博正文",
        content_type="note",
        view_count=5000,
        like_count=100,
        comment_count=0,
        source_rank=1,
    )
    fake_rec = Recommendation(
        content=item,
        expression="matches weibo interest",
        topic_label="AI",
        confidence=0.88,
        presented=False,
    )

    with (
        patch.object(
            recommender, "_fetch_last30days_candidates",
            return_value=_fake_l30_articles(),
        ),
        # When source=last30days, fetch_candidates (V3) should NOT be called.
        patch.object(
            recommender, "fetch_candidates",
            side_effect=AssertionError("V3 fetch_candidates must not run"),
        ),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=[fake_rec])
        mock_factory.return_value = eng
        code = cli.main([
            "--users", str(users_file),
            "--output", str(out),
            "--source", "last30days",
            "--last30days-cli-path", "/fake/last30days.py",
            "--last30days-query", "AI 大模型",
            "--max-parallel", "1",
            "--per-user-timeout", "30",
        ])

    assert code == 0, "CLI should exit 0 on success"
    assert out.exists(), "Output file should be written"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["users"][0]["user_id"] == "u_l30"
    rec = data["users"][0]["recommendations"][0]
    assert rec["title"] == "AI 微博热议"
    assert rec["reason"] == "matches weibo interest"
    assert rec["topic_label"] == "AI"
    assert rec["confidence"] == 0.88


def test_end_to_end_source_both_merges_and_dedupes(
    tmp_path: Path, monkeypatch
) -> None:
    """--source both invokes both fetchers; URL collisions drop last30days."""
    monkeypatch.setenv("OPENBILICLAW_LLM_API_KEY", "test-key")
    users_file = _build_one_user_users_file(tmp_path)
    out = tmp_path / "recs.json"

    shared_url = "https://example.com/collision"

    v3_article = {
        "article_id": "toutiao:v3_1",
        "title": "V3 头条",
        "url": shared_url,
        "body_text": "v3",
        "summary": "",
        "author": "",
        "published_at": "",
        "tags": [],
        "heat": {"rank": 1},
        "platform": "toutiao",
    }
    v3_extra = {
        "article_id": "toutiao:v3_2",
        "title": "V3 头条独有",
        "url": "https://example.com/v3-only",
        "body_text": "v3 only",
        "summary": "",
        "author": "",
        "published_at": "",
        "tags": [],
        "heat": {"rank": 2},
        "platform": "toutiao",
    }
    l30_collision = {
        "article_id": "weibo:l30_dup",
        "title": "L30 重复",
        "url": shared_url,  # collides with v3_1
        "body_text": "l30",
        "summary": "",
        "author": "",
        "published_at": "",
        "tags": [],
        "heat": {"rank": 1},
        "platform": "weibo",
    }
    l30_extra = {
        "article_id": "zhihu:l30_only",
        "title": "L30 独有",
        "url": "https://example.com/l30-only",
        "body_text": "l30 only",
        "summary": "",
        "author": "",
        "published_at": "",
        "tags": [],
        "heat": {"rank": 1},
        "platform": "zhihu",
    }

    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.recommendation.engine import Recommendation

    # Build as many recs as articles, but the test only cares about pipeline wiring.
    def _rec_for(article: dict) -> Recommendation:
        item = DiscoveredContent(
            title=article["title"],
            content_id=article["article_id"],
            content_url=article["url"],
            source_platform=article["platform"],
            body_text=article["body_text"],
            content_type="note",
            view_count=0, like_count=0, comment_count=0,
            source_rank=article["heat"].get("rank", 1),
        )
        return Recommendation(
            content=item, expression="r", topic_label="T",
            confidence=0.5, presented=False,
        )

    all_articles = [v3_article, v3_extra, l30_collision, l30_extra]
    fake_recs = [_rec_for(a) for a in all_articles]

    with (
        patch.object(recommender, "fetch_candidates",
                     return_value=[v3_article, v3_extra]),
        patch.object(recommender, "_fetch_last30days_candidates",
                     return_value=[l30_collision, l30_extra]),
        patch.object(recommender, "build_recommender") as mock_factory,
    ):
        eng = MagicMock()
        eng.serve_external_candidates = AsyncMock(return_value=fake_recs)
        mock_factory.return_value = eng
        code = cli.main([
            "--users", str(users_file),
            "--output", str(out),
            "--source", "both",
            "--last30days-cli-path", "/fake/last30days.py",
            "--last30days-query", "AI",
            "--max-parallel", "1",
            "--per-user-timeout", "30",
        ])

    assert code == 0
    # Test the merger semantics only: after URL dedup the pool is
    # [v3_1, v3_2, l30_only] (l30_dup dropped).
    captured_calls = []
    for c in eng.serve_external_candidates.call_args_list:
        captured_calls.append(c.kwargs.get("candidates") or c.args[1])
    assert len(captured_calls) == 1
    candidates = captured_calls[0]
    urls = [getattr(c, "content_url", None) or c.content_url for c in candidates]
    # v3 wins the collision; l30_dup is dropped
    assert shared_url in urls
    assert "https://example.com/v3-only" in urls
    assert "https://example.com/l30-only" in urls
    # 3 unique URLs passed in
    assert len(urls) == 3, f"expected 3 unique URLs after dedup, got {urls}"
