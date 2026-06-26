import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.search_discovery.config import plan_sources_for_category, profile_source_weights, source_registry
from src.search_discovery.discovery import cluster_results
from src.search_discovery.enrich import enrich_results
from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.providers import MockProvider, SearchProviderRegistry
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CreatorProfile


def run_discovery_command(root: Path, profile_path: Path, render_report: bool = False) -> dict[str, int]:
    profile = CreatorProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    generated_at = _now_shanghai()
    categories = classify_keywords(profile)
    bundles = generate_query_bundles(profile, categories=categories)
    sources = source_registry()
    registry = _default_mock_registry()
    results = []
    for bundle in bundles:
        planned_sources = plan_sources_for_category(profile.profile_type, bundle.category)
        for planned_source in planned_sources:
            source = sources[planned_source.source_id]
            for query in bundle.queries:
                results.extend(
                    registry.search(
                        source_id=planned_source.source_id,
                        source_role=source.source_role,
                        query=query,
                        keyword_category=bundle.category,
                        fetched_at=generated_at,
                    )
                )
    enriched = enrich_results(results)
    source_weights = profile_source_weights(profile.profile_type)
    topics = cluster_results(profile, results, enriched, source_weights=source_weights)
    paths = _output_paths(root)
    write_jsonl(paths["raw_results"], [result.to_dict() for result in results])
    write_jsonl(paths["evidence"], [content.to_dict() for content in enriched])
    write_json(
        paths["topic_index"],
        {
            "schema_version": "0.1",
            "generated_at": generated_at,
            "profile": profile_path.as_posix(),
            "topics": [topic.to_dict() for topic in topics],
        },
    )
    if render_report:
        paths["report"].parent.mkdir(parents=True, exist_ok=True)
        paths["report"].write_text(render_topics_markdown(topics, generated_at), encoding="utf-8")
    return {
        "search_results_count": len(results),
        "evidence_count": len(enriched),
        "topics_count": len(topics),
    }


def _output_paths(root: Path) -> dict[str, Path]:
    return {
        "raw_results": root / "data/search_discovery/raw/search_results.jsonl",
        "evidence": root / "data/search_discovery/evidence/search_content_evidence.jsonl",
        "topic_index": root / "data/search_discovery/processed/search_topic_index.json",
        "report": root / "reports/search_discovery/search_topic_recommendations.md",
    }


def _default_mock_registry() -> SearchProviderRegistry:
    return SearchProviderRegistry(
        [
            MockProvider(
                "baidu_qianfan_search",
                [
                    {
                        "title": "AI Agent 最新进展：开源工具和产品能力同步升温",
                        "url": "https://example.com/ai-agent-news",
                        "snippet": "AI Agent 相关产品发布和开源项目近期持续增加。",
                        "content_type": "news",
                    }
                ],
            ),
            MockProvider(
                "news_api_cn",
                [
                    {
                        "title": "AI 工具行业出现新一轮产品发布",
                        "url": "https://example.com/ai-tool-news",
                        "snippet": "多家公司发布 AI 工具更新，开发者生态成为重点。",
                        "content_type": "news",
                    }
                ],
            ),
            MockProvider(
                "github_search",
                [
                    {
                        "title": "example/ai-agent-framework",
                        "url": "https://github.com/example/ai-agent-framework",
                        "snippet": "Open source AI Agent framework with tools and workflow support.",
                        "content_type": "repo",
                    }
                ],
            ),
            MockProvider(
                "juejin_content",
                [
                    {
                        "title": "AI Agent 掘金实践：从工具调用到工作流",
                        "url": "https://juejin.cn/post/example",
                        "snippet": "文章介绍 AI Agent 工程实践、工具调用和部署经验。",
                        "content_type": "article",
                    }
                ],
            ),
        ]
    )


def _now_shanghai() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--render-report", action="store_true")
    args = parser.parse_args()
    counts = run_discovery_command(Path("."), Path(args.profile), render_report=args.render_report)
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()