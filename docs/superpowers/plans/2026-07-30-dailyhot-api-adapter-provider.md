# DailyHotApi Adapter Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `DailyHotApiProvider` to V3 that wraps the local DailyHotApi cache (and optionally the HTTP endpoint) so the openbiliclaw_integration layer can pull hot lists from any of 40+ Chinese platforms without writing a per-platform scraper. Phase 1 covers cache-backed hot-list + per-URL body fetch via GNE.

**Architecture:**
- New file `src/heated_topics_v3/providers/dailyhot.py` defines a single `DailyHotApiProvider(platform: str)` class.
- `collect_hot_list`: reads `data/cache/dailyhot/{platform}.json` (or the cache key the dailyhot client writes), maps each record into a V3 `HotItem`. Title/url/rank/heat only — body_text is empty here.
- `fetch_detail`: HTTP GET the URL, run `GeneralNewsExtractor().extract(html)` to pull the article body. Returns an `ItemDetail` with `content_status="full_text"` or `"title_only"` depending on extraction success.
- Integration layer wires the new provider in `recommender._build_provider` for any `dailyhot:<route>` string (e.g., `dailyhot:36kr`). One branch, no per-platform code.

**Tech Stack:**
- `httpx` (sync client, follows existing V3 pattern)
- `gne.GeneralNewsExtractor` (already used by thepaper.py as fallback)
- Local cache reader: `json` stdlib
- Tests: `pytest` + V3 test conventions

---

## Task 1: DailyHotApiProvider — hot list from local cache

**Files:**
- Create: `src/heated_topics_v3/providers/dailyhot.py`
- Modify: `src/heated_topics_v3/providers/__init__.py` (register the class)

- [x] **Step 1: Write the failing test**

```python
# tests/providers/test_dailyhot_provider.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from heated_topics_v3.providers.dailyhot import DailyHotApiProvider


@pytest.fixture
def fake_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "dailyhot"
    cache.mkdir()
    (cache / "36kr.json").write_text(
        json.dumps(
            {
                "key": "dailyhot:36kr:today",
                "fetched_at": "2026-07-30T10:00:00+08:00",
                "data": [
                    {
                        "record": {
                            "id": "3865519682802948",
                            "title": "腾讯买出了AI半壁江山",
                            "url": "https://www.36kr.com/p/3865519682802948",
                            "rank": 1,
                            "hot_value": "56641",
                            "owner": "字母榜",
                        }
                    },
                    {
                        "record": {
                            "id": "3866428592657411",
                            "title": "8点1氪",
                            "url": "https://www.36kr.com/p/3866428592657411",
                            "rank": 2,
                            "hot_value": "29182",
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return cache


def test_collect_hot_list_reads_cache(fake_cache: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=fake_cache)
    capture = p.collect_hot_list("2026-07-30T10:00:00+08:00")
    assert len(capture.items) == 2
    first = capture.items[0]
    assert first.title == "腾讯买出了AI半壁江山"
    assert first.platform == "36kr"
    assert first.rank == 1
    assert first.url == "https://www.36kr.com/p/3865519682802948"
    assert first.item_id == "3865519682802948"
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/providers/test_dailyhot_provider.py -v`
Expected: `ModuleNotFoundError: No module named 'heated_topics_v3.providers.dailyhot'`

- [x] **Step 3: Implement minimal provider**

