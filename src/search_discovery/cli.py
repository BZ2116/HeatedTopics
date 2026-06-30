import argparse
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.core_pipeline.model_topic_summarizer import DEFAULT_MODEL, call_openai_compatible_chat
from src.search_discovery.analysis import build_topic_analysis
from src.search_discovery.analysis_render import render_topic_analysis_markdown
from src.search_discovery.base_provider import make_error_row
from src.search_discovery.config import profile_source_weights
from src.search_discovery.discovery import cluster_results
from src.search_discovery.enrich import enrich_results
from src.search_discovery.history import (
    mark_recent_recommendations,
    read_recommendation_history,
    update_recommendation_history,
    write_recommendation_history,
)
from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.model_analysis import build_model_topic_analysis
from src.search_discovery.providers import MockProvider, SearchProviderRegistry, normalize_provider_rows
from src.search_discovery.providers_bailian import BailianWebSearchProvider
from src.search_discovery.providers_bocha import BochaSearchProvider
from src.search_discovery.providers_github import GitHubSearchProvider
from src.search_discovery.providers_qianfan import QianfanSearchProvider
from src.search_discovery.providers_qiniu import QiniuWebSearchProvider
from src.search_discovery.providers_tavily import TavilySearchProvider
from src.search_discovery.providers_tianapi import TianAPINewsProvider
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.routing import build_search_routes
from src.search_discovery.types import CreatorProfile, SearchResult

_REAL_PROVIDER_CLASSES = [
    GitHubSearchProvider,
    BochaSearchProvider,
    BailianWebSearchProvider,
    QianfanSearchProvider,
    TianAPINewsProvider,
    TavilySearchProvider,
    QiniuWebSearchProvider,
]


def _build_registry() -> SearchProviderRegistry:
    providers: list[object] = []
    for cls in _REAL_PROVIDER_CLASSES:
        real = cls.from_env()
        if real is not None:
            providers.append(real)
        else:
            providers.append(MockProvider(cls.source_id, rows=[]))
    return SearchProviderRegistry(providers)


def _emit_unavailable_markers(
    *,
    registry_source_ids: list[str],
    query: str,
    category: str,
    fetched_at: str,
    index: int,
) -> list[dict]:
    return [
        make_error_row(
            source_id=sid,
            query=query,
            category=category,
            fetch_status="mock_unavailable",
            error_type="missing_key",
            fetched_at=fetched_at,
            index=index,
        )
        for sid in registry_source_ids
    ]


def run_discovery_command(
    root: Path,
    profile_path: Path,
    render_report: bool = False,
    render_analysis: bool = False,
    analysis_mode: str = "rule",
    model_call: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
    model_name: str | None = None,
) -> dict[str, int]:
    load_dotenv(root / ".env")
    profile = CreatorProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    generated_at = _now_shanghai()
    paths = _output_paths(root)
    history = read_recommendation_history(paths["history"])
    routes = build_search_routes(profile)
    registry = _build_registry()
    results = []
    unavailable_ids = {
        sid for sid, provider in registry.providers.items()
        if isinstance(provider, MockProvider)
    }
    for counter, route in enumerate(routes):
        if route.source_id in unavailable_ids:
            marker_rows = _emit_unavailable_markers(
                registry_source_ids=[route.source_id],
                query=route.query,
                category=route.intent,
                fetched_at=generated_at,
                index=counter,
            )
            rows = normalize_provider_rows(
                rows=[
                    {
                        **row,
                        "route_weight": route.weight,
                        "route_reason": route.reason,
                        "matched_keywords": _matched_keywords(profile, row.get("title", ""), row.get("snippet", "")),
                    }
                    for row in marker_rows
                ],
                source_id=route.source_id,
                source_role=route.source_role,
                query=route.query,
                keyword_category=route.intent,
                fetched_at=generated_at,
            )
            results.extend(rows)
            continue

        rows = registry.search(
            source_id=route.source_id,
            source_role=route.source_role,
            query=route.query,
            keyword_category=route.intent,
            fetched_at=generated_at,
            index=counter,
        )
        results.extend(
            [
                SearchResult(
                    **{
                        **result.to_dict(),
                        "route_weight": route.weight,
                        "route_reason": route.reason,
                        "matched_keywords": _matched_keywords(profile, result.title, result.snippet),
                    }
                )
                for result in rows
            ]
        )
    results = mark_recent_recommendations(
        results,
        history=history,
        now=datetime.fromisoformat(generated_at),
        cooldown_days=30,
    )
    enriched = enrich_results(results)
    source_weights = profile_source_weights(profile.profile_type)
    topics = cluster_results(profile, results, enriched, source_weights=source_weights)
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
    analysis_topics_count = 0
    if render_analysis:
        model = model_name or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        analysis = build_topic_analysis(
            profile_path=profile_path,
            generated_at=generated_at,
            topics=topics,
            results=results,
            evidence=enriched,
        )
        if analysis_mode == "model":
            call = model_call or (lambda messages: call_openai_compatible_chat(messages, model=model))
            model_result = build_model_topic_analysis(
                analysis=analysis,
                model_call=call,
                model=model,
                generated_at=generated_at,
            )
            key = "model_error" if model_result.get("mode") == "model_error" else "model_synthesis"
            analysis[key] = model_result
        write_json(paths["topic_analysis"], analysis)
        paths["analysis_report"].parent.mkdir(parents=True, exist_ok=True)
        paths["analysis_report"].write_text(render_topic_analysis_markdown(analysis), encoding="utf-8")
        analysis_topics_count = len(analysis["topics"])
    updated_history = update_recommendation_history(history, results, recommended_at=generated_at)
    write_recommendation_history(paths["history"], updated_history)
    return {
        "search_results_count": len(results),
        "evidence_count": len(enriched),
        "topics_count": len(topics),
        "analysis_topics_count": analysis_topics_count,
    }


def _output_paths(root: Path) -> dict[str, Path]:
    return {
        "raw_results": root / "data/search_discovery/raw/search_results.jsonl",
        "evidence": root / "data/search_discovery/evidence/search_content_evidence.jsonl",
        "topic_index": root / "data/search_discovery/processed/search_topic_index.json",
        "report": root / "reports/search_discovery/search_topic_recommendations.md",
        "history": root / "data/search_discovery/history/recommended_topics.json",
        "topic_analysis": root / "data/search_discovery/processed/topic_analysis.json",
        "analysis_report": root / "reports/search_discovery/topic_analysis.md",
    }


def _now_shanghai() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _matched_keywords(profile: CreatorProfile, title: str, snippet: str) -> list[str]:
    haystack = f"{title} {snippet}".lower()
    return [
        keyword
        for keyword in profile.all_keywords()
        if keyword.lower() in haystack
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--render-report", action="store_true")
    parser.add_argument("--render-analysis", action="store_true")
    parser.add_argument("--analysis-mode", choices=("rule", "model"), default="rule")
    args = parser.parse_args()
    counts = run_discovery_command(
        Path("."),
        Path(args.profile),
        render_report=args.render_report,
        render_analysis=args.render_analysis,
        analysis_mode=args.analysis_mode,
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
