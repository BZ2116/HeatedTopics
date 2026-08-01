"""LLM-driven keyword extraction from UserSpec with per-user cache.

Calls ``LLMService.complete_with_core_memory`` to turn a user's track_1 /
track_2 / persona into 3 trending Chinese keywords. Caches the result
per-user under ``{cache_dir}/{user_id}.json``; cache is keyed by a
``sha256`` of the spec so any change to track_1 / track_2 / persona
automatically invalidates the cache.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec

if TYPE_CHECKING:
    from openbiliclaw.llm.service import LLMService

logger = logging.getLogger(__name__)

_N_KEYWORDS = 3
_CACHE_FILENAME = "keyword_cache.json"


def _spec_hash(spec: UserSpec) -> str:
    """Stable sha256 of the spec fields that influence keyword extraction.

    Changes here invalidate the per-user cache. user_id is intentionally
    excluded: changing the ID means a new user, not an updated one.
    """
    blob = f"{spec.track_1}\x00{spec.track_2}\x00{spec.persona}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fallback_keywords(spec: UserSpec) -> list[str]:
    """Return non-empty track_1/track_2 as a last-resort fallback."""
    return [t for t in (spec.track_1, spec.track_2) if t and t.strip()]


def _cache_path(cache_dir: Path, user_id: str) -> Path:
    return cache_dir / user_id / _CACHE_FILENAME


def _load_cache(cache_dir: Path, spec: UserSpec) -> list[str] | None:
    """Return cached keywords if the file exists and its spec_hash matches."""
    p = _cache_path(cache_dir, spec.user_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("keyword cache for %s unreadable: %s", spec.user_id, exc)
        return None
    if data.get("spec_hash") != _spec_hash(spec):
        return None
    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        return None
    return keywords


def _save_cache(
    cache_dir: Path, spec: UserSpec, keywords: list[str]
) -> None:
    """Persist the extracted keywords atomically."""
    p = _cache_path(cache_dir, spec.user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_hash": _spec_hash(spec),
        "keywords": keywords,
        "track_1": spec.track_1,
        "track_2": spec.track_2,
        "persona": spec.persona,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


_SYSTEM_PROMPT = """你是中文内容运营专家。给定用户画像，输出恰好 {n} 个能命中近期热点的中文搜索关键词。

要求：
1. 关键词必须是中文，2-8 个字
2. 优先选近期可能成为热点的具体词，避免宽泛抽象词
3. 关键词之间覆盖用户画像的不同子方向
4. 只返回 JSON 数组，例如：["非遗手工艺", "传统节气", "民俗活动"]
不要解释，不要其他文字。"""


_USER_PROMPT = """# 用户画像
- 赛道一：{track_1}
- 赛道二：{track_2}
- 人设：{persona}

请输出恰好 {n} 个 JSON 数组形式的关键词。"""


def _parse_keyword_json(text: str) -> list[str] | None:
    """Robustly extract a JSON list of strings from LLM output.

    Handles:
    - bare JSON array
    - ``\\`\\`\\`json ... \\`\\`\\`` fenced code block
    - leading prose + JSON
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            return None
        s = item.strip()
        if s:
            out.append(s)
    return out or None


async def _extract_via_llm(
    spec: UserSpec,
    llm_service: "LLMService",
    *,
    n: int = _N_KEYWORDS,
    timeout: float = 30.0,
) -> list[str]:
    """Call the LLM to produce n trending keywords for the user.

    On any error, returns ``_fallback_keywords(spec)`` so the pipeline
    never crashes because of a flaky LLM.
    """
    from openbiliclaw.llm.service import LLMServiceError

    try:
        response = await asyncio.wait_for(
            llm_service.complete_with_core_memory(
                system_instruction=_SYSTEM_PROMPT.format(n=n),
                user_input=_USER_PROMPT.format(
                    track_1=spec.track_1,
                    track_2=spec.track_2,
                    persona=spec.persona,
                    n=n,
                ),
                json_mode=True,
                temperature=0.5,
                max_tokens=512,
                caller="integration.keyword_extraction",
                inject_core_memory=False,
            ),
            timeout=timeout,
        )
    except (LLMServiceError, asyncio.TimeoutError, RuntimeError, ValueError) as exc:
        logger.warning(
            "keyword extraction LLM call failed for %s: %s", spec.user_id, exc,
        )
        return _fallback_keywords(spec)
    keywords = _parse_keyword_json(response.content or "")
    if not keywords:
        logger.warning(
            "keyword extraction returned no parseable list for %s: %r",
            spec.user_id, (response.content or "")[:200],
        )
        return _fallback_keywords(spec)
    return keywords[:n]


async def extract_or_load(
    spec: UserSpec,
    llm_service: "LLMService",
    cache_dir: Path,
    *,
    n: int = _N_KEYWORDS,
) -> list[str]:
    """Return n keywords for the user, preferring the per-user cache.

    Cache is keyed by ``_spec_hash(spec)``; if the user's track_1/track_2/
    persona change, the hash changes and the keywords are re-extracted.
    """
    cached = _load_cache(cache_dir, spec)
    if cached is not None:
        logger.info("keyword cache hit for %s (%d kw)", spec.user_id, len(cached))
        return cached[:n]
    logger.info("keyword cache miss for %s; calling LLM", spec.user_id)
    keywords = await _extract_via_llm(spec, llm_service, n=n)
    try:
        _save_cache(cache_dir, spec, keywords)
    except OSError as exc:
        logger.warning(
            "failed to persist keyword cache for %s: %s", spec.user_id, exc,
        )
    return keywords