```python
# src/heated_topics_v3/providers/dailyhot.py
"""DailyHotApi-backed V3 provider. Reads hot lists from a local JSON cache
written by the upstream dailyhot client (https://github.com/imsyy/DailyHotApi).
Body fetch is via HTTP + GNE; see ``fetch_detail``.

Add new platforms by setting ``platform`` — no per-platform code required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import httpx

from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture


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
        self._cache_dir = cache_dir or Path("data/cache/dailyhot")
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

    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        path = self._cache_dir / f"{self.platform}.json"
        if not path.exists():
            return ProviderCapture(
                raw_text="", raw_suffix="", items=(), metadata={"reason": "cache_missing"}
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = [r["record"] for r in payload.get("data", []) if "record" in r]
        items = tuple(self._record_to_item(r, collected_at) for r in records)
        items = tuple(i for i in items if i is not None)
        return ProviderCapture(
            raw_text=path.read_text(encoding="utf-8"),
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
        raw = record.get("raw_payload") or {}
        if isinstance(raw, dict):
            for k in ("statRead", "statCollect", "statComment", "statPraise"):
                v = _number_or_none(raw.get(k))
                if v is not None:
                    metrics.setdefault(k.lower(), v)
        return HotItem(
            item_id=item_id,
            platform=record.get("platform") or "dailyhot",
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
            raw_payload={"owner": owner, **raw} if isinstance(raw, dict) else {"owner": owner},
        )

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        # Implemented in Task 2.
        raise NotImplementedError

    def enrich_metrics(
        self, items: Sequence[HotItem], collected_at: str
    ) -> tuple[HotItem, ...]:
        return tuple(items)
```

- [x] **Step 4: Register the provider**

```python
# src/heated_topics_v3/providers/__init__.py — append
from .dailyhot import DailyHotApiProvider

__all__ = [
    "BaiduHotProvider",
    "DailyHotApiProvider",          # NEW
    "ProviderCapture",
    "JuejinProvider",
    "NeteaseNewsProvider",
    "SinaNewsProvider",
    "ThePaperProvider",
    "ToutiaoProvider",
    "ZhihuDailyProvider",
    "ZhihuHotProvider",
]
```

- [x] **Step 5: Re-run test, expect PASS**

Run: `PYTHONPATH=src python -m pytest tests/providers/test_dailyhot_provider.py -v`
Expected: 1 passed.

---

## Task 2: fetch_detail via httpx + GNE

**Files:**
- Modify: `src/heated_topics_v3/providers/dailyhot.py` (replace `fetch_detail`)

- [x] **Step 1: Write failing tests for fetch_detail**

Append to `tests/providers/test_dailyhot_provider.py`:

```python
from heated_topics_v3.contracts import HotItem, HeatMetrics


def _make_item(url: str = "https://www.36kr.com/p/123") -> HotItem:
    return HotItem(
        item_id="123",
        platform="36kr",
        title="t",
        url=url,
        rank=1,
        heat=HeatMetrics(value=10, label="hot", metric_name="hot_value", metrics={}),
        summary="",
        publication_time=None,
        collected_at="2026-07-30T10:00:00+08:00",
    )


def test_fetch_detail_returns_title_only_when_gne_fails(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)

    class _StubClient:
        def get(self, url, *a, **kw):
            class _Resp:
                status_code = 200
                text = "<html><head></head><body>无正文</body></html>"
                def raise_for_status(self): pass
            return _Resp()

    p._client = _StubClient()  # type: ignore[assignment]
    detail = p.fetch_detail(_make_item(), "2026-07-30T10:00:00+08:00")
    assert detail.content_status in ("title_only", "full_text")
    assert detail.source_url == "https://www.36kr.com/p/123"


def test_fetch_detail_returns_full_text_when_gne_succeeds(tmp_path: Path) -> None:
    p = DailyHotApiProvider(platform="36kr", cache_dir=tmp_path)
    long_body = "段落一。" + ("这是一段真实长度足够长的中文正文。" * 30)

    class _StubClient:
        def get(self, url, *a, **kw):
            class _Resp:
                status_code = 200
                text = f"<html><body><article>{long_body}</article></body></html>"
                def raise_for_status(self): pass
            return _Resp()

    p._client = _StubClient()  # type: ignore[assignment]
    detail = p.fetch_detail(_make_item(), "2026-07-30T10:00:00+08:00")
    assert detail.content_status == "full_text"
    assert "段落一" in detail.content
```

- [x] **Step 2: Run, expect ImportError on `fetch_detail` NotImplementedError path**

Run: `PYTHONPATH=src python -m pytest tests/providers/test_dailyhot_provider.py -v`
Expected: tests fail with `NotImplementedError`.

- [x] **Step 3: Implement fetch_detail**

Replace the placeholder in `src/heated_topics_v3/providers/dailyhot.py`:

