import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from heated_topics_v3.providers.common import ProviderCapture
from heated_topics_v3.providers.toutiao import (
    TOUTIAO_HOT_BOARD_URL,
    TOUTIAO_SEARCH_URL,
    TOUTIAO_ARTICLE_EVALUATION_SCRIPT,
    PlaywrightArticleRenderer,
    ToutiaoProvider,
    _trending_block_text,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = "2026-07-13T04:00:00Z"


def test_rendered_article_javascript_keeps_join_newlines_escaped():
    assert "texts.join('\\n\\n')" in TOUTIAO_ARTICLE_EVALUATION_SCRIPT
    assert "texts.join('\n\n')" not in TOUTIAO_ARTICLE_EVALUATION_SCRIPT


def test_rendered_article_javascript_never_falls_back_to_document_body():
    assert "document.body" not in TOUTIAO_ARTICLE_EVALUATION_SCRIPT


@pytest.mark.parametrize("operation", ["board", "search"])
def test_board_and_search_raise_for_http_errors(operation):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": "unavailable"})
        )
    )
    provider = ToutiaoProvider(client)

    with pytest.raises(httpx.HTTPStatusError):
        if operation == "board":
            provider.collect_hot_list(NOW)
        else:
            provider.search("AI", NOW)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "failure", "data": []},
        {"status": "success", "data": []},
    ],
)
def test_hot_board_rejects_malformed_error_and_empty_payloads(payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(ValueError):
        ToutiaoProvider(client).collect_hot_list(NOW)


@pytest.mark.parametrize("payload", [{}, {"status": "failure", "count": 0, "dom": ""}])
def test_search_rejects_malformed_and_api_error_payloads(payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(ValueError):
        ToutiaoProvider(client).search("AI", NOW)


@pytest.mark.parametrize("dom", ["", " \n\t"])
def test_search_accepts_explicit_zero_count_with_blank_dom_as_genuine_empty_result(dom):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"count": 0, "dom": dom})
        )
    )

    capture = ToutiaoProvider(client).search("no-such-current-topic", NOW)

    assert capture.items == ()


def test_search_rejects_zero_count_when_dom_is_not_empty():
    raw = json.dumps(
        {
            "count": 0,
            "dom": '<article data-group-id="9001"><h2>Unexpected card</h2></article>',
        }
    )

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(raw, NOW)


@pytest.mark.parametrize("count", [False, 0.0, "0", None])
def test_search_rejects_legacy_empty_data_without_strict_integer_zero_count(count):
    payload = {"data": []}
    if count is not None:
        payload["count"] = count

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(json.dumps(payload), NOW)


def test_search_rejects_nonempty_legacy_data_when_every_row_is_malformed():
    raw = json.dumps({"data": [{"unexpected": "shape"}]})

    with pytest.raises(ValueError):
        ToutiaoProvider.parse_search(raw, NOW)


def test_search_accepts_structurally_valid_legacy_rows_all_filtered_by_age():
    raw = json.dumps(
        {
            "data": [
                {
                    "id": "old-1",
                    "title": "Old but valid",
                    "url": "https://www.toutiao.com/article/old-1/",
                    "publish_time": "2026-07-10T03:00:00Z",
                }
            ]
        }
    )

    assert ToutiaoProvider.parse_search(raw, NOW) == ()

def test_collect_hot_list_preserves_raw_text_and_parses_heat():
    raw = (FIXTURES / "toutiao_hot_board.json").read_text(encoding="utf-8")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=raw)))
    capture = ToutiaoProvider(client).collect_hot_list(NOW)
    assert isinstance(capture, ProviderCapture)
    assert capture.raw_text == raw and capture.raw_suffix == ".json"
    assert capture.items[0].heat.value == 98765
    assert capture.items[1].heat.value is None
    assert client.get(TOUTIAO_HOT_BOARD_URL).status_code == 200

