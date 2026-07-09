import re
from pathlib import Path
from typing import Any

from src.search_discovery.source_labels import search_engine_name
from src.search_discovery.types import CandidateTopic, EnrichedContent, SearchResult

SCHEMA_VERSION = "0.1"


def build_topic_analysis(
    *,
    profile_path: Path,
    generated_at: str,
    topics: list[CandidateTopic],
    results: list[SearchResult],
    evidence: list[EnrichedContent],
    content_modes: list[str],
    search_routes: list[dict[str, Any]] | None = None,
    model_synthesis: dict[str, Any] | None = None,
    model_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic_rows = [_topic_row(topic, evidence, content_modes) for topic in topics]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "profile": profile_path.as_posix(),
        "statistics": _statistics(topics, results, evidence),
        "search_queries": search_routes or [],
        "topics": topic_rows,
        "model_synthesis": model_synthesis,
        "model_error": model_error,
    }


def _statistics(
    topics: list[CandidateTopic],
    results: list[SearchResult],
    evidence: list[EnrichedContent],
) -> dict[str, Any]:
    return {
        "total_topics": len(topics),
        "total_results": len(results),
        "total_evidence": len(evidence),
        "source_distribution": _count(result.source_id for result in results if result.fetch_status == "ok"),
        "keyword_distribution": _count(keyword for topic in topics for keyword in topic.matched_keywords),
        "risk_distribution": _count(topic.risk_level for topic in topics),
        "content_type_distribution": _count(_hit_text(hit, "content_type") for topic in topics for hit in topic.source_hits),
        "freshness_distribution": _count(topic.freshness for topic in topics),
        "score_buckets": _score_buckets(topics),
        "recently_recommended_count": sum(
            1
            for topic in topics
            for hit in topic.source_hits
            if bool(hit.get("recently_recommended")) or bool(_hit_metrics(hit).get("recently_recommended"))
        ),
    }


def _topic_row(topic: CandidateTopic, evidence: list[EnrichedContent], content_modes: list[str]) -> dict[str, Any]:
    topic_evidence = _evidence_for_topic(topic, evidence)
    source_ids = _unique(_hit_text(hit, "source_id") for hit in topic.source_hits)
    search_engines = _unique(_hit_search_engine(hit) for hit in topic.source_hits)
    content_types = _unique(_hit_text(hit, "content_type") for hit in topic.source_hits)
    rule_summary = _rule_summary(topic, topic_evidence, content_modes)
    return {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "priority": _priority(topic.topic_score),
        "topic_score": topic.topic_score,
        "matched_keywords": topic.matched_keywords,
        "keyword_categories": topic.keyword_categories,
        "freshness": topic.freshness,
        "risk_level": topic.risk_level,
        "detail_level": topic.detail_level,
        "evidence_count": len(topic_evidence),
        "source_ids": source_ids,
        "search_engines": search_engines,
        "content_types": content_types,
        "rule_summary": rule_summary,
        "verification_summary": _verification_summary(topic, topic_evidence),
        "suggested_titles": _suggested_titles(topic),
        "evidence": topic_evidence,
        "llm_context": _llm_context(topic, topic_evidence),
    }


def _evidence_for_topic(topic: CandidateTopic, evidence: list[EnrichedContent]) -> list[dict[str, Any]]:
    urls = {str(hit.get("url", "")).rstrip("/") for hit in topic.source_hits if hit.get("url")}
    titles = {str(hit.get("title", "")).strip() for hit in topic.source_hits if hit.get("title")}
    rows: list[dict[str, Any]] = []
    for item in evidence:
        if item.url.rstrip("/") not in urls and item.title.strip() not in titles:
            continue
        rows.append(
            {
                "result_id": item.result_id,
                "title": item.title,
                "url": item.url,
                "content_excerpt": _truncate(item.content, 220),
                "content_quality": item.content_quality,
                "evidence_confidence": item.evidence_confidence,
                "published_at": item.published_at,
                "source_type": _source_type(_source_id_for_evidence(item, topic), ""),
                "source_name": _source_name(_source_id_for_evidence(item, topic)),
            }
        )
    if rows:
        return rows
    return [
        {
            "result_id": "",
            "title": _hit_text(hit, "title"),
            "url": _hit_text(hit, "url"),
            "content_excerpt": "",
            "content_quality": "low",
            "evidence_confidence": "low",
            "published_at": "",
            "source_type": _source_type(_hit_text(hit, "source_id"), _hit_text(hit, "content_type")),
            "source_name": _source_name(_hit_text(hit, "source_id")),
        }
        for hit in topic.source_hits
    ]


