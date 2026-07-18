"""Persona-driven keyword extractor.

Reads a PersonaProfile and uses the LLM (or static core_keywords) to produce
3-10 ExtractedKeyword records annotated with match_expectation ∈ {热榜, 长尾, 兜底}.

Cached per-user in cache/core_keywords/{user_id}.json with TTL 7 days.
Cache invalidates when persona_signature changes.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from heated_topics_v3.contracts import ExtractedKeyword, PersonaProfile
from heated_topics_v3.llm_client import LLMUnavailable, call_llm, strip_code_fence


DEFAULT_CACHE_DIR = "cache/core_keywords"
DEFAULT_TTL_DAYS = 7
MIN_KEYWORDS = 3
MAX_KEYWORDS = 10
HOT_TARGET = 5
LONG_TAIL_TARGET = 4
FALLBACK_TARGET = 1
EXPECTATION_ORDER: tuple[str, ...] = ("热榜", "长尾", "兜底")
VALID_EXPECTATIONS: tuple[str, ...] = EXPECTATION_ORDER


KEYWORD_EXTRACTION_SYSTEM = """你是中文搜索引擎关键词策划助手。请根据用户提供的 persona 生成检索关键词。

【决策顺序】
1. 相关性是硬约束：每个词必须能从一级赛道、二级赛道、角色、主题、场景、价值主张或核心词种子解释出直接联系。
2. 关键词不要求在原始字段中原样出现；允许生成直接相关的上位词、下位词、人物、品牌、产品和常见热点表达。
3. 在满足相关性的候选中，优先选择更可能召回热搜、热榜或高讨论度内容的词，不能为了热度引入无关词。

【数量和分档】
- 去重后生成 3-10 个；有 3 个高质量词即可，不得为了凑满 10 个加入弱相关词。
- 3-5 个：全部标记为「热榜」。
- 6-9 个：前 5 个标记为「热榜」，其余标记为「长尾」。
- 10 个：前 5 个「热榜」，接下来 4 个「长尾」，最后 1 个「兜底」。

【词形要求】
- 中文概念优先 2-3 个字符，使用核心名词或实体词，不写句子、问题或堆叠修饰语。
- OpenAI、DeepSeek 等不可合理缩写的专有实体可以超过 3 个字符并保留原名。
- 禁止「新闻」「热点」「今日」「最新」等没有独立主题含义的泛词。

【输出格式】
严格输出 JSON 数组，不要代码块或额外解释：
[{"keyword": "...", "match_expectation": "热榜|长尾|兜底"}, ...]
"""


@dataclass(frozen=True)
class PersonaKeywordExtraction:
    user_id: str
    persona_signature: str
    generated_at: str
    keywords: tuple[ExtractedKeyword, ...]
    source: str  # "fresh" | "fallback_core" | "no_llm" | "cache_<original>"


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
            normalized = _normalize_keywords([keyword for keyword, _ in cached["keywords"]])
            cached_source = cached.get("source") or "unknown"
            return PersonaKeywordExtraction(
                user_id=profile.user_id,
                persona_signature=profile.persona_signature,
                generated_at=cached["generated_at"],
                keywords=tuple(normalized),
                source=f"cache_{cached_source}",
            )

    keywords: list[ExtractedKeyword] = []
    llm_attempted = False
    if allow_llm:
        llm_attempted = True
        try:
            keywords = _extract_via_llm(profile, llm=llm)
        except LLMUnavailable as exc:
            print(
                f"[llm_keywords] MiniMax/LLM keyword extraction failed; "
                f"using core_keywords fallback: {exc}",
                file=sys.stderr,
                flush=True,
            )
            keywords = []

    if not keywords:
        keywords = _fallback_from_core(profile)
        source = "no_llm" if not llm_attempted else "fallback_core"
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
    base_prompt = _build_prompt(profile)
    prompt = base_prompt
    caller = llm or call_llm
    best: list[ExtractedKeyword] = []
    for attempt in range(3):
        raw = caller(prompt, system=KEYWORD_EXTRACTION_SYSTEM, max_tokens=1024, temperature=0.3)
        keywords = _parse_keywords(raw)
        if len(keywords) > len(best):
            best = keywords
        if len(keywords) >= MIN_KEYWORDS:
            return keywords
        if attempt < 2:
            prompt = (
                base_prompt
                + f"\n\n上一次仅得到 {len(keywords)} 个有效关键词，少于最低要求 3 个。"
                "请补充直接相关的候选，并严格输出 JSON 数组。"
            )
    return best


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
        "根据以下 persona 生成 3-10 个相关检索关键词。"
        "相关性优先，在相关候选中优先选择更可能召回热门内容的词：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _parse_keywords(raw_text: str) -> list[ExtractedKeyword]:
    """Parse structured LLM output, then deduplicate, cap, and tier it."""
    cleaned = strip_code_fence(raw_text)
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    candidate = match.group(0) if match else cleaned
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    keywords: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        kw = str(entry.get("keyword") or "").strip()
        expectation = str(entry.get("match_expectation") or "").strip()
        if kw and expectation in VALID_EXPECTATIONS:
            keywords.append(kw)
    return _normalize_keywords(keywords)


def _normalize_keywords(keywords: list[str]) -> list[ExtractedKeyword]:
    """Deduplicate in order, cap at ten, and apply hot-first tiers."""
    unique: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        normalized = keyword.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) == MAX_KEYWORDS:
            break

    result: list[ExtractedKeyword] = []
    for index, keyword in enumerate(unique):
        if index < HOT_TARGET:
            tier = "热榜"
        elif index < HOT_TARGET + LONG_TAIL_TARGET:
            tier = "长尾"
        else:
            tier = "兜底"
        result.append(ExtractedKeyword(keyword=keyword, match_expectation=tier))
    return result


def _fallback_from_core(profile: PersonaProfile) -> list[ExtractedKeyword]:
    """Normalize static core keywords with the same hot-first contract."""
    return _normalize_keywords(list(profile.core_keywords))


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
        if not isinstance(kw, str) or not kw.strip():
            return None
        if expectation not in VALID_EXPECTATIONS:
            return None
        normalized.append((kw.strip(), expectation))
    if len(normalized) > MAX_KEYWORDS:
        return None
    source = payload.get("source")
    if not isinstance(source, str) or not source:
        source = "unknown"
    return {
        "keywords": normalized,
        "generated_at": payload.get("generated_at", ""),
        "source": source,
    }


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