def test_search_uses_exactly_one_keyword_and_parses_current_dom_cards():
    payload = json.loads((FIXTURES / "toutiao_search.json").read_text(encoding="utf-8"))
    payload["count"] = 777
    raw = json.dumps(payload)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=raw)
    capture = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(handler))).search("AI Agent", NOW)
    assert len(requests) == 1 and str(requests[0].url).startswith(TOUTIAO_SEARCH_URL)
    assert dict(requests[0].url.params) == {
        "keyword": "AI Agent",
        "pd": "information",
        "source": "search_subtab_switch",
        "from": "information",
        "format": "json",
        "count": "10",
        "offset": "0",
    }
    assert [item.item_id for item in capture.items] == [
        "toutiao_7661817657498305030",
        "toutiao_7661826133797487147",
    ]
    assert capture.items[0].title == "OpenAI 挖了苹果 400 人，到底在下一盘什么棋？"
    assert capture.items[0].url == "https://www.toutiao.com/group/7661817657498305030/"
    assert capture.items[0].summary.startswith("苹果与OpenAI的商业机密诉讼案")
    assert capture.items[0].publication_time == "1783905943"
    assert capture.items[0].raw_payload["group_id"] == "7661817657498305030"
    assert capture.items[0].raw_payload["source"] == "人人都是产品经理"
    for rank, item in enumerate(capture.items, 1):
        assert item.heat.metric_name == "search_rank"
        assert item.heat.value == rank
        assert item.heat.metrics == {"search_rank": rank}
        assert item.heat.value != payload["count"]


def test_search_dom_void_elements_do_not_leak_title_summary_or_source_scopes():
    raw = json.dumps({"count": 999, "dom": """
        <article data-group-id="9001">
          <a href="https://toutiao.com/group/9001/"><h2>Title<img src="cover.jpg"></h2></a>
          <p>Summary<br>continued</p>
          <footer><span class="source">Source<img src="avatar.jpg"></span><time datetime="1783905943">recent</time></footer>
        </article>
    """})
    item = ToutiaoProvider.parse_search(raw, NOW)[0]
    assert item.title == "Title"
    assert item.summary == "Summary continued"
    assert item.raw_payload["source"] == "Source"
    assert item.publication_time == "1783905943"


def test_search_keeps_legacy_data_rows_as_compatibility_fallback():
    raw = json.dumps({"count": 99, "data": [
        {"id": "201", "title": "Fresh agent story", "url": "https://www.toutiao.com/article/201/", "abstract": "Fresh summary", "publish_time": "2026-07-13T03:00:00Z", "read_count": 1200, "comment_count": 34},
        {"id": "202", "title": "Old agent story", "url": "https://www.toutiao.com/article/202/", "abstract": "Old summary", "publish_time": "2026-07-10T03:00:00Z"},
    ]})
    items = ToutiaoProvider.parse_search(raw, NOW)
    assert [item.item_id for item in items] == ["toutiao_201"]
    assert items[0].heat.metric_name == "engagement"
    assert items[0].heat.metrics == {"reads": 1200, "comments": 34}

def test_fetch_detail_fallback_order():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    rendered = "Rendered article body with enough context to be meaningful. " * 3 + "\nSecond paragraph with supporting detail. " * 3
    provider = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))), rendered_fetcher=lambda url: rendered)
    assert provider.fetch_detail(item, NOW).fetch_status == "success"
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: "",
    )
    detail = provider.fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.fetch_status.startswith("partial")


def test_default_provider_has_anonymous_rendered_detail_path():
    provider = ToutiaoProvider(httpx.Client())

    assert provider.rendered_fetcher is not None

    provider.close()


def test_fetch_detail_prefers_meaningful_multiline_rendered_body_over_summary():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    rendered = "第一段正文，包含足够多的事实信息和上下文。" * 4 + "\n" + "第二段正文，继续解释事件经过与影响。" * 4
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: rendered,
    )

    detail = provider.fetch_detail(item, NOW)

    assert detail.content == rendered
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"


def test_short_or_navigation_only_rendered_text_does_not_claim_full_text():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: "首页\n关注\n登录\n评论\n分享",
    )

    detail = provider.fetch_detail(item, NOW)

    assert detail.content == item.summary
    assert detail.content_status == "summary"
    assert detail.fetch_status.startswith("partial")


def test_title_plus_long_login_comment_and_footer_chrome_is_not_full_text():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    chrome = "\n".join(
        [item.title]
        + ["请先登录后发表评论～", "打开APP查看更多内容", "网友讨论", "查看全部 99 条回复"] * 12
    )
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: chrome,
    )

    detail = provider.fetch_detail(item, NOW)

    assert detail.content == item.summary
    assert detail.content_status == "summary"
    assert detail.fetch_status == "partial:RenderedContentTooShort"


def test_reviewer_exact_long_single_line_app_prompt_is_not_full_text():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    prompt = "打开今日头条查看更多精彩内容，登录后关注作者并参与评论。"
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: f"{item.title}\n{prompt * 8}",
    )

    detail = provider.fetch_detail(item, NOW)

    assert detail.content == item.summary
    assert detail.content_status == "summary"
    assert detail.fetch_status == "partial:RenderedContentTooShort"