def _source_id_for_evidence(item: EnrichedContent, topic: CandidateTopic) -> str:
    item_url = item.url.rstrip("/")
    item_title = item.title.strip()
    for hit in topic.source_hits:
        if item_url and item_url == _hit_text(hit, "url").rstrip("/"):
            return _hit_text(hit, "source_id")
        if item_title and item_title == _hit_text(hit, "title"):
            return _hit_text(hit, "source_id")
    return ""


def _rule_summary(topic: CandidateTopic, evidence: list[dict[str, Any]], content_modes: list[str]) -> dict[str, Any]:
    return {
        "one_line_summary": _truncate(topic.summary, 180),
        "why_it_matters": _why_it_matters(topic),
        "creator_angles": _creator_angles(topic, content_modes),
        "recommended_format": _recommended_format(topic),
        "verification_notes": _verification_notes(topic, evidence),
    }


def _why_it_matters(topic: CandidateTopic) -> str:
    keyword_text = "、".join(topic.matched_keywords) or "当前关键词"
    source_count = len({str(hit.get("source_id", "")) for hit in topic.source_hits if hit.get("source_id")})
    return f"该话题命中 {keyword_text}，来自 {source_count} 个来源，当前评分 {topic.topic_score}，适合进入选题池继续核验。"


def _creator_angles(topic: CandidateTopic, content_modes: list[str]) -> list[str]:
    if content_modes:
        return content_modes[:3]
    categories = set(topic.keyword_categories)
    if "tech_project" in categories:
        return ["项目拆解", "工具对比", "实现教程"]
    if "tech_article" in categories:
        return ["教程总结", "实践清单", "架构解释"]
    if "news_trend" in categories:
        return ["时间线梳理", "影响分析", "后续观察"]
    if "product_trend" in categories:
        return ["产品对比", "使用场景分析", "市场解读"]
    return ["趋势观察", "证据汇总", "案例拆解"]


def _recommended_format(topic: CandidateTopic) -> str:
    content_types = {_hit_text(hit, "content_type") for hit in topic.source_hits}
    if topic.risk_level == "high":
        return "research_note"
    if "repo" in content_types:
        return "research_note"
    if topic.risk_level == "medium":
        return "article"
    if topic.freshness == "breaking":
        return "short_post"
    return "article"


