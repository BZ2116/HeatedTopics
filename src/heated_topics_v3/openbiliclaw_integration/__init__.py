"""OpenBiliClaw multi-user hot-article recommender integration.

Bridges V3 providers (juejin / baidu_hot / zhihu_hot / zhihu_daily / toutiao)
to OpenBiliClaw's RecommendationEngine, accepting multiple user profiles
as JSON input and producing per-user top-N recommendations as JSON output.
"""

__all__ = [
    "candidate_adapter",
    "cli",
    "exceptions",
    "llm_refilter",
    "output",
    "recommender",
    "runtime",
    "user_profile",
]