def test_article_may_mention_login_and_comment_once_without_being_rejected():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    body = (
        "报道介绍了平台治理的新规则，用户登录后可以参与评论，但这只是事件背景的一部分。"
        "监管部门同时公布了实施时间、适用范围和申诉流程，相关企业随后确认将按期调整产品。"
        "记者核对了公开文件与多方回应，正文包含具体事实而不是页面操作提示。"
        "\n"
        "第二段继续说明政策影响、行业反馈与后续安排，并列出了可核对的数据和消息来源。"
        "受访机构表示会持续公开执行进度，避免规则变化影响普通用户正常使用服务。"
    )
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: body,
    )

    detail = provider.fetch_detail(item, NOW)

    assert detail.content == body
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"


def test_two_line_300_character_article_remains_full_text():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    body = "第一段提供可核对的事件背景、时间、参与者以及事实经过。" * 7 + "\n" + "第二段继续说明事件影响、后续进展和来源信息。" * 7
    provider = ToutiaoProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))),
        rendered_fetcher=lambda url: body,
    )

    detail = provider.fetch_detail(item, NOW)

    assert len(detail.content) >= 300
    assert detail.content_status == "full_text"
    assert detail.fetch_status == "success"


def test_provider_close_releases_renderer_once():
    class Renderer:
        def __init__(self):
            self.closed = 0

        def fetch(self, url):
            return ""

        def close(self):
            self.closed += 1

    renderer = Renderer()
    provider = ToutiaoProvider(httpx.Client(), renderer=renderer)

    provider.close()
    provider.close()

    assert renderer.closed == 1


def test_shared_renderer_initializes_once_and_caps_concurrent_pages_at_three():
    class InMemoryRenderer(PlaywrightArticleRenderer):
        def __init__(self):
            super().__init__(timeout_seconds=2, max_concurrency=3)
            self.initialize_calls = 0
            self.active = 0
            self.maximum_active = 0

        async def _initialize(self):
            self.initialize_calls += 1
            await asyncio.sleep(0.02)
            self._semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _fetch(self, url):
            async with self._semaphore:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
                return url

    renderer = InMemoryRenderer()
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(renderer.fetch, (str(index) for index in range(6))))
    renderer.close()

    assert results == [str(index) for index in range(6)]
    assert renderer.initialize_calls == 1
    assert renderer.maximum_active == 3


def test_trending_renderer_follows_event_detail_article_before_extracting_body():
    body = "第一段完整正文，包含事件背景、事实和上下文。" * 5 + "\n" + "第二段完整正文，包含后续影响和信息来源。" * 5

    class Page:
        def __init__(self):
            self.urls = []
            self.evaluate_calls = 0

        async def goto(self, url, **kwargs):
            self.urls.append(url)

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def evaluate(self, script):
            self.evaluate_calls += 1
            if self.evaluate_calls == 1:
                return {"text": "事件详情\n短标题", "detail_url": "/article/123456/"}
            return {"text": body, "detail_url": ""}

        async def close(self):
            return None

    class Context:
        def __init__(self, page):
            self.page = page

        async def new_page(self):
            return self.page

    renderer = PlaywrightArticleRenderer()
    page = Page()
    renderer._context = Context(page)
    renderer._semaphore = asyncio.Semaphore(3)

    result = asyncio.run(renderer._fetch("https://www.toutiao.com/trending/999/"))

    assert page.urls == [
        "https://www.toutiao.com/trending/999/",
        "https://www.toutiao.com/article/123456/",
    ]
    assert result == body


def test_trending_renderer_uses_marker_bounded_event_and_related_blocks_without_article():
    event = "事件视频说明了发生时间、地点和主要经过。" * 4
    related = "相关报道补充了当事人回应、现场情况和后续处置。" * 5

    class Page:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def evaluate(self, script):
            return {
                "text": "",
                "detail_url": "",
                "blocks": [
                    {"title": "事件详情", "text": event},
                    {"title": "相关内容", "text": related},
                    {"title": "网友讨论", "text": "评论区内容" * 100},
                    {"title": "头条热榜", "text": "其他热搜" * 100},
                ],
            }

        async def close(self):
            return None

    class Context:
        async def new_page(self):
            return Page()

    renderer = PlaywrightArticleRenderer()
    renderer._context = Context()
    renderer._semaphore = asyncio.Semaphore(3)

    result = asyncio.run(renderer._fetch("https://www.toutiao.com/trending/999/"))

    assert "事件详情" in result and event in result
    assert "相关内容" in result and related in result
    assert "网友讨论" not in result
    assert "评论区内容" not in result
    assert "头条热榜" not in result
    assert "其他热搜" not in result


