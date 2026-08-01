"""LLM-driven keyword extraction from UserSpec with per-user cache.

Calls ``LLMService.complete_with_core_memory`` to turn a user's track_1 /
track_2 / persona into 3 trending Chinese keywords. Caches the result
per-user under ``{cache_dir}/{user_id}.json``; cache is keyed by a
``sha256`` of the spec so any change to track_1 / track_2 / persona
automatically invalidates the cache.
"""

from __future__ import annotations

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
