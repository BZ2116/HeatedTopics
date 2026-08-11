"""Best-effort full-body enrichment for last30days candidates."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx
from gne import GeneralNewsExtractor

from heated_topics_v3.content import extract_container_text, validate_full_text


def _platform_from_url(url: str, fallback: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    if "mp.weixin.qq.com" in host:
        return "wechat"
    if "zhuanlan.zhihu.com" in host or "zhihu.com" in host:
        return "zhihu"
    if "weibo.com" in host or "weibo.cn" in host:
        return "weibo"
    if "toutiao.com" in host:
        return "toutiao"
    if "bilibili.com" in host:
        return "bilibili"
    return fallback


def _extract_body(html: str, url: str, title: str, summary: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    if "weixin.qq.com" in host:
        selectors = ("#js_content", ".rich_media_content")
    elif "zhihu.com" in host:
        selectors = (".Post-RichTextContainer", ".RichText", "article")
    else:
        selectors = ("article", ".article-content", ".article__content")
    body = extract_container_text(html, selectors)
    if not body:
        try:
            payload = GeneralNewsExtractor().extract(html, title=title)
            body = str((payload or {}).get("content") or "").strip()
        except Exception:
            body = ""
    validation = validate_full_text(body, title, summary, parser="last30days_web")
    return body if validation.status == "accepted" else ""


def enrich_article(article: dict, *, client: httpx.Client | None = None) -> dict:
    """Fetch a real article page when the source only supplied a snippet."""
    current_body = str(article.get("body_text") or "").strip()
    if len("".join(current_body.split())) >= 120:
        return article
    url = str(article.get("url") or "").strip()
    if not url:
        return article
    own_client = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=20.0)
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if "zhihu.com" in (urlsplit(url).hostname or "") and os.getenv("ZHIHU_COOKIE"):
            headers["Cookie"] = os.environ["ZHIHU_COOKIE"]
        response = c.get(url, headers=headers)
        response.raise_for_status()
        final_url = str(response.url)
        if final_url != url:
            article["source_url"] = url
            article["url"] = final_url
            article["canonical_url"] = final_url
        body = _extract_body(response.text, final_url, str(article.get("title") or ""), str(article.get("summary") or ""))
        if body:
            article["body_text"] = body
            article["platform"] = _platform_from_url(final_url, str(article.get("platform") or ""))
            article["canonical_url"] = final_url
            article["body_fetch_status"] = "full_text:web"
        elif final_url != url:
            article["canonical_url"] = final_url
            article["platform"] = _platform_from_url(final_url, str(article.get("platform") or ""))
    except (httpx.HTTPError, ValueError):
        pass
    finally:
        if own_client:
            c.close()
    return article


__all__ = ["enrich_article"]
