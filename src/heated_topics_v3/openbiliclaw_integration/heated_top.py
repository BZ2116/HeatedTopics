"""Daily shared hot-topic generation facade."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from heated_topics_v3.providers.dailyhot import DailyHotApiProvider
from heated_topics_v3.contracts import HeatMetrics, HotItem
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.hot_topics.run_hot_topics import run_hot_topics
from heated_topics_v3.llm_adapter import LLMAdapter, LLMConfig
from heated_topics_v3.hot_topics.research_provider import MiniMaxMcpResearchProvider


class _CachedHotProvider:
    def __init__(self, platform: str, path: Path):
        self.platform = platform
        self.path = path

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = []
        items = []
        for index, record in enumerate(records if isinstance(records, list) else (), 1):
            if not isinstance(record, dict) or not str(record.get("title") or "").strip():
                continue
            heat = record.get("heat") or {}
            rank = heat.get("rank") or record.get("rank") or index
            items.append(HotItem(
                item_id=str(record.get("article_id") or f"{self.platform}_{index}"),
                platform=self.platform,
                title=str(record.get("title")),
                url=str(record.get("url") or record.get("source_url") or ""),
                rank=int(rank) if str(rank).isdigit() else index,
                heat=HeatMetrics(heat.get("hot_value"), str(heat.get("hot_value") or ""), "hot"),
                summary=str(record.get("body_text") or record.get("summary") or ""),
                publication_time=str(record.get("published_at") or "") or None,
                collected_at=collected_at,
                raw_payload=record,
            ))
        return ProviderCapture("", "", tuple(items), {"source": "hot_cache"})


def _fingerprint(title: str) -> str:
    from heated_topics_v3.hot_topics.hot_topic_clustering import topic_fingerprint
    return topic_fingerprint(title)


class HeatedTop:
    """One daily shared hot-topic job; repeated runs reuse same-day cards."""

    def run(self, *, run_dir: str | Path, limit: int = 50, force: bool = False) -> dict[str, Any]:
        root = Path(run_dir)
        if not (root / "hot_cache").exists() and (root.parent / "hot_cache").exists():
            root = root.parent
        cache_dir = root / "hot_cache"
        dated = sorted(p for p in cache_dir.iterdir() if p.is_dir()) if cache_dir.exists() else []
        if dated:
            cache_dir = dated[-1]
        output_dir = root / "daily_hot"
        output_dir.mkdir(parents=True, exist_ok=True)
        old_path = output_dir / "topics.json"
        old: dict[str, dict[str, Any]] = {}
        if old_path.exists() and not force:
            try:
                old = {_fingerprint(x["topic"]): x for x in json.loads(old_path.read_text(encoding="utf-8"))}
            except (OSError, ValueError, KeyError, TypeError):
                old = {}

        platforms = ("juejin", "netease_news", "sina_news", "thepaper", "toutiao", "zhihu_daily", "weibo", "zhihu")
        providers = {
            p: _CachedHotProvider(p, cache_dir / f"{p}.json")
            for p in platforms if (cache_dir / f"{p}.json").exists()
        }
        config = LLMConfig.from_env()
        research = MiniMaxMcpResearchProvider(
            api_key=os.getenv("MINIMAX_API_KEY", config.api_key),
            api_host=os.getenv("MINIMAX_API_HOST", "https://api.minimaxi.com"),
        )
        try:
            result = run_hot_topics(
                providers=providers,
                research_provider=research,
                collected_at=datetime.now().astimezone().isoformat(),
                output_dir=output_dir,
                topic_limit=limit,
                llm_service=LLMAdapter(config),
                audience="xhs",
                cached_briefs=old,
            )
        finally:
            research.close()

        cards = []
        for brief in result.briefs:
            card = {
                "fingerprint": _fingerprint(brief.topic),
                **{k: v for k, v in brief_to_json(brief).items() if k != "evidence"},
                "evidence": [evidence_to_json(x) for x in brief.evidence],
            }
            if not force and card["fingerprint"] in old:
                cached = dict(old[card["fingerprint"]])
                cached["trend_score"] = card["trend_score"]
                cached["platforms"] = card["platforms"]
                card = cached
            cards.append(card)
        (output_dir / "topics.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "topics.md").write_text("\n\n".join(f"## {i+1}. {x['topic']}\n\n{x['summary']}" for i, x in enumerate(cards)), encoding="utf-8")
        status = {"date": root.name.removeprefix("run_"), "topic_count": len(cards), "cached_count": sum(1 for x in cards if _fingerprint(x["topic"]) in old and not force), "research_failures": list(result.research_failures)}
        (output_dir / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"date": status["date"], "topics": cards, "cached_count": status["cached_count"], "research_failures": status["research_failures"]}


def brief_to_json(brief: Any) -> dict[str, Any]:
    return {k: getattr(brief, k) for k in ("topic_id", "topic", "trend_score", "platforms", "summary", "key_facts", "timeline", "key_numbers", "why_trending", "platform_insights", "controversies", "creator_angles", "evidence_status")}


def evidence_to_json(item: Any) -> dict[str, Any]:
    return {k: getattr(item, k) for k in ("topic_id", "query", "title", "url", "source", "published_at", "snippet", "retrieved_at", "provider", "evidence_status")}
