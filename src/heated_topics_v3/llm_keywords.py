"""Persona-driven keyword extractor.

Reads a PersonaProfile and uses the LLM (or static core_keywords) to produce
5-10 ExtractedKeyword records annotated with match_expectation ∈ {热榜, 长尾, 兜底}.

Cached per-user in cache/core_keywords/{user_id}.json with TTL 7 days.
Cache invalidates when persona_signature changes.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from heated_topics_v3.contracts import ExtractedKeyword, PersonaProfile
from heated_topics_v3.llm_client import LLMUnavailable, call_llm, strip_code_fence


DEFAULT_CACHE_DIR = "cache/core_keywords"
DEFAULT_TTL_DAYS = 7
MIN_KEYWORDS = 5
MAX_KEYWORDS = 10
VALID_EXPECTATIONS: tuple[str, ...] = ("热榜", "长尾", "兜底")


KEYWORD_EXTRACTION_SYSTEM = """你是中文搜索引擎关键词策划助手。根据用户的 persona（一级赛道 / 二级赛道 / 角色 / 对象 / 场景 / 价值主张），生成 5-10 个检索关键词，要求：

1. 每个关键词必须能直接在中文搜索引擎（如今日头条、微信搜一搜、百度）上检索到内容
2. 关键词必须和 persona 强相关，剔除通用大词（如「新闻」「热点」）
3. 每个关键词给出 `match_expectation`：
   - 「热榜」= 该词容易命中热搜/热榜条目
   - 「长尾」= 该词容易召回长尾高质量内容
   - 「兜底」= 该词作为兜底，与 persona 直接对应但搜索量低
4. 严格输出 JSON 数组，不要代码块、不要额外解释。格式：
   [{"keyword": "...", "match_expectation": "热榜|长尾|兜底"}, ...]
"""


@dataclass(frozen=True)
class PersonaKeywordExtraction:
    user_id: str
    persona_signature: str
    generated_at: str
    keywords: tuple[ExtractedKeyword, ...]
    source: str  # "cache" | "fresh" | "fallback_core" | "no_llm"


def extract_persona_keywords(
    profile: PersonaProfile,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    ttl_days: int = DEFAULT_TTL_DAYS,
    use_cache: bool = True,
    llm: Callable[..., str] | None = None,
    allow_llm: bool = True,
) -> PersonaKeywordExtraction:
    """Extract search keywords for the persona.

    Resolution order:
      1. Cache file with matching persona_signature and fresh mtime -> return as-is
      2. LLM call (when allow_llm=True) -> parse JSON -> validate -> save cache
      3. Fallback: derive from profile.core_keywords with match_expectation="兜底"
    """
    cache_path = Path(cache_dir) / f"{profile.user_id}.json"
    if use_cache:
        cached = _read_cache(cache_path, profile.persona_signature, ttl_days)
        if cached is not None:
            return PersonaKeywordExtraction(
                user_id=profile.user_id,
                persona_signature=profile.persona_signature,
                generated_at=cached["generated_at"],
                keywords=tuple(ExtractedKeyword(k, e) for k, e in cached["keywords"]),
                source="cache",
            )

    keywords: list[ExtractedKeyword] = []
    llm_attempted = False
    llm_failed = False
    if allow_llm:
        llm_attempted = True
        try:
            keywords = _extract_via_llm(profile, llm=llm)
        except LLMUnavailable:
            llm_failed = True
            keywords = []

    padded_from_core = False
    if len(keywords) < MIN_KEYWORDS:
        before = {k.keyword for k in keywords}
        keywords = _pad_from_core(keywords, profile)
        padded_from_core = len(keywords) > len(before)

    if not keywords:
        keywords = _fallback_from_core(profile)
        source = "fallback_core"
    elif llm_failed:
        source = "fallback_core"
    elif not llm_attempted:
        source = "no_llm"
    elif padded_from_core:
        source = "fresh_padded"
    else:
        source = "fresh"

    extraction = PersonaKeywordExtraction(
        user_id=profile.user_id,
        persona_signature=profile.persona_signature,
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(keywords[:MAX_KEYWORDS]),
        source=source,
    )
    if use_cache:
        _write_cache(cache_path, extraction)
    return extraction


def _extract_via_llm(
    profile: PersonaProfile, *, llm: Callable[..., str] | None,
) -> list[ExtractedKeyword]:
    prompt = _build_prompt(profile)
    caller = llm or call_llm
    raw = caller(prompt, system=KEYWORD_EXTRACTION_SYSTEM, max_tokens=1024, temperature=0.3)
    return _parse_keywords(raw, profile)


def _build_prompt(profile: PersonaProfile) -> str:
    payload = {
        "level1": profile.level1,
        "level2": profile.level2,
        "role": profile.personal.role,
        "subject": profile.personal.subject,
        "scenarios": list(profile.personal.scenarios),
        "value": profile.personal.value,
        "core_keywords_seed": list(profile.core_keywords),
    }
    return (
        "根据以下 persona 生成 5-10 个检索关键词：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _parse_keywords(raw_text: str, profile: PersonaProfile) -> list[ExtractedKeyword]:
    cleaned = strip_code_fence(raw_text)
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    candidate = match.group(0) if match else cleaned
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    keywords: list[ExtractedKeyword] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        kw = str(entry.get("keyword") or "").strip()
        expectation = str(entry.get("match_expectation") or "").strip()
        if not kw or expectation not in VALID_EXPECTATIONS:
            continue
        keywords.append(ExtractedKeyword(keyword=kw, match_expectation=expectation))
        if len(keywords) >= MAX_KEYWORDS:
            break
    return keywords


def _fallback_from_core(profile: PersonaProfile) -> list[ExtractedKeyword]:
    seen: set[str] = set()
    keywords: list[ExtractedKeyword] = []
    for core in profile.core_keywords:
        if core and core not in seen:
            keywords.append(ExtractedKeyword(keyword=core, match_expectation="兜底"))
            seen.add(core)
    return keywords


def _pad_from_core(
    existing: list[ExtractedKeyword], profile: PersonaProfile,
) -> list[ExtractedKeyword]:
    seen = {k.keyword for k in existing}
    padded = list(existing)
    for core in profile.core_keywords:
        if len(padded) >= MIN_KEYWORDS:
            break
        if core and core not in seen:
            padded.append(ExtractedKeyword(keyword=core, match_expectation="兜底"))
            seen.add(core)
    return padded


def _read_cache(
    path: Path, persona_signature: str, ttl_days: int,
) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("persona_signature") != persona_signature:
        return None
    if ttl_days > 0:
        mtime = path.stat().st_mtime
        if (time.time() - mtime) > ttl_days * 86400:
            return None
    keywords = payload.get("keywords")
    if not isinstance(keywords, list):
        return None
    normalized = []
    for entry in keywords:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            return None
        kw, expectation = entry
        if not isinstance(kw, str) or expectation not in VALID_EXPECTATIONS:
            return None
        normalized.append((kw, expectation))
    return {"keywords": normalized, "generated_at": payload.get("generated_at", "")}


def _write_cache(path: Path, extraction: PersonaKeywordExtraction) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "user_id": extraction.user_id,
                    "persona_signature": extraction.persona_signature,
                    "generated_at": extraction.generated_at,
                    "keywords": [[k.keyword, k.match_expectation] for k in extraction.keywords],
                    "source": extraction.source,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass