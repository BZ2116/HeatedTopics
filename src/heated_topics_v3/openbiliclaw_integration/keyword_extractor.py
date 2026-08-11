"""LLM-driven keyword extraction from UserSpec with per-user cache.

Calls ``LLMService.complete_with_core_memory`` to turn a user's track_1 /
track_2 / persona into 3 trending Chinese keywords. Caches the result
per-user under ``{cache_dir}/{user_id}.json``; cache is keyed by a
``sha256`` of the spec so any change to track_1 / track_2 / persona
automatically invalidates the cache.

Design note: rather than ask the LLM to invent fresh keywords from scratch,
we pre-extract *anchor terms* (high-frequency / unambiguous 2-4 char
Chinese tokens from the spec, see :func:`_extract_anchor_terms`) and feed
them into the prompt as a hard constraint. The LLM must keep at least one
anchor in its output — this prevents drift where the model invents adjacent
but off-topic terms (e.g. returning "赶集文化" when the spec keeps saying
"非遗"). The remaining 2 keywords may extend into adjacent sub-niches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from heated_topics_v3.openbiliclaw_integration.user_profile import UserSpec, _spec_hash

if TYPE_CHECKING:
    from openbiliclaw.llm.service import LLMService

logger = logging.getLogger(__name__)

_N_KEYWORDS = 3
_CACHE_FILENAME = "keyword_cache.json"

# Tokens shorter than this are too generic to anchor on (e.g. 的/是/和).
# Tokens longer than this are usually phrase fragments, not searchable terms.
_ANCHOR_MIN_LEN = 2
_ANCHOR_MAX_LEN = 6
_ANCHOR_MAX = 6  # cap anchors in the prompt; LLM gets the top N most prominent
_ANCHOR_SPLIT_RE = re.compile(r"[\s/&、，,+\-]+|与|和|及|之|的")


def _fallback_keywords(spec: UserSpec) -> list[str]:
    """Return non-empty track_1/track_2 as a last-resort fallback."""
    return [t for t in (spec.track_1, spec.track_2) if t and t.strip()]


def _extract_anchor_terms(spec: UserSpec) -> list[str]:
    """Pull the most prominent Chinese terms from track_1/track_2/persona.

    Splits on CJK-friendly separators (mirrors OpenBiliClaw's
    :func:`interest_aliases`), counts occurrences across the three fields,
    and returns the top :data:`_ANCHOR_MAX` terms sorted by frequency (ties
    broken by first appearance in track_1 → track_2 → persona).

    For multi-char tokens (4+ chars), also surface 2-3 char CJK substrings so
    the anchor check can recognise partial matches like "非遗" inside "非遗扩展".

    The result seeds the prompt as a hard "must keep at least one" constraint
    so the LLM cannot drift away from the user's declared domain.
    """
    fields = (spec.track_1, spec.track_2, spec.persona)
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    counter = 0
    for field_idx, text in enumerate(fields):
        if not text:
            continue
        for chunk in _ANCHOR_SPLIT_RE.split(text):
            token = chunk.strip()
            if (
                _ANCHOR_MIN_LEN <= len(token) <= _ANCHOR_MAX_LEN
                and any("一" <= ch <= "鿿" for ch in token)
            ):
                counts[token] = counts.get(token, 0) + 1
                if token not in order:
                    order[token] = field_idx * 1000 + counter
                    counter += 1
                # Also count 2-3 char CJK substrings so partial matches count
                # (e.g. "非遗" inside "非遗扩展").
                if len(token) >= 4:
                    for start in range(len(token) - _ANCHOR_MIN_LEN + 1):
                        for size in (_ANCHOR_MIN_LEN, _ANCHOR_MIN_LEN + 1):
                            sub = token[start : start + size]
                            if (
                                any("一" <= ch <= "鿿" for ch in sub)
                                and sub not in counts
                            ):
                                counts[sub] = 0  # presence-only, no count bump
                                order[sub] = field_idx * 1000 + counter
                                counter += 1
    ranked = sorted(
        counts.items(), key=lambda kv: (-kv[1], order[kv[0]]),
    )
    return [t for t, _ in ranked[:_ANCHOR_MAX]]


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

<anchors>
下面是用户画像里**最核心的词**（按出现频率排）。要求：
- 输出的 {n} 个关键词中，**至少 {min_anchor} 个必须包含至少一个核心词作为子串**（如核心词"非遗" → "非遗手工艺"、"非遗美食"都算命中）。
- 核心词是用户明确定位过的领域；不要用同义/近义词整体替换它们（如不要把"非遗"换成"传统文化"）。
- 围绕核心词扩展的子方向要覆盖不同切面（如工艺/传承/人物/场景/节令），不要重复同一维度。
</anchors>

<rules>
1. 关键词必须是中文，2-8 个字，适合在百度/微博/B站/知乎/抖音搜索框直接输入。
2. 优先选近期可能成为热点的具体词，避免宽泛抽象词（如"文化"太泛，"非遗手工艺"更好）。
3. 关键词之间覆盖用户画像的不同子方向，不要 3 个都聚焦同一窄面。
4. 只返回 JSON 数组，例如：["非遗手工艺", "传统节气", "民俗活动"]。不要解释，不要其他文字。
</rules>"""


