import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from heated_topics_v3 import cli


V2_PROFILE = {
    "user_id": "zhao_001",
    "level1": "科技AI",
    "level2": "AI工具应用",
    "personal": {
        "role": "AI工具体验官",
        "subject": "AI工具",
        "scenarios": ["写作", "学习"],
        "value": "真实建议",
    },
    "core_keywords": ["AI工具"],
}


def _write_v2_profile(tmp_path: Path, name: str = "zhao_001.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(V2_PROFILE, ensure_ascii=False), encoding="utf-8")
    return path


def _v2_result() -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=Path("outputs/users/zhao_001/2026-07-13/run_120000"),
        report_path=Path("outputs/users/zhao_001/2026-07-13/run_120000/report.md"),
        focused_path=Path("outputs/users/zhao_001/2026-07-13/run_120000/focused.json"),
        candidates_total=12,
        kept_total=7,
        paths={"A": 2, "B": 10},
        hot_board_source="cache",
        keyword_source="fresh",
    )


def test_toutiao_profile_v2_dispatches_runtime_options(tmp_path, monkeypatch, capsys):
    captured = {}
    fetcher_options = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _v2_result()

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", fake_run)
    monkeypatch.setattr(
        cli,
        "make_search_fetcher",
        lambda **kwargs: fetcher_options.update(kwargs) or (lambda _url, _timeout: ""),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "heated-topics",
            "toutiao",
            "--profile-v2",
            str(_write_v2_profile(tmp_path, "zhao_001.json")),
            "--output-root",
            "output",
            "--fetched-at",
            "2026-07-13T10:00:00+08:00",
            "--cache-root",
            "cache-data",
            "--top-n",
            "7",
            "--force-hot-board-refresh",
            "--offline",
            "--skip-quota",
        ],
    )

    cli._main()

    profile_path = Path(captured.pop("profile_path"))
    custom_keywords = captured.pop("custom_keywords")
    on_search_committed = captured.pop("on_search_committed")
    fetcher = captured.pop("fetcher")
    assert captured == {
        "output_root": Path("output"),
        "fetched_at": "2026-07-13T10:00:00+08:00",
        "hot_board_cache_root": Path("cache-data"),
        "persona_keyword_cache_root": Path("cache-data/core_keywords"),
        "force_hot_board_refresh": True,
        "offline": True,
        "top_n": 7,
    }
    assert profile_path.name == "zhao_001.json"
    assert custom_keywords == ()
    assert on_search_committed is None  # --skip-quota wired nothing
    assert callable(fetcher)
    assert fetcher_options["paced"] is False
    output = capsys.readouterr().out
    assert "focused: outputs" in output
    assert "candidates: 7/12" in output


