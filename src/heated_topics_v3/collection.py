"""Daily collection orchestration for the Toutiao and Juejin V1 workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
import re
from typing import Any, Mapping, Protocol

from .content import validate_full_text
from .contracts import (
    ContentValidation,
    DailySnapshot,
    HeatEvidence,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    QualifiedArticle,
)
from .heat import dynamic_floors, qualifies_public_metrics
from .providers.common import (
    AuthenticationBlockedError,
    AuthenticationExpiredError,
    MissingCredentialError,
    NEWS_PLATFORMS,
    NewsProvider,
    ProviderCapture,
    ProviderContractError,
)
from .storage import FileRepository


V1_PLATFORMS = ("toutiao", "juejin")


def _news_error_code(error: Exception) -> str:
    if isinstance(error, MissingCredentialError):
        return "auth_missing"
    if isinstance(error, AuthenticationExpiredError):
        return "auth_expired"
    if isinstance(error, AuthenticationBlockedError):
        return "auth_blocked"
    if isinstance(error, ProviderContractError):
        return "contract_changed"
    return type(error).__name__


class _V1Provider(Protocol):
    def collect_hot_list(self, collected_at: str) -> ProviderCapture: ...

    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail: ...


def collect_v1_daily(
    now: datetime,
    repository: FileRepository,
    providers: Mapping[str, _V1Provider],
) -> DailySnapshot:
    """Collect and persist the two official V1 boards independently."""
    business_date = now.date().isoformat()
    collected_at = now.isoformat()
    previous_snapshot = repository.load_daily_snapshot(business_date)
    items_by_platform: dict[str, tuple[HotItem, ...]] = {}
    statuses: list[PlatformCollectionStatus] = []

    for platform in V1_PLATFORMS:
        provider = providers.get(platform)
        try:
            if provider is None:
                raise KeyError(platform)
            capture = provider.collect_hot_list(collected_at)
            if not capture.items:
                raise ValueError("empty official hot board")
            repository.save_raw(
                business_date,
                platform,
                capture.raw_text,
                suffix=capture.raw_suffix,
            )
            repository.save_normalized(business_date, platform, capture.items)
            items_by_platform[platform] = capture.items
            detail_failed, detail_failure_codes = _collect_details(
                business_date,
                platform,
                capture.items,
                provider,
                collected_at,
                repository,
                ()
                if previous_snapshot is None
                else previous_snapshot.items_by_platform.get(platform, ()),
                _previous_status(previous_snapshot, platform),
            )
            failed_item_ids = tuple(
                item.item_id for item in capture.items if item.item_id in detail_failed
            )
            statuses.append(
                PlatformCollectionStatus(
                    platform=platform,
                    status="partial" if detail_failed else "success",
                    collected_at=collected_at,
                    item_count=len(capture.items),
                    error=(
                        f"detail_fetch_failed:{','.join(failed_item_ids)}"
                        + (
                            f";cause={','.join(sorted(detail_failure_codes))}"
                            if detail_failure_codes
                            else ""
                        )
                        if detail_failed
                        else None
                    ),
                )
            )
        except Exception as error:
            statuses.append(
                PlatformCollectionStatus(
                    platform=platform,
                    status="failed",
                    collected_at=collected_at,
                    item_count=0,
                    error=type(error).__name__,
                )
            )
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    repository.save_collection_status(business_date, statuses)
    return DailySnapshot(
        business_date=business_date,
        collected_at=collected_at,
        items_by_platform=items_by_platform,
        platform_statuses=tuple(statuses),
    )


def _collect_details(
    business_date: str,
    platform: str,
    items: tuple[HotItem, ...],
    provider: _V1Provider,
    collected_at: str,
    repository: FileRepository,
    previous_items: tuple[HotItem, ...],
    previous_status: PlatformCollectionStatus | None,
) -> tuple[set[str], set[str]]:
    cached = _load_cached_details(
        business_date, platform, items, previous_items, repository
    )
    failed_item_ids = set(cached) & _previous_detail_failures(
        previous_items, previous_status
    )
    failure_codes = _previous_failure_codes(previous_status) if failed_item_ids else set()
    for sequence, item in enumerate(items, 1):
        if item.item_id in cached:
            repository.save_detail(
                business_date, platform, sequence, cached[item.item_id]
            )
    pending = [
        (sequence, item)
        for sequence, item in enumerate(items, 1)
        if item.item_id not in cached
    ]
    if not pending:
        return failed_item_ids, failure_codes

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(provider.fetch_detail, item, collected_at): (sequence, item)
            for sequence, item in pending
        }
        for future in as_completed(futures):
            sequence, item = futures[future]
            try:
                detail = future.result()
                content = detail.content
                if (
                    detail.fetch_status != "success"
                    or detail.content_status != "full_text"
                    or not content.strip()
                ):
                    failed_item_ids.add(item.item_id)
                    if ":" in detail.fetch_status:
                        code = detail.fetch_status.split(":", 1)[1]
                        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", code):
                            failure_codes.add(code)
                if not content.strip():
                    content = item.summary or item.title
            except Exception:
                content = item.summary or item.title
                failed_item_ids.add(item.item_id)
            repository.save_detail(business_date, platform, sequence, content)
    return failed_item_ids, failure_codes


def _load_cached_details(
    business_date: str,
    platform: str,
    items: tuple[HotItem, ...],
    previous_items: tuple[HotItem, ...],
    repository: FileRepository,
) -> dict[str, str]:
    current_ids = {item.item_id for item in items}
    cached: dict[str, str] = {}
    for sequence, item in enumerate(previous_items, 1):
        path = (
            repository.daily_dir(business_date)
            / "details"
            / f"{platform}_{sequence}.txt"
        )
        if item.item_id in current_ids and path.is_file():
            cached[item.item_id] = path.read_text(encoding="utf-8")
    return cached


def _previous_status(
    snapshot: DailySnapshot | None, platform: str
) -> PlatformCollectionStatus | None:
    if snapshot is None:
        return None
    return next(
        (status for status in snapshot.platform_statuses if status.platform == platform),
        None,
    )


def _previous_detail_failures(
    previous_items: tuple[HotItem, ...],
    status: PlatformCollectionStatus | None,
) -> set[str]:
    if status is None or status.status != "partial":
        return set()
    prefix = "detail_fetch_failed:"
    if status.error and status.error.startswith(prefix):
        item_ids = status.error[len(prefix) :].split(";", 1)[0]
        return {item_id for item_id in item_ids.split(",") if item_id}
    return {item.item_id for item in previous_items}


def _previous_failure_codes(status: PlatformCollectionStatus | None) -> set[str]:
    if status is None or not status.error or ";cause=" not in status.error:
        return set()
    values = status.error.split(";cause=", 1)[1]
    return {
        code
        for code in values.split(",")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", code)
    }


def collect_news_daily(
    now: datetime,
    repository: FileRepository,
    providers: Mapping[str, NewsProvider],
) -> DailySnapshot:
    """Collect and persist qualified news hot boards independently per platform."""
    business_date = now.date().isoformat()
    collected_at = now.isoformat()
    statuses: list[PlatformCollectionStatus] = []
    items_by_platform: dict[str, tuple[HotItem, ...]] = {}

    for platform in NEWS_PLATFORMS:
        provider = providers.get(platform)
        try:
            if provider is None:
                raise KeyError(platform)
            items = _collect_news_platform(
                business_date,
                platform,
                provider,
                collected_at,
                repository,
            )
            items_by_platform[platform] = items
            statuses.append(
                PlatformCollectionStatus(
                    platform=platform,
                    status="partial",
                    collected_at=collected_at,
                    item_count=len(items),
                    error=None,
                )
            )
        except Exception as error:
            statuses.append(
                PlatformCollectionStatus(
                    platform=platform,
                    status="failed",
                    collected_at=collected_at,
                    item_count=0,
                    error=_news_error_code(error),
                )
            )

    statuses = _reconcile_news_statuses(business_date, repository, statuses)
    repository.save_collection_status(business_date, statuses)

    for status in statuses:
        if status.status == "failed":
            continue
        repository.publish_active_snapshot(status.platform, business_date)

    return DailySnapshot(
        business_date=business_date,
        collected_at=collected_at,
        items_by_platform=items_by_platform,
        platform_statuses=tuple(statuses),
    )


def _collect_news_platform(
    business_date: str,
    platform: str,
    provider: NewsProvider,
    collected_at: str,
    repository: FileRepository,
) -> tuple[HotItem, ...]:
    capture = provider.collect_hot_list(collected_at)
    if not capture.items:
        raise ValueError("empty official hot board")
    repository.save_raw(
        business_date, platform, capture.raw_text, suffix=capture.raw_suffix
    )
    repository.save_normalized(business_date, platform, capture.items)

    enriched = provider.enrich_metrics(capture.items, collected_at)
    if not enriched or not isinstance(enriched, tuple):
        enriched = tuple(capture.items)

    floors = dynamic_floors(
        (dict(item.heat.metrics) for item in enriched),
        provider.absolute_floors,
    )

    detail_lookup = _fetch_news_details(
        business_date, platform, enriched, provider, collected_at, repository
    )

    eligible: list[QualifiedArticle] = []
    rejected: list[dict[str, Any]] = []
    builder = getattr(provider, "build_board_evidence", None)
    ranker = getattr(provider, "rank_articles", None)
    for item in enriched:
        detail = detail_lookup.get(item.item_id)
        if detail is None:
            detail = ItemDetail(
                item_id=item.item_id,
                content="",
                content_status="rejected",
                publication_time=item.publication_time,
                collected_at=collected_at,
                source_url=item.url,
                fetch_status="rejected:no_detail",
            )
        repository.save_stable_detail(
            business_date, platform, item.item_id, detail.content
        )
        repository.save_item_detail_metadata(
            business_date, platform, detail
        )
        evidence = (
            builder(item, floors)
            if callable(builder)
            else _build_official_evidence(item, floors)
        )
        if callable(builder):
            if evidence is None:
                rejected.append(
                    _rejected_payload(item, detail, ("rejected:no_board_evidence",))
                )
                continue
        elif not qualifies_public_metrics(dict(item.heat.metrics), floors) and (
            item.heat.value is None and not item.heat.metrics
        ):
            reasons = (detail.fetch_status,) if detail.fetch_status else ("rejected:no_metric",)
            rejected.append(_rejected_payload(item, detail, reasons))
            continue
        parser = detail.fetch_status.split(":", 1)[-1] if (
            detail.fetch_status and detail.fetch_status.startswith("rejected")
        ) else ""
        validation = validate_full_text(
            detail.content, item.title, item.summary, parser=parser
        )
        if detail.content_status != "full_text" or validation.status != "accepted":
            reasons = list(validation.reasons) or [detail.fetch_status or "rejected"]
            rejected.append(_rejected_payload(item, detail, reasons))
            continue
        qualified = QualifiedArticle(
            hot_item=item,
            detail=detail,
            heat_evidence=evidence,
            content_validation=ContentValidation(
                status=validation.status,
                parser=validation.parser,
                character_count=validation.character_count,
                paragraph_count=validation.paragraph_count,
                reasons=validation.reasons,
            ),
            platform_heat_score=0.0,
        )
        eligible.append(qualified)

    if callable(ranker):
        ordered = tuple(ranker(tuple(eligible)))
    else:
        ordered = tuple(eligible)

    repository.save_eligible(business_date, platform, ordered)
    repository.save_rejected(business_date, platform, tuple(rejected))
    return enriched


def _fetch_news_details(
    business_date: str,
    platform: str,
    items: tuple[HotItem, ...],
    provider: NewsProvider,
    collected_at: str,
    repository: FileRepository,
) -> dict[str, ItemDetail]:
    cached = _load_cached_news_details(business_date, platform, items, repository)
    results: dict[str, ItemDetail] = dict(cached)
    pending = [item for item in items if item.item_id not in cached]
    if not pending:
        return results
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(provider.fetch_detail, item, collected_at): item
            for item in pending
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                detail = future.result()
            except Exception as error:
                detail = ItemDetail(
                    item_id=item.item_id,
                    content="",
                    content_status="rejected",
                    publication_time=item.publication_time,
                    collected_at=collected_at,
                    source_url=item.url,
                    fetch_status=f"rejected:{type(error).__name__}",
                )
            results[item.item_id] = detail
    return results


def _load_cached_news_details(
    business_date: str,
    platform: str,
    items: tuple[HotItem, ...],
    repository: FileRepository,
) -> dict[str, ItemDetail]:
    cached: dict[str, ItemDetail] = {}
    details_dir = repository.daily_dir(business_date) / "details"
    for item in items:
        if not item.item_id:
            continue
        metadata_detail = repository.load_item_detail_metadata(
            business_date, platform, item.item_id
        )
        if metadata_detail is not None:
            cached[item.item_id] = metadata_detail
            continue
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item.item_id)
        path = details_dir / f"{platform}_{safe_id}.txt"
        if path.is_file():
            cached[item.item_id] = ItemDetail(
                item_id=item.item_id,
                content=path.read_text(encoding="utf-8"),
                content_status="full_text",
                publication_time=item.publication_time,
                collected_at=item.collected_at,
                source_url=item.url,
                fetch_status="cached",
            )
    return cached


def _build_official_evidence(
    item: HotItem,
    floors: Mapping[str, float],
) -> HeatEvidence:
    native = (
        float(item.heat.value)
        if isinstance(item.heat.value, (int, float))
        else None
    )
    metrics = {key: float(value) for key, value in item.heat.metrics.items()}
    if native is not None and item.heat.metric_name and item.heat.metric_name not in metrics:
        metrics[item.heat.metric_name] = float(native)
    return HeatEvidence(
        source_kind="official_hot_board",
        platform_rank=item.rank,
        native_hot_value=native,
        metrics=metrics,
        threshold_metrics=dict(floors),
        qualified_by=("official_hot_board",),
    )


def _rejected_payload(
    item: HotItem,
    detail: ItemDetail,
    reasons: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "source_url": item.url,
        "reasons": list(reasons),
    }


def _reconcile_news_statuses(
    business_date: str,
    repository: FileRepository,
    initial: list[PlatformCollectionStatus],
) -> list[PlatformCollectionStatus]:
    reconciled: list[PlatformCollectionStatus] = []
    for status in initial:
        if status.status == "failed":
            reconciled.append(status)
            continue
        day = repository.daily_dir(business_date)
        eligible_path = day / "eligible" / f"{status.platform}.json"
        rejected_path = day / "rejected" / f"{status.platform}.json"
        normalized_path = day / "normalized" / f"{status.platform}.json"
        item_count = 0
        if normalized_path.is_file():
            item_count = len(_read_json(normalized_path))
        rejected_count = (
            len(_read_json(rejected_path)) if rejected_path.is_file() else 0
        )
        qualified_count = (
            len(_read_json(eligible_path)) if eligible_path.is_file() else 0
        )
        if qualified_count == 0 and rejected_count == 0:
            new_status = "success" if item_count == 0 else "partial"
        elif qualified_count == 0:
            new_status = "partial"
        elif rejected_count == 0:
            new_status = "success"
        else:
            new_status = "partial"
        reconciled.append(
            replace(
                status,
                status=new_status,
                item_count=item_count,
            )
        )
    return reconciled


def _read_json(path) -> list:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
