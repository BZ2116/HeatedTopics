"""Evidence-grounded creator brief generation."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .hot_topic_clustering import Topic
from .research_contracts import SearchEvidence


@dataclass(frozen=True)
class CreatorBrief:
    topic_id: str
    topic: str
    trend_score: float
    platforms: tuple[str, ...]
    summary: str
    key_facts: tuple[str, ...]
    timeline: tuple[str, ...]
    key_numbers: tuple[str, ...]
    why_trending: str
    platform_insights: tuple[str, ...]
    controversies: tuple[str, ...]
    creator_angles: tuple[str, ...]
    evidence: tuple[SearchEvidence, ...]
    evidence_status: str


class CreatorBriefGenerator:
    def __init__(self, llm_service: Any | None = None) -> None:
        self.llm_service = llm_service

    def generate(self, topic: Topic, evidence: Sequence[SearchEvidence]) -> CreatorBrief:
        cited = tuple(item for item in evidence if item.evidence_status in {"verified_article", "search_cited"})
        facts = tuple(self._clean_text(item.snippet) for item in cited if item.snippet.strip())
        status = "search_cited" if cited else "hot_item_only"
        brief = CreatorBrief(
            topic_id=topic.topic_id,
            topic=topic.title,
            trend_score=topic.trend_score,
            platforms=topic.platforms,
            summary=topic.title if not facts else facts[0],
            key_facts=facts,
            timeline=(),
            key_numbers=(),
            why_trending=f"覆盖 {topic.platform_count} 个平台" if not facts else "多个来源提供了相关报道",
            platform_insights=tuple(f"{platform} 榜单关注" for platform in topic.platforms),
            controversies=(),
            creator_angles=("事件快速解读", "事实核查", "影响分析"),
            evidence=tuple(evidence),
            evidence_status=status,
        )
        if self.llm_service is None:
            return brief
        try:
            compact_evidence = [
                {
                    "title": item.title[:180],
                    "url": item.url,
                    "snippet": re.sub(r"<[^>]+>", " ", item.snippet)[:400],
                }
                for item in evidence[:4]
            ]
            response = asyncio.run(
                self.llm_service.complete_with_core_memory(
                    system_instruction=(
                        "你是热点内容策划。只基于用户提供的热点和引用证据生成 Markdown。"
                        "不得把没有证据支持的事实写成事实。严格输出七个三级标题：摘要、已确认事实、"
                        "时间线、关键数字、热点原因、争议点、创作角度。数组区块每行用 - 开头。不要输出 JSON。"
                    ),
                    user_input=json.dumps({
                        "topic": topic.title,
                        "evidence": [
                            item for item in compact_evidence
                        ],
                    }, ensure_ascii=False),
                    json_mode=True,
                    temperature=0.3,
                    max_tokens=2400,
                    caller="recommendation",
                    inject_core_memory=False,
                )
            )
            payload = self._parse_markdown(response.content or "") or self._parse_json(response.content or "")
            if payload is None:
                retry_evidence = compact_evidence[:4]
                retry = asyncio.run(self.llm_service.complete_with_core_memory(
                    system_instruction="只输出不超过 500 字的合法 JSON，字段为 summary、key_facts、timeline、key_numbers、why_trending、controversies、creator_angles。",
                    user_input=json.dumps({"topic": topic.title, "evidence": retry_evidence}, ensure_ascii=False),
                    json_mode=True, temperature=0.1, max_tokens=1200,
                    caller="recommendation", inject_core_memory=False,
                ))
                payload = self._parse_markdown(retry.content or "") or self._parse_json(retry.content or "")
            if payload is None:
                return brief
            if not isinstance(payload, dict):
                return brief
            return CreatorBrief(
                **{
                    **brief.__dict__,
                    "summary": str(payload.get("summary") or brief.summary),
                    "key_facts": tuple(str(item) for item in payload.get("key_facts", brief.key_facts) if str(item).strip()),
                    "timeline": tuple(str(item) for item in payload.get("timeline", brief.timeline) if str(item).strip()),
                    "key_numbers": tuple(str(item) for item in payload.get("key_numbers", brief.key_numbers) if str(item).strip()),
                    "why_trending": str(payload.get("why_trending") or brief.why_trending),
                    "controversies": tuple(str(item) for item in payload.get("controversies", brief.controversies) if str(item).strip()),
                    "creator_angles": tuple(
                        str(item) for item in payload.get("creator_angles", brief.creator_angles)
                        if str(item).strip()
                    ),
                }
            )
        except Exception:
            return brief

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"```(?:json)?", "", content, flags=re.IGNORECASE).replace("```", "").strip()
        try:
            payload = json.loads(content)
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(content[start : end + 1])
                return payload if isinstance(payload, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _parse_markdown(content: str) -> dict[str, Any] | None:
        names = {"摘要":"summary", "已确认事实":"key_facts", "时间线":"timeline", "关键数字":"key_numbers", "热点原因":"why_trending", "争议点":"controversies", "创作角度":"creator_angles"}
        matches = list(re.finditer(r"^###\s*(摘要|已确认事实|时间线|关键数字|热点原因|争议点|创作角度)\s*$", content, re.MULTILINE))
        if not matches:
            return None
        result: dict[str, Any] = {}
        for i, match in enumerate(matches):
            body = content[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(content)]
            lines = [re.sub(r"^\s*[-*]\s*", "", line).strip() for line in body.splitlines() if line.strip()]
            key = names[match.group(1)]
            result[key] = " ".join(lines) if key in {"summary", "why_trending"} else lines
        return result