def test_toutiao_help_does_not_offer_runtime_llm_options(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["heated-topics", "toutiao", "--help"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli._main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--llm-keywords" not in output
    assert "--llm-summary" not in output
    assert "--no-llm" not in output


def test_toutiao_profile_keeps_legacy_dispatch(monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"report": Path("outputs/report.md")}

    monkeypatch.setattr(cli, "run_toutiao_pipeline", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["heated-topics", "toutiao", "--profile", "legacy.json", "--output-root", "output"],
    )

    cli._main()

    assert captured["profile_path"] == Path("legacy.json")
    assert captured["output_root"] == Path("output")


def test_main_prints_v2_profile_errors(tmp_path, monkeypatch, capsys):
    def fake_run(**_kwargs):
        raise ValueError("profile.json uses legacy v1 schema; please migrate to v2")

    monkeypatch.setattr(cli, "run_toutiao_pipeline_v2", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "heated-topics",
            "toutiao",
            "--profile-v2",
            str(_write_v2_profile(tmp_path, "profile.json")),
            "--skip-quota",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "legacy v1 schema" in capsys.readouterr().err


def test_check_llm_bypasses_cache(monkeypatch, capsys):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(cli, "call_llm", fake_call)
    monkeypatch.setattr("sys.argv", ["heated-topics", "check-llm"])

    cli._main()

    assert captured["use_cache"] is False
    assert captured["max_tokens"] == 16
    assert captured["prompt"] == "Reply with exactly OK."
    assert "LLM connection: OK" in capsys.readouterr().out


def test_toutiao_help_does_not_offer_llm_rerank(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["heated-topics", "toutiao", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        cli._main()

    assert exc_info.value.code == 0
    assert "--llm-rerank" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# sina-news / netease-news CLI surface
# ---------------------------------------------------------------------------


def _news_parser_defaults(command: str) -> argparse.Namespace:
    """Build a parser that only knows ``command`` and parse with required args."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser(command)
    cli._add_news_args(p)
    return parser.parse_args([command, "--profile", "p.json"])


def test_sina_news_parser_defaults():
    args = _news_parser_defaults("sina-news")
    assert args.profile == Path("p.json")
    assert args.output_root == Path("outputs")
    assert args.cache_root == Path("cache")
    assert args.top_n == 10
    assert args.fetched_at is None
    assert args.offline is False
    assert args.force_board_refresh is False
    assert args.force_search_refresh is False
    assert args.force_article_refresh is False
    assert args.matched_query_ids == []


def test_netease_news_parser_defaults():
    args = _news_parser_defaults("netease-news")
    assert args.profile == Path("p.json")
    assert args.output_root == Path("outputs")
    assert args.cache_root == Path("cache")
    assert args.top_n == 10


def test_news_parser_accepts_all_flags():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("sina-news")
    cli._add_news_args(p)
    args = parser.parse_args([
        "sina-news", "--profile", "p.json",
        "--output-root", "out", "--output-dir", "out2",
        "--cache-root", "cc", "--fetched-at", "2026-07-25T10:00:00+08:00",
        "--top-n", "7", "--offline",
        "--force-board-refresh", "--force-search-refresh", "--force-article-refresh",
        "--matched-query-ids", "q1", "--matched-query-ids", "q2",
    ])
    assert args.output_root == Path("out2")  # last one wins, matches baidu/bilibili
    assert args.cache_root == Path("cc")
    assert args.fetched_at == "2026-07-25T10:00:00+08:00"
    assert args.top_n == 7
    assert args.offline is True
    assert args.force_board_refresh is True
    assert args.force_search_refresh is True
    assert args.force_article_refresh is True
    assert args.matched_query_ids == ["q1", "q2"]


def test_sina_news_dispatch(monkeypatch, capsys):
    """Verify _main wires the right pipeline / fetcher / kwargs for sina-news."""
    captured: dict = {}
    fetcher_options: dict = {}

    from heated_topics_v3.pipeline import SinaNewsV2Result

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SinaNewsV2Result(
            user_id="zhao_001",
            date="2026-07-25",
            run_dir=Path("outputs/users/zhao_001/2026-07-25/run_120000"),
            top_n=15,
            candidates_total=12,
            kept_total=7,
            paths={"A": 2, "B": 10},
            hot_board_source="fresh",
            keyword_source="core_keywords",
            keyword_count=5,
            report_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/report.md"),
            focused_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/focused.json"),
        )

    import heated_topics_v3.fetcher_factory as ff
    import heated_topics_v3.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_sina_news_pipeline", fake_run)
    monkeypatch.setattr(
        ff,
        "make_sina_news_fetcher",
        lambda **kwargs: fetcher_options.update(kwargs) or (lambda _url, _timeout: ""),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "heated-topics",
            "sina-news",
            "--profile",
            "p.json",
            "--output-root",
            "output",
            "--fetched-at",
            "2026-07-25T10:00:00+08:00",
            "--cache-root",
            "cache-data",
            "--top-n",
            "15",
            "--offline",
            "--force-board-refresh",
            "--force-search-refresh",
            "--force-article-refresh",
            "--matched-query-ids",
            " q1 ",
            "--matched-query-ids",
            "",
            "--matched-query-ids",
            "q2",
        ],
    )

    cli._main()

    assert captured["profile_path"] == Path("p.json")
    assert captured["output_root"] == Path("output")
    assert captured["fetched_at"] == "2026-07-25T10:00:00+08:00"
    assert captured["cache_root"] == Path("cache-data")
    assert captured["top_n"] == 15
    assert captured["offline"] is True
    assert captured["force_board_refresh"] is True
    assert captured["force_search_refresh"] is True
    assert captured["force_article_refresh"] is True
    # matched_query_ids stripped and empties removed
    assert captured["matched_query_ids"] == ("q1", "q2")
    assert callable(captured["fetcher"])
    log_path = fetcher_options["log_path"]
    assert log_path.name == ".sina_news_fetcher_log.json"

    out = capsys.readouterr().out
    assert "run_dir:" in out
    assert "focused:" in out
    assert "candidates: 7/12" in out
    assert "paths: " in out
    assert "keyword_source: core_keywords" in out
    assert "keyword_count: 5" in out


def test_netease_news_dispatch(monkeypatch, capsys):
    """Verify _main wires the right pipeline / fetcher / kwargs for netease-news."""
    captured: dict = {}
    fetcher_options: dict = {}

    from heated_topics_v3.pipeline import NeteaseNewsV2Result

    def fake_run(**kwargs):
        captured.update(kwargs)
        return NeteaseNewsV2Result(
            user_id="zhao_001",
            date="2026-07-25",
            run_dir=Path("outputs/users/zhao_001/2026-07-25/run_120000"),
            top_n=30,
            candidates_total=10,
            kept_total=5,
            paths={"A": 2, "B": 8},
            hot_board_source="fresh",
            keyword_source="core_keywords",
            keyword_count=5,
            report_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/report.md"),
            focused_path=Path("outputs/users/zhao_001/2026-07-25/run_120000/focused.json"),
        )

    import heated_topics_v3.fetcher_factory as ff
    import heated_topics_v3.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_netease_news_pipeline", fake_run)
    monkeypatch.setattr(
        ff,
        "make_netease_news_fetcher",
        lambda **kwargs: fetcher_options.update(kwargs) or (lambda _url, _timeout: ""),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["heated-topics", "netease-news", "--profile", "p.json", "--fetched-at", "2026-07-25T10:00:00+08:00"],
    )

    cli._main()

    assert captured["profile_path"] == Path("p.json")
    assert captured["fetched_at"] == "2026-07-25T10:00:00+08:00"
    assert captured["matched_query_ids"] == ()
    assert callable(captured["fetcher"])
    log_path = fetcher_options["log_path"]
    assert log_path.name == ".netease_news_fetcher_log.json"

    out = capsys.readouterr().out
    assert "run_dir:" in out


def test_sina_news_generates_fetched_at_when_missing(monkeypatch, capsys):
    """When --fetched-at is absent, the handler stamps a local-time ISO string."""
    captured: dict = {}

    from heated_topics_v3.pipeline import SinaNewsV2Result

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SinaNewsV2Result(
            user_id="zhao_001",
            date="2026-07-25",
            run_dir=Path("out/run"),
            top_n=10,
            candidates_total=0,
            kept_total=0,
            paths={},
            hot_board_source="fresh",
            keyword_source="core_keywords",
            keyword_count=0,
            report_path=Path("out/run/report.md"),
            focused_path=Path("out/run/focused.json"),
        )

    import heated_topics_v3.fetcher_factory as ff
    import heated_topics_v3.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "run_sina_news_pipeline", fake_run)
    monkeypatch.setattr(
        ff,
        "make_sina_news_fetcher",
        lambda **kwargs: (lambda _url, _timeout: ""),
    )
    monkeypatch.setattr("sys.argv", ["heated-topics", "sina-news", "--profile", "p.json"])

    cli._main()

    assert captured["fetched_at"]  # non-empty
    # ISO-ish: contains a T and a timezone offset or Z
    assert "T" in captured["fetched_at"]
