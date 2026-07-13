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
            )
            statuses.append(
                PlatformCollectionStatus(
                    platform=platform,
                    status="partial" if detail_failed else "success",
                    collected_at=collected_at,
                    item_count=len(capture.items),
                    error="detail_fetch_failed" if detail_failed else None,
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
) -> bool:
    pending = [
        (sequence, item)
        for sequence, item in enumerate(items, 1)
        if not (
            repository.daily_dir(business_date)
            / "details"
            / f"{platform}_{sequence}.txt"
        ).is_file()
    ]
    if not pending:
        return False

    failed = False
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(provider.fetch_detail, item, collected_at): (sequence, item)
            for sequence, item in pending
        }
        for future in as_completed(futures):
            sequence, item = futures[future]
            try:
                content = future.result().content
            except Exception:
                content = item.summary or item.title
                failed = True
            repository.save_detail(business_date, platform, sequence, content)
    return failed
