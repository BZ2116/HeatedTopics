import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.search_discovery.base_provider import make_error_row
from src.search_discovery.config import plan_sources_for_category, profile_source_weights, source_registry
from src.search_discovery.discovery import cluster_results
from src.search_discovery.enrich import enrich_results
from src.search_discovery.io import write_json, write_jsonl
from src.search_discovery.keywords import classify_keywords, generate_query_bundles
from src.search_discovery.providers import MockProvider, SearchProviderRegistry, normalize_provider_rows
from src.search_discovery.providers_bailian import BailianWebSearchProvider
from src.search_discovery.providers_bocha import BochaSearchProvider
from src.search_discovery.providers_github import GitHubSearchProvider
from src.search_discovery.providers_qianfan import QianfanSearchProvider
from src.search_discovery.render import render_topics_markdown
from src.search_discovery.types import CreatorProfile, SearchResult

_REAL_PROVIDER_CLASSES = [
    GitHubSearchProvider,
    BochaSearchProvider,
    BailianWebSearchProvider,
    QianfanSearchProvider,
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


def run_discovery_command(root: Path, profile_path: Path, render_report: bool = False) -> dict[str, int]:
    load_dotenv()
    profile = CreatorProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    generated_at = _now_shanghai()
    categories = classify_keywords(profile)
    bundles = generate_query_bundles(profile, categories=categories)
    sources = source_registry()
    registry = _build_registry()
    results = []
    unavailable_ids = {
        sid for sid, provider in registry.providers.items()
        if isinstance(provider, MockProvider)
    }
    counter = 0
    for bundle in bundles:
        planned_sources = plan_sources_for_category(profile.profile_type, bundle.category)
        for planned_source in planned_sources:
            source = sources[planned_source.source_id]
            for query in bundle.queries:
                if planned_source.source_id in unavailable_ids:
                    marker_rows = _emit_unavailable_markers(
                        registry_source_ids=[planned_source.source_id],
                        query=query, category=bundle.category, fetched_at=generated_at,
                        index=counter,
                    )
                    results.extend(normalize_provider_rows(
                        rows=marker_rows,
                        source_id=planned_source.source_id,
                        source_role=source.source_role,
                        query=query,
                        keyword_category=bundle.category,
                        fetched_at=generated_at,
                    ))
                else:
                    results.extend(
                        registry.search(
                            source_id=planned_source.source_id,
                            source_role=source.source_role,
                            query=query,
                            keyword_category=bundle.category,
                            fetched_at=generated_at,
                            index=counter,
                        )
                    )
                counter += 1
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