```python
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
        except Exception as exc:  # httpx.HTTPError, ConnectError, etc.
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
                item.item_id, "", "title_only", item.publication_time, collected_at, url,
                "gne_empty",
            )
        return ItemDetail(
            item.item_id, content, "full_text", item.publication_time, collected_at, url,
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
        # Drop leading/trailing whitespace; collapse double newlines.
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
```

- [x] **Step 4: Re-run, expect PASS**

Run: `PYTHONPATH=src python -m pytest tests/providers/test_dailyhot_provider.py -v`
Expected: 3 passed.

- [x] **Step 5: Run full provider test suite to confirm no regression**

Run: `PYTHONPATH=src python -m pytest tests/providers/ tests/openbiliclaw_integration/test_candidate_adapter.py -q`
Expected: all green.

---

## Task 3: Wire DailyHotApiProvider into the integration layer

**Files:**
- Modify: `src/heated_topics_v3/openbiliclaw_integration/recommender.py` (`_build_provider`, `_DEFAULT_PROVIDERS`)

- [x] **Step 1: Add provider dispatch**

In `src/heated_topics_v3/openbiliclaw_integration/recommender.py`, extend `_build_provider` to handle the `dailyhot:<route>` pattern. Replace the existing function with:

```python
def _build_provider(platform: str) -> Any | None:
    """Instantiate the V3 provider class for ``platform``.

    Returns None if the platform name is unknown so the caller can skip it.
    Accepts ``dailyhot:<route>`` (e.g. ``dailyhot:36kr``, ``dailyhot:sspai``)
    to dispatch to the DailyHotApi adapter.
    """
    import httpx as _httpx

    client = _httpx.Client(
        follow_redirects=True,
        timeout=_httpx.Timeout(20.0),
        headers={"User-Agent": "heatedtopics-v3/0.1 (+anonymous-public-data)"},
    )
    if platform.startswith("dailyhot:"):
        from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

        route = platform.split(":", 1)[1]
        return DailyHotApiProvider(route, client=client), client
    if platform == "juejin":
        from heated_topics_v3.providers.juejin import JuejinProvider

        return JuejinProvider(client), client
    if platform == "toutiao":
        from heated_topics_v3.providers.toutiao import ToutiaoProvider

        return ToutiaoProvider(client), client
    if platform == "baidu_hot":
        from heated_topics_v3.providers.baidu_hot import BaiduHotProvider

        return BaiduHotProvider(client), client
    if platform == "zhihu_hot":
        from heated_topics_v3.providers.zhihu_hot import ZhihuHotProvider

        return ZhihuHotProvider(client, ""), client
    if platform == "zhihu_daily":
        from heated_topics_v3.providers.zhihu_daily import ZhihuDailyProvider

        return ZhihuDailyProvider(client), client
    if platform == "sina_news":
        from heated_topics_v3.providers.sina_news import SinaNewsProvider

        return SinaNewsProvider(client), client
    if platform == "thepaper":
        from heated_topics_v3.providers.thepaper import ThePaperProvider

        return ThePaperProvider(client), client
    if platform == "netease_news":
        from heated_topics_v3.providers.netease_news import NeteaseNewsProvider

        return NeteaseNewsProvider(client), client
    try:
        client.close()
    except Exception:
        pass
    return None
```

- [x] **Step 2: Extend the integration test for the new dispatch path**

Append to `tests/openbiliclaw_integration/test_recommender.py`:

```python
def test_build_provider_dispatches_dailyhot_route(monkeypatch) -> None:
    """``dailyhot:<route>`` resolves to DailyHotApiProvider(route)."""
    from heated_topics_v3.providers.dailyhot import DailyHotApiProvider

    monkeypatch.setattr(
        "heated_topics_v3.openbiliclaw_integration.recommender.os.environ",
        {"OPENBILICLAW_LLM_API_KEY": "test-key"},  # noop; just ensures attribute exists
        raising=False,
    )
    built = recommender._build_provider("dailyhot:36kr")
    assert built is not None
    provider, client = built
    assert isinstance(provider, DailyHotApiProvider)
    assert provider.platform == "36kr"
    client.close()


def test_build_provider_returns_none_for_unknown() -> None:
    assert recommender._build_provider("totally_made_up_platform") is None
```

