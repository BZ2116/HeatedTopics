import json

from src.search_discovery.cli import run_discovery_command
from src.search_discovery.providers import MockProvider, SearchProviderRegistry


class RecordingProvider:
    source_id = "github_search"

    def __init__(self):
        self.queries = []

    def search_rows(self, query, **kwargs):
        self.queries.append(query)
        return [
            {
                "result_id": "github_1",
                "title": "example/agent-framework",
                "url": "https://github.com/example/agent-framework",
                "snippet": "Agent framework",
                "content_type": "repo",
            }
        ]


class SingleGitHubProvider:
    source_id = "github_search"

    def search_rows(self, query, **kwargs):
        return [
            {
                "result_id": "github_1",
                "title": "owner/agent-framework",
                "url": "https://github.com/owner/agent-framework",
                "snippet": "AI Agent framework",
                "content_type": "repo",
                "metrics": {"stars": 1200},
            }
        ]


def test_run_discovery_command_calls_each_source_once(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "track_tags": ["AI", "开发者工具", "开源项目"],
                "custom_keywords": ["AI Agent", "MCP", "RAG"],
                "content_goal": "寻找近期技术趋势和项目",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    github = RecordingProvider()
    registry = SearchProviderRegistry(
        [
            github,
            MockProvider("juejin_content", rows=[]),
            MockProvider("baidu_qianfan_search", rows=[]),
            MockProvider("news_api_cn", rows=[]),
        ]
    )
    monkeypatch.setattr("src.search_discovery.cli._build_registry", lambda: registry)

    run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=True)

    assert len(github.queries) == 1
    assert github.queries[0].startswith("AI Agent MCP RAG in:name,description,readme stars:>200 pushed:>")
    raw_rows = [
        json.loads(line)
        for line in (tmp_path / "data/search_discovery/raw/search_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queries_by_source = {}
    for row in raw_rows:
        queries_by_source.setdefault(row["source_id"], set()).add(row["query"])
    assert all(len(queries) == 1 for queries in queries_by_source.values())


def test_run_discovery_command_writes_isolated_outputs(tmp_path):
    profile_path = tmp_path / "config/search_discovery/creator_profiles/tech_ai_creator.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "track_tags": ["AI"],
                "custom_keywords": ["AI Agent"],
                "content_modes": ["教程实践"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    counts = run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=True)

    assert counts["search_results_count"] > 0
    assert (tmp_path / "data/search_discovery/raw/search_results.jsonl").exists()
    assert (tmp_path / "data/search_discovery/processed/search_topic_index.json").exists()
    assert (tmp_path / "reports/search_discovery/search_topic_recommendations.md").exists()
    assert not (tmp_path / "data/raw/dailyhot_records.json").exists()


def test_run_discovery_command_marks_recent_github_recommendations(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "creator_id": "creator_001",
                "role": "科技类博主",
                "profile_type": "tech_ai_creator",
                "custom_keywords": ["AI Agent", "MCP", "RAG"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    history_path = tmp_path / "data/search_discovery/history/recommended_topics.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {
                "https://github.com/owner/agent-framework": {
                    "title": "owner/agent-framework",
                    "recommended_at": "2026-06-20T10:00:00+08:00",
                    "source_id": "github_search",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = SearchProviderRegistry(
        [
            SingleGitHubProvider(),
            MockProvider("juejin_content", rows=[]),
            MockProvider("baidu_qianfan_search", rows=[]),
            MockProvider("news_api_cn", rows=[]),
        ]
    )
    monkeypatch.setattr("src.search_discovery.cli._build_registry", lambda: registry)
    monkeypatch.setattr("src.search_discovery.cli._now_shanghai", lambda: "2026-06-29T12:00:00+08:00")

    run_discovery_command(root=tmp_path, profile_path=profile_path, render_report=False)

    raw_rows = [
        json.loads(line)
        for line in (tmp_path / "data/search_discovery/raw/search_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    github_row = next(row for row in raw_rows if row["source_id"] == "github_search" and row["fetch_status"] == "ok")
    assert github_row["metrics"]["recently_recommended"] is True
    updated_history = json.loads(history_path.read_text(encoding="utf-8"))
    assert updated_history["https://github.com/owner/agent-framework"]["recommended_at"] == "2026-06-29T12:00:00+08:00"