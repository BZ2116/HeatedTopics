"""DailyHotApi-backed V3 provider. Reads hot lists from a local JSON cache
written by the upstream dailyhot client (https://github.com/imsyy/DailyHotApi).
Body fetch is via HTTP + GNE; see ``fetch_detail``.

Add new platforms by setting ``platform`` — no per-platform code required.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Sequence

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture

logger = logging.getLogger(__name__)


def _number_or_none(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


class DailyHotApiProvider:
    """One class, any DailyHotApi route (36kr, sspai, xiaohongshu, ...).

    Hot-list data comes from the dailyhot client's local JSON cache so we
    don't have to spin up the upstream service. Body text is fetched per
    article at serve time via httpx + GNE.

    The cache is content-addressed (files are SHA256-named). We resolve the
    ``<platform>`` argument by scanning every file's ``key`` field rather
    than guessing filenames, so cache regeneration by the upstream client
    doesn't break the lookup. Set ``DAILYHOT_CACHE_DIR`` to override the
    default ``data/cache/dailyhot`` (useful for worktrees that share a
    main-repo cache).
    """

    platform = "dailyhot"

    def __init__(
        self,
        platform: str,
        *,
        cache_dir: Path | None = None,
        client: httpx.Client | None = None,
    ):
        self.platform = platform
        if cache_dir is None:
            env_dir = os.environ.get("DAILYHOT_CACHE_DIR")
            cache_dir = Path(env_dir) if env_dir else Path("data/cache/dailyhot")
        self._cache_dir = Path(cache_dir)
        self._client = client

    @property
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(20.0),
                headers={"User-Agent": "heatedtopics-v3/0.1 (+anonymous-public-data)"},
            )
        return self._client

    def _find_cache_payload(self) -> tuple[dict[str, Any] | None, str]:
        """Scan the cache dir for a file whose ``key`` matches this provider.

        Returns the parsed payload and the raw text. ``(None, "")`` if no
        matching file is found or the dir doesn't exist.
        """
        if not self._cache_dir.exists():
            return None, ""
        target_key = f"dailyhot:{self.platform}:today"
        for entry in self._cache_dir.iterdir():
            if not entry.is_file() or not entry.suffix == ".json":
                continue
            try:
                raw = entry.read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("key") == target_key:
                return payload, raw
        return None, ""

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        payload, raw_text = self._find_cache_payload()
        if payload is None:
            return ProviderCapture(
                raw_text="", raw_suffix="", items=(), metadata={"reason": "cache_missing"}
            )
        records = [r["record"] for r in payload.get("data", []) if "record" in r]
        items = tuple(
            it for it in (self._record_to_item(r, collected_at) for r in records) if it
        )
        return ProviderCapture(
            raw_text=raw_text,
            raw_suffix="",
            items=items,
            metadata={"source": "dailyhot", "cache_key": payload.get("key", "")},
        )

    @staticmethod
    def _record_to_item(record: dict[str, Any], collected_at: str) -> HotItem | None:
        title = str(record.get("title") or "").strip()
        url = str(record.get("url") or "").strip()
        item_id = str(record.get("id") or "").strip()
        if not title or not url or not item_id:
            return None
        hot_value = _number_or_none(record.get("hot_value"))
        rank = _number_or_none(record.get("rank"))
        owner = str(record.get("owner") or "").strip()
        metrics: dict[str, int] = {}
        if hot_value is not None:
            metrics["hot"] = hot_value
        raw = record.get("raw_payload")
        if isinstance(raw, dict):
            for k in ("statRead", "statCollect", "statComment", "statPraise"):
                v = _number_or_none(raw.get(k))
                if v is not None:
                    metrics.setdefault(k.lower(), v)
        return HotItem(
            item_id=item_id,
            platform=str(record.get("platform") or "dailyhot"),
            title=title,
            url=url,
            rank=rank,
            heat=HeatMetrics(
                value=hot_value,
                label=str(record.get("category") or "hot"),
                metric_name="hot_value",
                metrics=metrics,
            ),
            summary=str(record.get("desc") or owner),
            publication_time=str(record.get("timestamp") or ""),
            collected_at=collected_at,
            raw_payload=(
                {"owner": owner, **raw} if isinstance(raw, dict) else {"owner": owner}
            ),
        )

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        """Fetch the article body via HTTP + GNE.

        Falls back to ``title_only`` (no rejection) when extraction fails so
        the item still flows through the integration layer with at least the
        title + URL; the engine's MMR diversifier can rank by title.
        """
        url = item.url
        try:
            response = self._http.get(url)
            response.raise_for_status()
            html = response.text
        except Exception as exc:
            return ItemDetail(
                item.item_id,
                "",
                "title_only",
                item.publication_time,
                collected_at,
                url,
                f"fetch_failed:{type(exc).__name__}",
            )
        content = self._extract_body(html)
        if not content or len(content) < 80:
            return ItemDetail(
                item.item_id,
                "",
                "title_only",
                item.publication_time,
                collected_at,
                url,
                "gne_empty",
            )
        return ItemDetail(
            item.item_id,
            content,
            "full_text",
            item.publication_time,
            collected_at,
            url,
            "success",
        )

    @staticmethod
    def _extract_body(html: str) -> str:
        try:
            from gne import GeneralNewsExtractor

            extracted = GeneralNewsExtractor().extract(html)
        except Exception:
            return ""
        text = str(extracted.get("content") or "").strip()
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    def enrich_metrics(
        self, items: Sequence[HotItem], collected_at: str
    ) -> tuple[HotItem, ...]:
        return tuple(items)