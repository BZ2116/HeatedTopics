"""Map last30days Item dicts to V3 HotItem + ItemDetail.

# Field mapping reference (verified against last30days-skill-cn v3.2.0
# scripts/lib/schema.py + actual `--emit json` stdout output):
#
# last30days top-level JSON shape:
#   {
#     "topic": str,
#     "range": {"from": ISO-date, "to": ISO-date},
#     "generated_at": ISO-datetime,
#     "mode": str,
#     "<platform>": [Item, ...],   # one list per platform
#     "best_practices": [...],
#     "prompt_pack": [...]
#   }
#   Top-level platform keys (per schema.py): weibo, xiaohongshu, bilibili,
#   zhihu, douyin, wechat, baidu, toutiao. Each is a list of Item dicts.
#   (Not wrapped in a "results" array.)
#
# Per-platform Item shape (each has id, engagement, relevance, why_relevant,
# subs {relevance, recency, engagement}, score, cross_refs):
#
#   WeiboItem (top-level key "weibo"):
#     id, text, url, author_handle, author_id?, date?, date_confidence,
#     engagement {views, likes, comments, reposts, ...}
#
#   XiaohongshuItem (top-level key "xiaohongshu"):
#     id, title, desc, url, author_name, author_id?, date?, date_confidence,
#     engagement, hashtags
#
#   BilibiliItem (top-level key "bilibili"):
#     id, title, url, bvid, channel_name, author_mid?, date?, date_confidence,
#     engagement {views, danmaku, likes, ...}, description, duration?
#
#   ZhihuItem (top-level key "zhihu"):
#     id, title, excerpt, url, author, date?, date_confidence, content_type,
#     engagement {voteups, num_comments, collects, ...}
#
#   DouyinItem (top-level key "douyin"):
#     id, text, url, author_name, author_id?, date?, date_confidence,
#     engagement, hashtags, duration?
#
#   WechatItem (top-level key "wechat"):
#     id, title, summary, url, account_name, date?
#     (engagement shape varies; treated as pass-through)
#
#   BaiduItem (top-level key "baidu"):
#     id, title, abstract, snippet, url, source_domain?, source?, date?
#
#   ToutiaoItem (top-level key "toutiao"):
#     id, title, content?, abstract?, url, source?, date?, author?
#
# Notes:
# - last30days `--fetch-bodies` enables full body fetch where supported
#   (Weibo/Zhihu/Bilibili fully; XHS/Douyin need login = empty body;
#    WeChat/Baidu/Toutiao partial). Body absence is expected, not an error.
# - last30days per-item `score` is last30days's own weighted composite
#   (relevance 45 + recency 25 + engagement 30) — NOT used as V3 rank.
#   V3 rank comes from per-platform position in the result list.
# - V3 HotItem requires (item_id, platform, title, url, rank, heat, summary).
#   V3 ItemDetail requires (item_id, content, content_status,
#   publication_time, collected_at, source_url, fetch_status).
"""

from __future__ import annotations

from typing import Any, Callable