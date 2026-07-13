"""Daily collection orchestration for the Toutiao and Juejin V1 workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Mapping, Protocol

from .contracts import DailySnapshot, HotItem, ItemDetail, PlatformCollectionStatus
from .providers.common import ProviderCapture
from .storage import FileRepository


V1_PLATFORMS = ("toutiao", "juejin")


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
        try:
            provider = providers[platform]
            capture = provider.collect_hot_list(collected_at)
            repository.save_raw(
                business_date,
                platform,
                capture.raw_text,
                suffix=capture.raw_suffix,
            )
            repository.save_normalized(business_date, platform, capture.items)
            items_by_platform[platform] = capture.items
            detail_failed = _collect_details(
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
) -> set[str]:
    cached = _load_cached_details(
        business_date, platform, items, previous_items, repository
    )
    failed_item_ids = set(cached) & _previous_detail_failures(
        previous_items, previous_status
    )
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
        return failed_item_ids

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
                if not content.strip():
                    content = item.summary or item.title
            except Exception:
                content = item.summary or item.title
                failed_item_ids.add(item.item_id)
            repository.save_detail(business_date, platform, sequence, content)
    return failed_item_ids


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
        return {item_id for item_id in status.error[len(prefix) :].split(",") if item_id}
    return {item.item_id for item in previous_items}
