"""Deterministic filesystem persistence for hot-topic workflow artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from unicodedata import normalize

from .contracts import (
    ContentValidation,
    DailySnapshot,
    HeatEvidence,
    HeatMetrics,
    HotItem,
    ItemDetail,
    PlatformCollectionStatus,
    QualifiedArticle,
    RecommendationBundle,
    RecommendationItem,
    SearchCacheRecord,
    validate_user_id,
)


BusinessDate = date | str

_SHANGHAI = timezone(timedelta(hours=8))


def _normalize_keyword(keyword: str) -> str:
    return " ".join(normalize("NFKC", keyword).casefold().split())


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
        return self._scoped_user_dir(user_id, "user_results")

    def news_user_dir(self, user_id: str) -> Path:
        """Return a validated user directory contained by ``news_user_results``."""
        return self._scoped_user_dir(user_id, "news_user_results")

    def _scoped_user_dir(self, user_id: str, root_name: str) -> Path:
        safe_user_id = validate_user_id(user_id)
        data_root = self.root.resolve()
        parent = (data_root / root_name).resolve()
        try:
            parent_contained = parent.parent.samefile(data_root)
        except OSError:
            parent_contained = parent.parent == data_root
        if not parent_contained:
            raise ValueError(f"{root_name} path escapes data root")
        candidate = parent / safe_user_id
        if candidate.exists():
            resolved_parent = candidate.resolve().parent
            try:
                contained = resolved_parent.samefile(parent)
            except OSError:
                contained = resolved_parent == parent
            if not contained:
                raise ValueError(f"user_id path escapes {root_name}")
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

    def save_stable_detail(
        self,
        business_date: BusinessDate,
        platform: str,
        item_id: str,
        content: str,
    ) -> Path:
        """Persist article detail keyed by a filesystem-safe stable item id."""
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item_id)
        path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_item_detail_metadata(
        self,
        business_date: BusinessDate,
        platform: str,
        detail: ItemDetail,
    ) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", detail.item_id)
        path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.json"
        return self.write_json(path, detail)

    def load_item_detail_metadata(
        self,
        business_date: BusinessDate,
        platform: str,
        item_id: str,
    ) -> ItemDetail | None:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item_id)
        path = self.daily_dir(business_date) / "details" / f"{platform}_{safe_id}.json"
        if not path.is_file():
            return None
        return _item_detail_from_dict(self._read_json(path))

    def save_eligible(
        self,
        business_date: BusinessDate,
        platform: str,
        articles: Iterable[QualifiedArticle],
    ) -> Path:
        return self.write_json(
            self.daily_dir(business_date) / "eligible" / f"{platform}.json",
            tuple(articles),
        )

    def save_rejected(
        self,
        business_date: BusinessDate,
        platform: str,
        rejected: Iterable[Mapping[str, Any]],
    ) -> Path:
        return self.write_json(
            self.daily_dir(business_date) / "rejected" / f"{platform}.json",
            tuple(rejected),
        )

    def load_eligible(
        self, business_date: BusinessDate, platform: str
    ) -> tuple[QualifiedArticle, ...]:
        path = self.daily_dir(business_date) / "eligible" / f"{platform}.json"
        if not path.is_file():
            return ()
        return tuple(
            _qualified_article_from_dict(item) for item in self._read_json(path)
        )

    def search_cache_dir(
        self, business_date: BusinessDate, platform: str, keyword: str
    ) -> Path:
        digest = sha256(_normalize_keyword(keyword).encode("utf-8")).hexdigest()
        return (
            self.root
            / "search_cache"
            / _date_text(business_date)
            / platform
            / digest
        )

    def save_search_cache(
        self,
        business_date: BusinessDate,
        platform: str,
        keyword: str,
        *,
        status: str,
        articles: Iterable[QualifiedArticle] = (),
        rejected: Iterable[Mapping[str, Any]] = (),
        collected_at: str = "",
        retry_after: str | None = None,
    ) -> Path:
        record = SearchCacheRecord(
            status=status,
            business_date=_date_text(business_date),
            platform=platform,
            normalized_keyword=_normalize_keyword(keyword),
            collected_at=collected_at,
            articles=tuple(articles),
            rejected=tuple(rejected),
            retry_after=retry_after,
        )
        return self.write_json(
            self.search_cache_dir(business_date, platform, keyword) / "status.json",
            record,
        )

    def load_search_cache(
        self, business_date: BusinessDate, platform: str, keyword: str
    ) -> SearchCacheRecord | None:
        path = (
            self.search_cache_dir(business_date, platform, keyword) / "status.json"
        )
        if not path.is_file():
            return None
        return _search_cache_record_from_dict(self._read_json(path))

    def publish_active_snapshot(
        self, platform: str, business_date: BusinessDate
    ) -> Path:
        target = self.root / "active_snapshots" / f"{platform}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        self.write_json(temporary, {"business_date": _date_text(business_date)})
        temporary.replace(target)
        return target

    def resolve_eligible_snapshot(
        self,
        platform: str,
        now_iso: str,
        max_age_hours: float = 48,
    ) -> tuple[str, tuple[QualifiedArticle, ...]] | None:
        pointer = self.root / "active_snapshots" / f"{platform}.json"
        if not pointer.is_file():
            return None
        snapshot_date = str(self._read_json(pointer).get("business_date", ""))
        if not snapshot_date:
            return None
        now = self._parse_shanghai(now_iso)
        published = self._parse_shanghai(snapshot_date)
        if now is None or published is None:
            return None
        age = now - published
        if age.total_seconds() < 0 or age > timedelta(hours=max_age_hours):
            return None
        return snapshot_date, self.load_eligible(snapshot_date, platform)

    @staticmethod
    def _parse_shanghai(value: str) -> datetime | None:
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = (
                datetime.fromisoformat(text)
                if "T" in text or " " in text
                else datetime.fromisoformat(f"{text}T00:00:00")
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_SHANGHAI)
        return parsed.astimezone(_SHANGHAI)


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
        return self._load_bundle(self.user_dir(user_id), business_date)

    def load_news_user_bundle(
        self, user_id: str, business_date: BusinessDate
    ) -> RecommendationBundle | None:
        return self._load_bundle(self.news_user_dir(user_id), business_date)

    def load_latest_user_bundle(self, user_id: str) -> RecommendationBundle | None:
        return self._load_latest_bundle(self.user_dir(user_id))

    def load_latest_news_user_bundle(
        self, user_id: str
    ) -> RecommendationBundle | None:
        return self._load_latest_bundle(self.news_user_dir(user_id))

    def _load_bundle(
        self, parent: Path, business_date: BusinessDate
    ) -> RecommendationBundle | None:
        path = parent / _date_text(business_date) / "result.json"
        return _recommendation_bundle(self._read_json(path)) if path.is_file() else None

    def _load_latest_bundle(self, parent: Path) -> RecommendationBundle | None:
        if not parent.is_dir():
            return None
        for directory in sorted(
            (path for path in parent.iterdir() if path.is_dir() and ".tmp-" not in path.name),
            key=lambda path: path.name,
            reverse=True,
        ):
            bundle = self._load_bundle(parent, directory.name)
            if bundle is not None:
                return bundle
        return None

    def write_user_result_atomic(
        self,
        user_id: str,
        business_date: BusinessDate,
        writer: Callable[[Path], Any],
    ) -> Path:
        return self._write_result_atomic(
            self.user_dir(user_id), business_date, writer
        )

    def write_news_user_result_atomic(
        self,
        user_id: str,
        business_date: BusinessDate,
        writer: Callable[[Path], Any],
    ) -> Path:
        return self._write_result_atomic(
            self.news_user_dir(user_id), business_date, writer
        )

    def _write_result_atomic(
        self,
        parent: Path,
        business_date: BusinessDate,
        writer: Callable[[Path], Any],
    ) -> Path:
        day = _date_text(business_date)
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


def _item_detail_from_dict(data: Mapping[str, Any]) -> ItemDetail:
    return ItemDetail(
        item_id=str(data["item_id"]),
        content=str(data["content"]),
        content_status=data["content_status"],
        publication_time=data.get("publication_time"),
        collected_at=str(data["collected_at"]),
        source_url=str(data["source_url"]),
        fetch_status=str(data["fetch_status"]),
        metadata=dict(data.get("metadata") or {}),
    )


def _heat_evidence_from_dict(data: Mapping[str, Any]) -> HeatEvidence:
    return HeatEvidence(
        source_kind=data["source_kind"],
        platform_rank=data.get("platform_rank"),
        native_hot_value=data.get("native_hot_value"),
        metrics=dict(data.get("metrics", {})),
        threshold_metrics=dict(data.get("threshold_metrics", {})),
        qualified_by=tuple(data.get("qualified_by", ())),
    )


def _content_validation_from_dict(data: Mapping[str, Any]) -> ContentValidation:
    return ContentValidation(
        status=data["status"],
        parser=data["parser"],
        character_count=data["character_count"],
        paragraph_count=data["paragraph_count"],
        reasons=tuple(data.get("reasons", ())),
    )


def _qualified_article_from_dict(data: Mapping[str, Any]) -> QualifiedArticle:
    return QualifiedArticle(
        hot_item=_hot_item(data["hot_item"]),
        detail=_item_detail_from_dict(data["detail"]),
        heat_evidence=_heat_evidence_from_dict(data["heat_evidence"]),
        content_validation=_content_validation_from_dict(data["content_validation"]),
        platform_heat_score=data["platform_heat_score"],
    )


def _search_cache_record_from_dict(data: Mapping[str, Any]) -> SearchCacheRecord:
    return SearchCacheRecord(
        status=data["status"],
        business_date=data["business_date"],
        platform=data["platform"],
        normalized_keyword=data["normalized_keyword"],
        collected_at=data.get("collected_at", ""),
        articles=tuple(
            _qualified_article_from_dict(item) for item in data.get("articles", ())
        ),
        rejected=tuple(dict(item) for item in data.get("rejected", ())),
        retry_after=data.get("retry_after"),
    )
