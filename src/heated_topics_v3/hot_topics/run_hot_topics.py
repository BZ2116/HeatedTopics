"""Orchestration for one DailyHotApi + Web Search run."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .creator_brief import CreatorBrief, CreatorBriefGenerator
from .creator_brief_render import brief_to_dict, render_creator_briefs
from .hot_topic_clustering import Topic, cluster_hot_items, topic_fingerprint
from .hot_topic_normalization import normalize_hot_item
from .hot_topic_ranking import rank_topics
from .xhs_topic_ranking import rank_xhs_topics
from .research_contracts import SearchEvidence
from .research_provider import ResearchProvider, deduplicate_evidence
from .search_planner import SearchPlanner
from .title_topic_merging import merge_topics_with_llm
from ..llm_adapter import LLMAdapter


DEFAULT_TOPIC_LIMIT = 50


@dataclass(frozen=True)
class RunResult:
    topics: tuple[Topic, ...]
    briefs: tuple[CreatorBrief, ...]
    platform_statuses: Mapping[str, str]
    research_failures: tuple[str, ...]
    output_dir: Path


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def run_hot_topics(
    *, providers: Mapping[str, object], research_provider: ResearchProvider,
    collected_at: str, output_dir: Path, topic_limit: int = DEFAULT_TOPIC_LIMIT,
    llm_service: object | None = None, audience: str = "xhs",
    standalone_llm: bool = True,
    cached_briefs: Mapping[str, Mapping[str, Any]] | None = None,
) -> RunResult:
    if llm_service is None and standalone_llm:
        llm_service = LLMAdapter()
    items = []
    statuses: dict[str, str] = {}
    for platform, provider in providers.items():
        try:
            capture = provider.collect_hot_list(collected_at)
            items.extend(normalize_hot_item(item) for item in capture.items)
            statuses[platform] = "success" if capture.items else "empty"
        except Exception:
            statuses[platform] = "failed"

    clustered = cluster_hot_items(items)
    if audience == "xhs":
        ranked = rank_xhs_topics(clustered, limit=max(topic_limit, 50))
    else:
        ranked = rank_topics(clustered, limit=max(topic_limit, 50))
    if llm_service is not None and not cached_briefs:
        merged = merge_topics_with_llm(ranked, llm_service=llm_service)
        ranked = (
            rank_xhs_topics(merged, limit=topic_limit)
            if audience == "xhs"
            else rank_topics(merged, limit=topic_limit)
        )
    planner = SearchPlanner()
    brief_generator = CreatorBriefGenerator(llm_service=llm_service)
    briefs: list[CreatorBrief] = []
    research_failures: list[str] = []
    for priority_rank, topic in enumerate(ranked, 1):
        cached = (cached_briefs or {}).get(topic_fingerprint(topic.title))
        if cached is not None:
            briefs.append(_brief_from_cache(topic, cached))
            continue
        evidence: list[SearchEvidence] = []
        for task in planner.plan(topic, priority_rank=priority_rank):
            try:
                evidence.extend(research_provider.search(task.query, topic_id=task.topic_id))
            except Exception:
                research_failures.append(f"{topic.topic_id}:{task.purpose}")
        briefs.append(brief_generator.generate(topic, deduplicate_evidence(evidence)))

    date_dir = output_dir / collected_at[:10]
    date_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(date_dir / "hot_topics.json", json.dumps([brief_to_dict(brief) for brief in briefs], ensure_ascii=False, indent=2))
    _atomic_write(date_dir / "hot_topics.md", render_creator_briefs(briefs))
    _atomic_write(date_dir / "run_status.json", json.dumps({
        "business_date": collected_at[:10],
        "topic_count": len(ranked),
        "platform_statuses": statuses,
        "research_failures": research_failures,
    }, ensure_ascii=False, indent=2))
    return RunResult(tuple(ranked), tuple(briefs), statuses, tuple(research_failures), date_dir)


def _brief_from_cache(topic: Topic, cached: Mapping[str, Any]) -> CreatorBrief:
    evidence = tuple(
        SearchEvidence(**item) for item in cached.get("evidence", ()) if isinstance(item, Mapping)
    )
    return CreatorBrief(
        topic_id=topic.topic_id,
        topic=topic.title,
        trend_score=topic.trend_score,
        platforms=topic.platforms,
        summary=str(cached.get("summary") or topic.title),
        key_facts=tuple(str(x) for x in cached.get("key_facts", ())),
        timeline=tuple(str(x) for x in cached.get("timeline", ())),
        key_numbers=tuple(str(x) for x in cached.get("key_numbers", ())),
        why_trending=str(cached.get("why_trending") or ""),
        platform_insights=tuple(str(x) for x in cached.get("platform_insights", ())),
        controversies=tuple(str(x) for x in cached.get("controversies", ())),
        creator_angles=tuple(str(x) for x in cached.get("creator_angles", ())),
        evidence=evidence,
        evidence_status=str(cached.get("evidence_status") or "search_cited"),
    )
