from __future__ import annotations

import httpx

from heated_topics_v3.openbiliclaw_integration.body_enricher import enrich_article


def test_enricher_extracts_wechat_body_and_canonical_platform() -> None:
    body = "这是微信公众号的正文内容。" * 20

    def handler(request: httpx.Request) -> httpx.Response:
        if "baidu.com" in str(request.url):
            return httpx.Response(302, headers={"location": "https://mp.weixin.qq.com/s/abc"})
        return httpx.Response(200, text=f'<html><div id="js_content"><p>{body}</p></div></html>')

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    result = enrich_article(
        {"title": "非遗文章", "summary": "摘要", "body_text": "摘要", "url": "https://baidu.com/link", "platform": "baidu"},
        client=client,
    )
    assert result["platform"] == "wechat"
    assert result["url"] == "https://mp.weixin.qq.com/s/abc"
    assert result["source_url"] == "https://baidu.com/link"
    assert len(result["body_text"]) > 100
