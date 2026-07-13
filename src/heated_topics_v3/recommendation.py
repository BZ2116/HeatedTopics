"""Cached user-result generation for the Toutiao and Juejin V1 workflow."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Protocol

from .clock import business_date, is_before_daily_cutoff
from .contracts import (
    HotItem,
    ItemDetail,
    RecommendationBundle,
    RecommendationItem,
    UserProfile,
)
from .matching import build_v1_recommendations
from .providers.common import ProviderCapture
from .reporting import (
    render_markdown,
    render_topic_txt,
    serialize_bundle,
    topic_txt_filename,
)
from .storage import FileRepository


class _ToutiaoSearchProvider(Protocol):
    def search(self, primary_keyword: str, collected_at: str) -> ProviderCapture: ...


_LOCK_REGISTRY_GUARD = Lock()
_GENERATION_LOCKS: dict[tuple[str, str], Lock] = {}
_CLAIM_WAIT_SECONDS = 30


def _generation_lock(user_id: str, day: str) -> Lock:
    with _LOCK_REGISTRY_GUARD:
        return _GENERATION_LOCKS.setdefault((user_id, day), Lock())


def _try_claim_lock(handle) -> bool:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _release_claim_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _filesystem_generation_claim(
    repository: FileRepository, user_id: str, day: str
):
    parent = repository.root / "user_results" / user_id
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / f"{day}.lock"
    result_path = parent / day / "result.json"
    deadline = time.monotonic() + _CLAIM_WAIT_SECONDS
    with lock_path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while not _try_claim_lock(handle):
            if result_path.is_file():
                yield False
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield False
                return
            time.sleep(min(0.01, remaining))
        try:
            if result_path.is_file():
                yield False
            else:
                yield True
        finally:
            _release_claim_lock(handle)


def _empty_bundle(
    status: str, profile: UserProfile, day: str, generated_at: str
) -> RecommendationBundle:
    return RecommendationBundle(
        status=status,
        user_id=profile.user_id,
        business_date=day,
        generated_at=generated_at,
        recommendations=(),
        potential_topics=(),
        general_fallback=(),
        query_metadata={},
    )


def _as_existing(bundle: RecommendationBundle) -> RecommendationBundle:
    return replace(bundle, status="existing")


def _content_status(item: HotItem, content: str) -> str:
    if content == item.title:
        return "title_only"
    if content == item.summary:
        return "summary"
    return "full_text"


def _load_details(
    repository: FileRepository,
    day: str,
    items_by_platform: dict[str, tuple[HotItem, ...]],
) -> dict[str, ItemDetail]:
    details: dict[str, ItemDetail] = {}
    for platform in ("toutiao", "juejin"):
        for sequence, item in enumerate(items_by_platform.get(platform, ()), 1):
            path = (
                repository.daily_dir(day)
                / "details"
                / f"{platform}_{sequence}.txt"
            )
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            details[item.item_id] = ItemDetail(
                item_id=item.item_id,
                content=content,
                content_status=_content_status(item, content),
                publication_time=item.publication_time,
                collected_at=item.collected_at,
                source_url=item.url,
                fetch_status="success",
            )
    return details


def _write_artifacts(
    directory: Path, bundle: RecommendationBundle
) -> None:
    (directory / "report.md").write_text(
        render_markdown(bundle), encoding="utf-8"
    )
    (directory / "result.json").write_text(
        serialize_bundle(bundle), encoding="utf-8"
    )
    topics = directory / "topics"
    topics.mkdir()
    items = (*bundle.recommendations, *bundle.general_fallback, *bundle.potential_topics)
    for sequence, item in enumerate(items, 1):
        (topics / topic_txt_filename(item, sequence)).write_text(
            render_topic_txt(item), encoding="utf-8"
        )


def generate_v1_user_result(
    profile: UserProfile,
    now: datetime,
    repository: FileRepository,
    toutiao_provider: _ToutiaoSearchProvider,
) -> RecommendationBundle:
    """Generate or reuse the user's atomic two-platform V1 artifact bundle."""
    generated_at = now.isoformat()
    if is_before_daily_cutoff(now):
        latest = repository.load_latest_user_bundle(profile.user_id)
        if latest is not None:
            return _as_existing(latest)
        return _empty_bundle(
            "not_ready", profile, business_date(now).isoformat(), generated_at
        )

    day = business_date(now).isoformat()
    existing = repository.load_user_bundle(profile.user_id, day)
    if existing is not None:
        return _as_existing(existing)
    if repository.load_daily_snapshot(day) is None:
        return _empty_bundle("not_ready", profile, day, generated_at)

    with _generation_lock(profile.user_id, day):
        existing = repository.load_user_bundle(profile.user_id, day)
        if existing is not None:
            return _as_existing(existing)
        with _filesystem_generation_claim(
            repository, profile.user_id, day
        ) as claimed:
            if not claimed:
                winner = repository.load_user_bundle(profile.user_id, day)
                return _as_existing(winner) if winner else _empty_bundle(
                    "failed", profile, day, generated_at
                )

            snapshot = repository.load_daily_snapshot(day)
            if snapshot is None:
                return _empty_bundle("not_ready", profile, day, generated_at)

            items_by_platform = {
                platform: tuple(snapshot.items_by_platform.get(platform, ()))
                for platform in ("toutiao", "juejin")
            }
            details = _load_details(repository, day, items_by_platform)
            try:
                search_items = toutiao_provider.search(
                    profile.primary_keyword, generated_at
                ).items
                search_status = "success"
            except Exception as error:
                search_items = ()
                search_status = f"failed:{type(error).__name__}"

            matched = build_v1_recommendations(
                profile,
                items_by_platform["toutiao"],
                search_items,
                items_by_platform["juejin"],
                details,
            )
            formal = tuple(item for item in matched if item.heat_level in (1, 2))
            potential = tuple(item for item in matched if item.heat_level == 3)
            status = "generated" if formal or potential else "no_result"
            bundle = RecommendationBundle(
                status=status,
                user_id=profile.user_id,
                business_date=day,
                generated_at=generated_at,
                recommendations=formal,
                potential_topics=potential,
                general_fallback=(),
                query_metadata={"toutiao_search_status": search_status},
            )
            repository.write_user_result_atomic(
                profile.user_id,
                day,
                lambda directory: _write_artifacts(directory, bundle),
            )
            winner = repository.load_user_bundle(profile.user_id, day)
            return bundle if winner == bundle else _as_existing(winner or bundle)