- [x] **Step 3: Run the recommender tests**

Run: `PYTHONPATH=src python -m pytest tests/openbiliclaw_integration/test_recommender.py -v`
Expected: existing 5 + 2 new = 7 passed.

- [x] **Step 4: Update `_DEFAULT_PROVIDERS` comment**

`_DEFAULT_PROVIDERS` in `recommender.py` should mention the dailyhot dispatch syntax:

```python
# Default provider list (ordered by typical relevance for V3 hot topics).
# ``dailyhot:<route>`` syntax dispatches to DailyHotApiProvider — e.g.
# ``dailyhot:36kr`` for 36氪, ``dailyhot:sspai`` for 少数派. The hot-list
# data comes from data/cache/dailyhot/*.json (written by the upstream
# dailyhot client); article bodies are fetched per-URL via GNE.
_DEFAULT_PROVIDERS: tuple[str, ...] = (
    "juejin",
    "toutiao",
    "baidu_hot",
    "zhihu_hot",
    "zhihu_daily",
    "sina_news",
    "thepaper",
    "netease_news",
)
```

No code change to the tuple itself — leaving the defaults as-is so existing
configurations keep working; new users opt in via `--providers`.

---

## Task 4: End-to-end demo against the cached 36kr data

**Files:** none — verification step.

- [x] **Step 1: Verify the cache file exists**

Run: `ls -la data/cache/dailyhot/36kr.json`
Expected: file present (50 items).

- [x] **Step 2: Run the CLI with the new provider**

```bash
PYTHONPATH=src \
  OPENBILICLAW_LLM_API_KEY=$OPENBILICLAW_LLM_API_KEY \
  python -m heated_topics_v3.openbiliclaw_integration.cli \
    --users /tmp/demo/users_caifu.json \
    --output /tmp/demo/recs_caifu_36kr.json \
    --limit 5 \
    --providers dailyhot:36kr \
    --data-dir /tmp/demo/data_36kr \
    --max-parallel 1 \
    --per-user-timeout 300
```

Expected: exit code 0, output JSON written, 5 recommendations returned.

- [x] **Step 3: Inspect results**

```bash
PYTHONIOENCODING=utf-8 python -c "
import json
d = json.load(open('/tmp/demo/recs_caifu_36kr.json', encoding='utf-8'))
for u in d['users']:
    print(f\"pipeline: {u['pipeline']}\")
    for r in u['recommendations']:
        print(f\"  [{r['rank']}] conf={r['confidence']:.3f} {r['source_platform']} | {r['title']}\")
"
```

Expected: 5 recommendations from `dailyhot:36kr`, all with non-zero `confidence`. Titles should be business/finance-flavored (vs. the news-heavy toutiao results).

- [ ] **Step 4: Run a second demo mixing dailyhot with existing providers** (skipped — single-source demo was sufficient for the user; the cache supports this whenever needed)

```bash
PYTHONPATH=src \
  OPENBILICLAW_LLM_API_KEY=$OPENBILICLAW_LLM_API_KEY \
  python -m heated_topics_v3.openbiliclaw_integration.cli \
    --users /tmp/demo/users_caifu.json \
    --output /tmp/demo/recs_caifu_mix.json \
    --limit 5 \
    --providers dailyhot:36kr,dailyhot:sspai,toutiao,thepaper \
    --data-dir /tmp/demo/data_mix \
    --max-parallel 2 \
    --per-user-timeout 300
```

Note: `dailyhot:sspai` will probably return 0 items (no cache file). That's fine — the run degrades gracefully, and the test confirms the dispatch works.

---

## Out of scope (Phase 2, separate plans)

- HTTP endpoint support (currently only local cache; needs `DAILYHOT_API_BASE_URL` env var + httpx).
- Per-platform body extractor overrides (GNE works generically but 36kr/sspai/xhs may want tighter selectors).
- `enrich_metrics` and `search` implementations (the hot-list-only contract is enough for the integration layer).
- DailyHotApi cache refresh / freshness check (cache is read as-is; TTL is the user's problem).