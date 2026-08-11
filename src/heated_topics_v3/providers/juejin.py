"""Juejin rank and article detail provider."""
import json
import re
from datetime import datetime, timezone
import httpx
from heated_topics_v3.contracts import HeatMetrics, HotItem, ItemDetail
from .common import ProviderCapture, ProviderContractError, article_text, number_or_none

JUEJIN_HOT_RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
JUEJIN_ARTICLE_DETAIL_URL = "https://api.juejin.cn/content_api/v1/article/detail"

class JuejinProvider:
    def __init__(self, client: httpx.Client): self.client = client
    def collect_hot_list(self, collected_at: str) -> ProviderCapture:
        response = self.client.get(JUEJIN_HOT_RANK_URL)
        response.raise_for_status()
        raw = response.text
        return ProviderCapture(raw, ".json", self.parse_hot_list(raw, collected_at))
    def fetch_detail(self, item: HotItem, collected_at: str) -> ItemDetail:
        article_id = re.sub(r"^juejin_", "", item.item_id)
        content = ""
        method = "juejin_detail_api"
        try:
            payload = self.client.post(JUEJIN_ARTICLE_DETAIL_URL, json={"article_id": article_id}).json()
            data = payload.get("data") or {}
            info = data.get("article_info") or {}
            content = str(info.get("mark_content") or info.get("content") or "").strip()
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            pass
        if not content:
            method = "juejin_article_page"
            try:
                content = article_text(self.client.get(item.url).text)
            except httpx.HTTPError:
                content = ""
        if not content: content, method = (item.summary or item.title), ("source_summary" if item.summary else "title")
        status = "full_text" if method in {"juejin_detail_api", "juejin_article_page"} else ("summary" if method == "source_summary" else "title_only")
        return ItemDetail(item.item_id, content, status, item.publication_time, collected_at, item.url, "success" if status == "full_text" else "partial")
    @staticmethod
    def parse_hot_list(raw: str, collected_at: str) -> tuple[HotItem, ...]:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ProviderContractError("juejin hot-rank response must be an object")
        rows = payload.get("data")
        if payload.get("err_no") != 0 or not isinstance(rows, list) or not rows:
            raise ProviderContractError("invalid juejin hot-rank response")
        items = []
        for rank, row in enumerate(rows, 1):
            content, counter = row.get("content") or {}, row.get("content_counter") or {}
            cid, title = str(content.get("content_id") or ""), str(content.get("title") or "").strip()
            if not cid or not title: continue
            value = number_or_none(counter.get("hot_rank"))
            metric_fields = (("views", "view"), ("likes", "like"), ("collects", "collect"), ("comments", "comment_count"), ("interactions", "interact_count"))
            metrics = {name: parsed for name, field in metric_fields if (parsed := number_or_none(counter.get(field))) is not None}
            pub = content.get("ctime"); publication = datetime.fromtimestamp(int(pub), timezone.utc).isoformat().replace("+00:00", "Z") if pub else None
            items.append(HotItem(f"juejin_{cid}", "juejin", title, f"https://juejin.cn/post/{cid}", rank, HeatMetrics(value, "" if value is None else str(value), "hot_rank", metrics), str(content.get("brief") or title), publication, collected_at, row))
        if not items:
            raise ProviderContractError("juejin hot rank contained no valid items")
        return tuple(items)
