"""Deterministic filesystem persistence for hot-topic workflow artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .contracts import (
    DailySnapshot,
    HeatMetrics,
    HotItem,
    PlatformCollectionStatus,
    RecommendationBundle,
    RecommendationItem,
    validate_user_id,
)


BusinessDate = date | str


def _date_text(value: BusinessDate) -> str:
    return value.isoformat() if isinstance(value, date) else value


def _is_secret_field(key: object) -> bool:
    # Normalize camelCase and punctuation so header/config aliases such as
    # ``x-api-key`` and ``apiKey`` receive the same treatment.  Only mapping
    # keys are examined; ordinary string values are deliberately untouched.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip())
    normalized = re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")
    tokens = tuple(part for part in normalized.split("_") if part)
    compact = "".join(tokens)
    return (
        "cookie" in tokens
        or "cookies" in tokens
        or "authorization" in tokens
        or "secret" in tokens
        or compact.endswith("apikey")
    )


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items() if not _is_secret_field(key)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class FileRepository:
    """Read and write workflow artifacts beneath a single data root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def daily_dir(self, business_date: BusinessDate) -> Path:
        return self.root / "daily_hot_lists" / _date_text(business_date)

    def user_dir(self, user_id: str) -> Path:
        """Return a validated user directory contained by ``user_results``."""
        safe_user_id = validate_user_id(user_id)
        data_root = self.root.resolve()
        parent = (data_root / "user_results").resolve()
        try:
            parent_contained = parent.parent.samefile(data_root)
        except OSError:
            parent_contained = parent.parent == data_root
        if not parent_contained:
            raise ValueError("user_results path escapes data root")
        candidate = parent / safe_user_id
        if candidate.exists():
            resolved_parent = candidate.resolve().parent
            try:
                contained = resolved_parent.samefile(parent)
            except OSError:
                contained = resolved_parent == parent
            if not contained:
                raise ValueError("user_id path escapes user_results")
        return candidate

    def write_json(self, path: Path, value: Any) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_plain(value), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def save_raw(
        self,
        business_date: BusinessDate,
        platform: str,
        content: Any,
        *,
        suffix: str = "json",
    ) -> Path:
        path = self.daily_dir(business_date) / "raw" / f"{platform}.{suffix.lstrip('.')}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        elif isinstance(content, bytes):
            path.write_bytes(content)
        else:
            self.write_json(path, content)
        return path

    def save_normalized(
        self, business_date: BusinessDate, platform: str, items: Iterable[HotItem]
    ) -> Path:
        return self.write_json(
            self.daily_dir(business_date) / "normalized" / f"{platform}.json",
            tuple(items),
        )

    def save_detail(
        self,
        business_date: BusinessDate,
        platform: str,
        sequence: int | str,
        content: str,
    ) -> Path:
        path = self.daily_dir(business_date) / "details" / f"{platform}_{sequence}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_collection_status(
        self,
        business_date: BusinessDate,
        statuses: Iterable[PlatformCollectionStatus],
    ) -> Path:
        return self.write_json(
            self.daily_dir(business_date) / "collection_status.json", tuple(statuses)
        )

    def load_daily_snapshot(self, business_date: BusinessDate) -> DailySnapshot | None:
        directory = self.daily_dir(business_date)
        normalized = directory / "normalized"
        if not normalized.is_dir():
            return None

        items_by_platform: dict[str, tuple[HotItem, ...]] = {}
        for path in sorted(normalized.glob("*.json")):
            items_by_platform[path.stem] = tuple(
                _hot_item(item) for item in self._read_json(path)
            )

        status_path = directory / "collection_status.json"
        statuses = (
            tuple(_platform_status(item) for item in self._read_json(status_path))
            if status_path.is_file()
            else ()
        )
        timestamps = [item.collected_at for items in items_by_platform.values() for item in items]
        timestamps.extend(status.collected_at for status in statuses)
        return DailySnapshot(
            business_date=_date_text(business_date),
            collected_at=max(timestamps, default=""),
            items_by_platform=items_by_platform,
            platform_statuses=statuses,
        )

    def load_user_bundle(
        self, user_id: str, business_date: BusinessDate
    ) -> RecommendationBundle | None:
        path = self.user_dir(user_id) / _date_text(business_date) / "result.json"
        return _recommendation_bundle(self._read_json(path)) if path.is_file() else None

    def load_latest_user_bundle(self, user_id: str) -> RecommendationBundle | None:
        parent = self.user_dir(user_id)
        if not parent.is_dir():
            return None
        for directory in sorted(
            (path for path in parent.iterdir() if path.is_dir() and ".tmp-" not in path.name),
            key=lambda path: path.name,
            reverse=True,
        ):
            bundle = self.load_user_bundle(user_id, directory.name)
            if bundle is not None:
                return bundle
        return None

    def write_user_result_atomic(
        self,
        user_id: str,
        business_date: BusinessDate,
        writer: Callable[[Path], Any],
    ) -> Path:
        day = _date_text(business_date)
        parent = self.user_dir(user_id)
        final = parent / day
        if final.is_dir():
            return final

        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f"{day}.tmp-{uuid.uuid4()}"
        temporary.mkdir()
        try:
            writer(temporary)
            self._flush_tree(temporary)
            if final.is_dir():
                shutil.rmtree(temporary)
                return final
            try:
                temporary.replace(final)
            except OSError:
                if not final.is_dir():
                    raise
                shutil.rmtree(temporary)
            return final
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _flush_tree(directory: Path) -> None:
        for path in directory.rglob("*"):
            if path.is_file():
                with path.open("r+b") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())


def _heat_metrics(data: Mapping[str, Any]) -> HeatMetrics:
    return HeatMetrics(**data)


def _hot_item(data: Mapping[str, Any]) -> HotItem:
    values = dict(data)
    values["heat"] = _heat_metrics(values["heat"])
    return HotItem(**values)


def _platform_status(data: Mapping[str, Any]) -> PlatformCollectionStatus:
    return PlatformCollectionStatus(**data)


def _recommendation_item(data: Mapping[str, Any]) -> RecommendationItem:
    return RecommendationItem(**data)


def _recommendation_bundle(data: Mapping[str, Any]) -> RecommendationBundle:
    values = dict(data)
    for field in ("recommendations", "potential_topics", "general_fallback"):
        values[field] = tuple(_recommendation_item(item) for item in values.get(field, ()))
    return RecommendationBundle(**values)
