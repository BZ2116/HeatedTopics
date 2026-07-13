import json
from pathlib import Path
import httpx
from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.providers.juejin import JUEJIN_ARTICLE_DETAIL_URL, JUEJIN_HOT_RANK_URL, JuejinProvider

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-13T04:00:00Z"

def test_collect_hot_list_parses_rank_and_preserves_capture():
    raw = (FIXTURES / "juejin_hot_rank.json").read_text(encoding="utf-8")
    seen = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200, text=raw))[1]))
    capture = JuejinProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture) and capture.raw_text == raw
    assert str(seen[0].url) == JUEJIN_HOT_RANK_URL
    assert capture.items[0].heat.value == 4567

def test_detail_prefers_api_then_article_page_then_summary_then_title():
    item = JuejinProvider.parse_hot_list((FIXTURES / "juejin_hot_rank.json").read_text(), NOW)[0]
    calls = []
    def successful(request):
        calls.append(request)
        return httpx.Response(200, json={"err_no":0,"data":{"article_info":{"mark_content":"API body"}}})
    detail = JuejinProvider(httpx.Client(transport=httpx.MockTransport(successful))).fetch_detail(item, NOW)
    assert detail.content == "API body" and len(calls) == 1 and str(calls[0].url) == JUEJIN_ARTICLE_DETAIL_URL
    responses = iter([httpx.Response(200, json={"err_no":1}), httpx.Response(200, text="<article>Page body</article>")])
    detail = JuejinProvider(httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))).fetch_detail(item, NOW)
    assert detail.content == "Page body"
    responses = iter([httpx.Response(200, json={"err_no":1}), httpx.Response(200, text="<html></html>")])
    detail = JuejinProvider(httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))).fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.fetch_status == "partial"