_USER_PROMPT = """# 用户画像
- 赛道一：{track_1}
- 赛道二：{track_2}
- 人设：{persona}

# 核心词（必含）
{anchors}

请输出恰好 {n} 个 JSON 数组形式的关键词，至少 {min_anchor} 个包含核心词作为子串。"""


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
        lines = [line for line in lines if not line.strip().startswith("```")]
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
    min_anchor: int = 1,
    timeout: float = 30.0,
) -> list[str]:
    """Call the LLM to produce n trending keywords for the user.

    On any error, returns ``_fallback_keywords(spec)`` so the pipeline
    never crashes because of a flaky LLM.

    :param min_anchor: at least this many of the n keywords must contain an
        anchor term as a substring. Set to 0 to disable the constraint.
    """
    from openbiliclaw.llm.service import LLMServiceError

    anchors = _extract_anchor_terms(spec)
    if not anchors:
        min_anchor = 0
    try:
        response = await asyncio.wait_for(
            llm_service.complete_with_core_memory(
                system_instruction=_SYSTEM_PROMPT.format(
                    n=n, min_anchor=min_anchor,
                ),
                user_input=_USER_PROMPT.format(
                    track_1=spec.track_1,
                    track_2=spec.track_2,
                    persona=spec.persona,
                    anchors=(
                        "、".join(anchors)
                        if anchors else "（无）"
                    ),
                    n=n,
                    min_anchor=min_anchor,
                ),
                json_mode=True,
                temperature=0.5,
                max_tokens=512,
                caller="integration.keyword_extraction",
                inject_core_memory=False,
            ),
            timeout=timeout,
        )
    except (TimeoutError, LLMServiceError, RuntimeError, ValueError) as exc:
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
    keywords = keywords[:n]
    # Enforce anchor constraint locally — even if the LLM ignored the prompt,
    # at least min_anchor outputs must contain an anchor substring.
    if min_anchor > 0 and anchors:
        anchored = [
            kw for kw in keywords
            if any(a in kw for a in anchors)
        ]
        shortfall = min_anchor - len(anchored)
        if shortfall > 0:
            logger.warning(
                "keyword extraction missed anchor constraint for %s: "
                "got %d anchored, need %d; padding from anchors",
                spec.user_id, len(anchored), min_anchor,
            )
            # Prepend anchors so they survive the final [:n] slice.
            pad: list[str] = []
            for a in anchors:
                if shortfall <= 0:
                    break
                if a not in keywords:
                    pad.append(a)
                    shortfall -= 1
            keywords = (pad + keywords)[:n]
    return keywords


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
