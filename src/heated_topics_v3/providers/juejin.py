"""Juejin rank and article detail provider."""
import json
import re
from datetime import datetime, timezone
import httpx
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture
from .toutiao import _article_text, _number

JUEJIN_HOT_RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
JUEJIN_ARTICLE_DETAIL_URL = "https://api.juejin.cn/content_api/v1/article/detail"

class JuejinProvider:
    def __init__(self, client: httpx.Client): self.client = client
    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        raw = self.client.get(JUEJIN_HOT_RANK_URL).text
        return ProviderCapture(raw, ".json", self.parse_hot_list(raw, collected_at))
    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        article_id = re.sub(r"^juejin_", "", item.item_id)
        response = self.client.post(JUEJIN_ARTICLE_DETAIL_URL, json={"article_id": article_id})
        payload = response.json(); data = payload.get("data") or {}; info = data.get("article_info") or {}
        content = str(info.get("mark_content") or info.get("content") or "").strip()
        method = "juejin_detail_api"
        if not content:
            content, method = _article_text(self.client.get(item.url).text), "juejin_article_page"
        if not content: content, method = (item.summary or item.title), ("source_summary" if item.summary else "title")
        status = "full_text" if method in {"juejin_detail_api", "juejin_article_page"} else ("summary" if method == "source_summary" else "title_only")
        return ItemDetail(item.item_id, content, status, item.publication_time, collected_at, item.url, "success" if status == "full_text" else "partial")
    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        items = []
        for rank, row in enumerate(json.loads(raw).get("data", []), 1):
            content, counter = row.get("content") or {}, row.get("content_counter") or {}
            cid, title = str(content.get("content_id") or ""), str(content.get("title") or "").strip()
            if not cid or not title: continue
            value = _number(counter.get("hot_rank")); metrics = {"views": _number(counter.get("view")) or 0, "likes": _number(counter.get("like")) or 0, "collects": _number(counter.get("collect")) or 0, "comments": _number(counter.get("comment_count")) or 0, "interactions": _number(counter.get("interact_count")) or 0}
            pub = content.get("ctime"); publication = datetime.fromtimestamp(int(pub), timezone.utc).isoformat().replace("+00:00", "Z") if pub else None
            items.append(HotItem(f"juejin_{cid}", "juejin", title, f"https://juejin.cn/post/{cid}", rank, HeatMetrics(value, "" if value is None else str(value), "hot_rank", metrics), str(content.get("brief") or title), publication, collected_at, row))
        return tuple(items)