def test_trending_renderer_waits_for_lazy_related_block_before_snapshot():
    related = "稍后加载的相关报道包含事件经过、官方回应、数据和后续安排。" * 8

    class Page:
        def __init__(self):
            self.related_ready = False

        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_selector(self, selector, **kwargs):
            if ".topic-related-list-wrapper" in selector:
                self.related_ready = True

        async def evaluate(self, script):
            blocks = [{"title": "事件详情", "text": "短事件卡片"}]
            if self.related_ready:
                blocks.append({"title": "相关内容", "text": related})
            return {"text": "", "detail_url": "", "blocks": blocks}

        async def close(self):
            return None

    page = Page()

    class Context:
        async def new_page(self):
            return page

    renderer = PlaywrightArticleRenderer()
    renderer._context = Context()
    renderer._semaphore = asyncio.Semaphore(3)

    result = asyncio.run(renderer._fetch("https://www.toutiao.com/trending/999/"))

    assert page.related_ready
    assert related in result


@pytest.mark.parametrize(
    "blocks",
    [
        [{"title": "其他区域", "text": "无语义边界的长文本" * 30}],
        [{"title": "网友讨论", "text": "请先登录后发表评论" * 30}],
        [
            {"title": "事件详情", "text": "登录\n评论\n分享"},
            {"title": "网友讨论", "text": "评论内容" * 30},
        ],
    ],
)
def test_trending_blocks_without_meaningful_bounded_content_stay_empty_or_short(blocks):
    result = _trending_block_text(blocks)

    assert len(result) < 120


def test_trending_block_boundary_stops_before_hot_list_even_without_discussion_block():
    result = _trending_block_text(
        [
            {"title": "事件详情", "text": "事件解释" * 30},
            {"title": "相关内容", "text": "相关报道" * 30},
            {"title": "头条热榜", "text": "不相关热搜" * 50},
            {"title": "推荐", "text": "不相关推荐" * 50},
        ]
    )

    assert "事件解释" in result and "相关报道" in result
    assert "头条热榜" not in result and "不相关热搜" not in result
    assert "推荐" not in result and "不相关推荐" not in result

def test_search_treats_malformed_publication_time_as_undated():
    raw = json.dumps({"data": [{"id": "bad-date", "title": "Still useful", "url": "https://www.toutiao.com/article/204/", "publish_time": "not-a-date"}]})
    item = ToutiaoProvider.parse_search(raw, NOW)[0]
    assert item.title == "Still useful" and item.publication_time is None

def test_fetch_detail_uses_title_when_summary_and_pages_are_empty():
    item = replace(ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0], summary="")
    provider = ToutiaoProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=""))), rendered_fetcher=lambda url: "")
    detail = provider.fetch_detail(item, NOW)
    assert detail.content == item.title and detail.content_status == "title_only"

def test_fetch_detail_continues_to_rendered_after_static_fetch_exception():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    rendered = "Rendered recovery with substantial article context. " * 4 + "\nSupporting paragraph with more facts. " * 4
    detail = ToutiaoProvider(client, rendered_fetcher=lambda url: rendered).fetch_detail(item, NOW)
    assert detail.content.startswith("Rendered recovery")
    assert "\nSupporting paragraph" in detail.content
    assert detail.content_status == "full_text"

def test_fetch_detail_continues_to_summary_after_rendered_exception():
    item = ToutiaoProvider.parse_hot_list((FIXTURES / "toutiao_hot_board.json").read_text(), NOW)[0]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="")))
    def failed_render(url):
        raise RuntimeError("browser unavailable")
    detail = ToutiaoProvider(client, rendered_fetcher=failed_render).fetch_detail(item, NOW)
    assert detail.content == item.summary and detail.content_status == "summary"

def test_search_interprets_naive_timestamps_as_asia_shanghai_for_24_hour_filter():
    raw = json.dumps({"data": [
        {"id": "inside", "title": "Inside", "url": "https://www.toutiao.com/article/301/", "publish_time": "2026-07-12T12:01:00"},
        {"id": "outside", "title": "Outside", "url": "https://www.toutiao.com/article/302/", "publish_time": "2026-07-12T11:59:00"},
    ]})
    items = ToutiaoProvider.parse_search(raw, NOW)
    assert [item.item_id for item in items] == ["toutiao_inside"]
