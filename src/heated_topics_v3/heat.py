"""Dynamic heat floors and stable per-platform ranking."""

from __future__ import annotations

from dataclasses import replace
from math import log1p
from typing import Iterable, Mapping, Sequence

from .contracts import QualifiedArticle


def positive_percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values if float(value) > 0)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def dynamic_floors(
    board_metrics: Iterable[Mapping[str, float]],
    absolute_floors: Mapping[str, float],
) -> dict[str, float]:
    rows = tuple(board_metrics)
    result: dict[str, float] = {}
    for metric, fallback in absolute_floors.items():
        calculated = positive_percentile(
            (row.get(metric, 0.0) for row in rows),
            0.25,
        )
        result[metric] = float(fallback if calculated is None else calculated)
    return result


def qualifies_public_metrics(
    metrics: Mapping[str, float],
    floors: Mapping[str, float],
) -> tuple[str, ...]:
    return tuple(
        metric
        for metric, floor in floors.items()
        if float(metrics.get(metric, 0.0)) >= float(floor)
    )


def _percentiles(values: Sequence[float]) -> tuple[float, ...]:
    transformed = [log1p(max(0.0, value)) for value in values]
    ordered = sorted(set(transformed))
    if len(ordered) <= 1:
        return tuple(1.0 if value > 0 else 0.0 for value in transformed)
    return tuple(
        0.0 if value == 0 else ordered.index(value) / (len(ordered) - 1)
        for value in transformed
    )


def rank_platform_articles(
    articles: Sequence[QualifiedArticle],
    weights: Mapping[str, float],
) -> tuple[QualifiedArticle, ...]:
    items = tuple(articles)
    metric_percentiles = {
        metric: _percentiles(
            tuple(float(item.heat_evidence.metrics.get(metric, 0.0)) for item in items)
        )
        for metric in weights
    }
    scored = tuple(
        replace(
            item,
            platform_heat_score=sum(
                weight * metric_percentiles[metric][index]
                for metric, weight in weights.items()
            ),
        )
        for index, item in enumerate(items)
    )
    ordered = sorted(scored, key=lambda item: item.hot_item.item_id)
    ordered.sort(
        key=lambda item: item.hot_item.publication_time or "",
        reverse=True,
    )
    ordered.sort(key=lambda item: item.heat_evidence.platform_rank or 10**9)
    ordered.sort(
        key=lambda item: item.heat_evidence.source_kind != "official_hot_board"
    )
    ordered.sort(
        key=lambda item: len(tuple(
            value
            for value in item.heat_evidence.metrics.values()
            if value > 0
        )),
        reverse=True,
    )
    ordered.sort(key=lambda item: item.platform_heat_score, reverse=True)
    return tuple(ordered)
