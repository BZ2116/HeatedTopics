import asyncio
import json
from pathlib import Path

from heated_topics_v3.openbiliclaw_integration import service
from heated_topics_v3.openbiliclaw_integration.service import HeatedTop


def test_recommend_user_writes_round_layout(tmp_path, monkeypatch):
    def fake_run(spec, **kwargs):
        return {
            "user_id": spec.user_id,
            "input": {"track_1": spec.track_1, "track_2": spec.track_2, "persona": spec.persona},
            "recommendations": [{"rank": 1, "title": "测试文章", "source": "toutiao", "body_text": "正文"}],
            "searched_articles": [], "summary": "",
        }
    monkeypatch.setattr(service.recommender, "run_one_user", fake_run)
    result = service.recommend_user(
        user_id="u_1", track_1="文化", track_2="非遗", persona="记录者",
        run_dir=tmp_path,
    )
    assert Path(result["round_dir"]).joinpath("input/input.json").exists()
    assert Path(result["round_dir"]).joinpath("outputs/recommended").exists()


def test_recommendation_service_interface_contract(tmp_path, monkeypatch):
    """The public async interface accepts one user and persists its round."""
    def fake_run(spec, **kwargs):
        return {
            "user_id": spec.user_id,
            "input": {"track_1": spec.track_1, "track_2": spec.track_2, "persona": spec.persona},
            "recommendations": [],
            "searched_articles": [],
            "summary": "",
        }

    monkeypatch.setattr(service.recommender, "run_one_user", fake_run)

    async def run():
        api = service.RecommendationService(max_concurrency=3)
        return await api.recommend_user(
            user_id="u_contract",
            track_1="文化生活",
            track_2="非遗与民俗",
            persona="记录传统文化生活智慧。",
            run_dir=tmp_path,
        )

    result = asyncio.run(run())
    assert result["user_id"] == "u_contract"
    assert Path(result["round_dir"]).joinpath("input/input.json").exists()
    assert Path(result["round_dir"]).joinpath("outputs/input.json").exists()


def test_recommend_user_auto_configures_last30days(tmp_path, monkeypatch):
    captured = {}

    def fake_run(spec, **kwargs):
        captured.update(kwargs)
        return {
            "user_id": spec.user_id,
            "input": {"track_1": spec.track_1, "track_2": spec.track_2, "persona": spec.persona},
            "recommendations": [], "searched_articles": [], "summary": "",
        }

    monkeypatch.setattr(service.recommender, "run_one_user", fake_run)
    monkeypatch.setattr(
        "heated_topics_v3.openbiliclaw_integration.cli._default_last30days_cli_path",
        lambda: Path("C:/tmp/last30days.py"),
    )
    service.recommend_user(
        user_id="u_l30", track_1="旅行", run_dir=tmp_path, source="both",
    )
    assert captured["last30days_config"]["cli_path"] == str(Path("C:/tmp/last30days.py"))


def test_service_serializes_same_user_and_caps_concurrency(monkeypatch, tmp_path):
    active = 0
    peak = 0

    async def fake_to_thread(fn, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"user_id": kwargs["user_id"]}

    monkeypatch.setattr(service.asyncio, "to_thread", fake_to_thread)
    svc = service.RecommendationService(max_concurrency=20)

    async def run():
        return await asyncio.gather(*[
            svc.recommend_user(user_id=f"u_{i}", run_dir=tmp_path)
            for i in range(8)
        ])

    asyncio.run(run())
    assert peak <= 3


def test_daily_hot_summary_reads_shared_cache(tmp_path):
    cache = tmp_path / "hot_cache" / "toutiao"
    cache.mkdir(parents=True)
    (cache / "items.json").write_text(json.dumps([{"title": "热榜"}]), encoding="utf-8")
    result = service.summarize_daily_hot(run_dir=tmp_path)
    assert result["count"] == 1
    assert (tmp_path / "daily_summary/summary.json").exists()


def test_heated_top_is_public_daily_entrypoint():
    assert callable(HeatedTop().run)
    assert service.__all__ == ["RecommendationService", "HeatedTop"]
