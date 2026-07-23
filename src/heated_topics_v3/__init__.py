"""Toutiao and Juejin hot-topic collection and recommendation package."""

from .collection import collect_news_daily, collect_v1_daily
from .recommendation import generate_news_user_result, generate_v1_user_result

__all__ = [
    "collect_news_daily",
    "collect_v1_daily",
    "generate_news_user_result",
    "generate_v1_user_result",
]