def _verification_notes(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if topic.risk_level == "high":
        notes.append("高风险话题，需要人工核验事实、来源和措辞。")
    elif topic.risk_level == "medium":
        notes.append("中风险话题，建议核验发布时间和关键事实。")
    if len({str(hit.get("source_id", "")) for hit in topic.source_hits if hit.get("source_id")}) <= 1:
        notes.append("single-source: 目前主要来自单一来源，发布前建议补充交叉证据。")
    if any(bool(hit.get("recently_recommended")) or bool(_hit_metrics(hit).get("recently_recommended")) for hit in topic.source_hits):
        notes.append("recently recommended: 该话题近期推荐过，注意避免重复选题。")
    if not any(row.get("published_at") for row in evidence):
        notes.append("缺少明确发布时间，建议打开来源页面复核时效性。")
    return notes or ["低风险，但不要把单一来源扩大为行业共识。"]


def _verification_summary(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    source_count = len({str(hit.get("source_id", "")) for hit in topic.source_hits if hit.get("source_id")})
    has_clear_publish_time = any(str(row.get("published_at", "")).strip() for row in evidence)
    notes = _unique([*topic.verification_notes, *_verification_notes(topic, evidence)])
    return {
        "source_count": source_count,
        "verification_score": topic.verification_score,
        "evidence_level": topic.evidence_level,
        "has_clear_publish_time": has_clear_publish_time,
        "risk_label": _risk_label(topic.risk_level),
        "confidence_label": _confidence_label(topic.verification_score),
        "risk_flags": topic.risk_flags,
        "notes": notes,
    }


def _suggested_titles(topic: CandidateTopic) -> list[str]:
    keyword_text = "、".join(topic.matched_keywords[:2]) or "关键词"
    title = topic.title.strip()
    if not title:
        return []
    return [
        f"{title}，国内热点背后发生了什么？",
        f"{title}为什么值得关注？一文梳理关键信号",
        f"围绕{keyword_text}，{title}有哪些新变化？",
    ]


def _risk_label(risk_level: str) -> str:
    return {"low": "低", "medium": "中", "high": "高"}.get(risk_level, "未知")


def _confidence_label(verification_score: int) -> str:
    if verification_score >= 85:
        return "高"
    if verification_score >= 65:
        return "中"
    return "低"


def _source_type(source_id: str, content_type: str) -> str:
    if source_id == "github_search" or content_type == "repo":
        return "技术项目"
    if source_id in {"tianapi_news", "news_api_cn"} or content_type == "news":
        return "新闻媒体"
    if "official" in source_id or content_type in {"docs", "official"}:
        return "官方/公告"
    if content_type in {"community_post", "blog"}:
        return "社区/自媒体"
    if source_id:
        return "搜索结果"
    return "未知来源"


def _source_name(source_id: str) -> str:
    if not source_id:
        return "未知来源"
    return search_engine_name(source_id)


def _llm_context(topic: CandidateTopic, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    all_text = " ".join(str(row.get("content_excerpt", "")) for row in evidence[:3] if row.get("content_excerpt"))
    content_summary = _extract_content_summary(all_text)
    return {
        "compact_summary": _truncate(topic.summary, 320),
        "content_summary": content_summary,
        "evidence_bullets": [
            f"{row.get('title', '')}: {_truncate(str(row.get('content_excerpt', '')), 160)}"
            for row in evidence[:5]
        ],
        "source_titles": [_hit_text(hit, "title") for hit in topic.source_hits if _hit_text(hit, "title")],
        "metrics": {
            "topic_score": topic.topic_score,
            "profile_match_score": topic.profile_match_score,
            "source_count": len(topic.source_hits),
        },
        "risk_flags": _verification_notes(topic, evidence),
    }


def _extract_content_summary(text: str) -> dict[str, Any]:
    if not text.strip():
        return {"core_insight": "", "key_points": []}

    core_insight = ""
    sentences = _split_sentences(text)
    for s in sentences:
        s = s.strip()
        if len(s) > 15 and not _is_noise_sentence(s):
            core_insight = s
            break

    key_points: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 编号列表：1、2、3 或 1. 2. 或 ★ ● ◆
        if re.match(r"^\d+[.、]", line) or re.match(r"^[一二三四五六七八九十][、.]", line):
            cleaned = re.sub(r"^[一二三四五六七八九十\d][.、\s]+", "", line)
            if len(cleaned) > 4:
                key_points.append(cleaned[:150])
        elif re.match(r"^[*★●◆✦✱\-]", line):
            cleaned = line.lstrip("*★●◆✦✱- ")
            if len(cleaned) > 4:
                key_points.append(cleaned[:150])
        elif "建议" in line or "注意" in line or "可以" in line or "应该" in line or "关键" in line or "核心" in line:
            if len(line) > 10 and len(line) < 200:
                key_points.append(line[:150])

    seen = set()
    deduped: list[str] = []
    for p in key_points:
        norm = p.lower()[:60]
        if norm not in seen and len(deduped) < 8:
            seen.add(norm)
            deduped.append(p)

    return {
        "core_insight": core_insight[:200],
        "key_points": deduped,
    }


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"[。！？\.]+", lambda m: m.group(0) + "\n", text)
    return [s.strip() for s in text.split("\n") if s.strip()]


def _is_noise_sentence(s: str) -> bool:
    noise = {"新浪财经", "东方财富", "微信公众号", "加载中", "点击查看", "更多精彩", "热门推荐", "相关阅读", "分享", "收藏"}
    return any(n in s for n in noise) or len(s) < 10


def _priority(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _score_buckets(topics: list[CandidateTopic]) -> dict[str, int]:
    buckets = {"80_plus": 0, "60_to_79": 0, "40_to_59": 0, "under_40": 0}
    for topic in topics:
        if topic.topic_score >= 80:
            buckets["80_plus"] += 1
        elif topic.topic_score >= 60:
            buckets["60_to_79"] += 1
        elif topic.topic_score >= 40:
            buckets["40_to_59"] += 1
        else:
            buckets["under_40"] += 1
    return buckets


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _unique(values) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _hit_text(hit: dict[str, Any], key: str) -> str:
    return str(hit.get(key, "") or "").strip()


def _hit_metrics(hit: dict[str, Any]) -> dict[str, Any]:
    metrics = hit.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _hit_search_engine(hit: dict[str, Any]) -> str:
    return _hit_text(hit, "search_engine") or search_engine_name(_hit_text(hit, "source_id"))


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
