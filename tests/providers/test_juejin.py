import json
from dataclasses import replace
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
    assert capture.items[1].heat.metrics == {"views": 80}

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

def test_detail_posts_content_id_and_falls_back_after_non_json_api():
    item = JuejinProvider.parse_hot_list((FIXTURES / "juejin_hot_rank.json").read_text(), NOW)[0]
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, text="not json")
        return httpx.Response(200, text="<article>Recovered page</article>")
    detail = JuejinProvider(httpx.Client(transport=httpx.MockTransport(handler))).fetch_detail(item, NOW)
    assert json.loads(requests[0].content) == {"article_id": "301"}
    assert detail.content == "Recovered page"

def test_detail_falls_back_after_api_network_error_and_bad_json_shape():
    item = JuejinProvider.parse_hot_list((FIXTURES / "juejin_hot_rank.json").read_text(), NOW)[0]
    for first_result in (httpx.ConnectError("offline"), httpx.Response(200, json=[])):
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                if isinstance(first_result, Exception): raise first_result
                return first_result
            return httpx.Response(200, text="<article>Fallback</article>")
        assert JuejinProvider(httpx.Client(transport=httpx.MockTransport(handler))).fetch_detail(item, NOW).content == "Fallback"

def test_detail_uses_title_when_api_page_and_summary_are_empty():
    item = replace(JuejinProvider.parse_hot_list((FIXTURES / "juejin_hot_rank.json").read_text(), NOW)[0], summary="")
    responses = iter([httpx.Response(200, json={"err_no": 1}), httpx.Response(200, text="")])
    detail = JuejinProvider(httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))).fetch_detail(item, NOW)
    assert detail.content == item.title and detail.content_status == "title_only"

def test_detail_uses_summary_when_api_and_page_requests_fail():
    item = JuejinProvider.parse_hot_list((FIXTURES / "juejin_hot_rank.json").read_text(), NOW)[0]
    provider = JuejinProvider(httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline")))))
    detail = provider.fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.content_status == "summary"
