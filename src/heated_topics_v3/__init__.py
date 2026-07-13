"""Toutiao and Juejin hot-topic collection and recommendation package."""

from .collection import collect_v1_daily
from .recommendation import generate_v1_user_result

__all__ = ["collect_v1_daily", "generate_v1_user_result"]
