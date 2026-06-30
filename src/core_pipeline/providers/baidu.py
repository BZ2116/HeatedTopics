import html
import re
import urllib.parse
import urllib.request

from src.core_pipeline.types import DetailEvidence, HotRecord


BAIDU_SEARCH_URL = "https://www.baidu.com/s"


def detail_queries_for_title(title: str) -> list[str]:
    clean_title = str(title).strip()
    if not clean_title:
        return []
    return [
        clean_title,
        f"{clean_title} 怎么回事",
        f"{clean_title} 最新进展",
    ]


def parse_baidu_search_html(page_html: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.findall(
        r'<div[^>]+(?:class|tpl)="[^"]*(?:result|c-container)[^"]*"[^>]*>.*?(?=<div[^>]+(?:class|tpl)="[^"]*(?:result|c-container)[^"]*"|</body>|$)',
        page_html,
        flags=re.S | re.I,
    )
    if not blocks:
        blocks = re.findall(r"<h3\b.*?</h3>.*?(?=<h3\b|</body>|$)", page_html, flags=re.S | re.I)
    for block in blocks:
        title = _first_text(block, r"<h3\b[^>]*>.*?<a\b[^>]*>(.*?)</a>.*?</h3>")
        if not title:
            title = _first_text(block, r"<a\b[^>]*>(.*?)</a>")
        snippet = _first_text(block, r'<div\b[^>]*class="[^"]*(?:c-abstract|c-span-last|content-right|c-color-text)[^"]*"[^>]*>(.*?)</div>')
        if not snippet:
            snippet = _block_text_without_title(block, title)
        url = _first_attr(block, r"<h3\b[^>]*>.*?<a\b[^>]*href=\"([^\"]+)\"")
        if not url:
            url = _first_attr(block, r"<a\b[^>]*href=\"([^\"]+)\"")
        if title or snippet:
            results.append({"title": title, "snippet": snippet, "url": url})
    return results[:10]


def search_baidu_details(query: str, timeout_seconds: int = 15) -> list[dict[str, str]]:
    url = f"{BAIDU_SEARCH_URL}?{urllib.parse.urlencode({'wd': query})}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 heatedTopics/0.1",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page_html = response.read().decode(charset, errors="replace")
    results = parse_baidu_search_html(page_html)
    if results:
        return results
    if "百度安全验证" in page_html or "wappass.baidu.com" in page_html:
        return search_baidu_details_with_browser(query, timeout_seconds * 1000)
    return results


def search_baidu_details_with_browser(query: str, timeout_ms: int = 20000) -> list[dict[str, str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required when Baidu requires browser verification") from exc

    url = f"{BAIDU_SEARCH_URL}?{urllib.parse.urlencode({'wd': query})}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2500)
        rows = page.locator(".result, .c-container").evaluate_all(
            """
            elements => elements.slice(0, 10).map(element => {
              const titleNode = element.querySelector('h3 a, a');
              const title = titleNode ? titleNode.innerText.trim() : '';
              const href = titleNode ? titleNode.href : '';
              const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
              const snippet = title && text.startsWith(title) ? text.slice(title.length).trim() : text;
              return { title, snippet, url: href };
            }).filter(row => (row.title || row.snippet) && row.snippet.length > 10)
            """
        )
        context.close()
        browser.close()
    return [
        {
            "title": str(row.get("title", "")),
            "snippet": str(row.get("snippet", "")),
            "url": str(row.get("url", "")),
        }
        for row in rows
    ]


def _first_text(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S | re.I)
    if not match:
        return ""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", match.group(1))
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_attr(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S | re.I)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _block_text_without_title(block: str, title: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", block)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if title and text.startswith(title):
        text = text[len(title) :].strip()
    return text[:300]


def collect_baidu_detail(
    record: HotRecord,
    fetched_at: str,
    search_results: list[dict[str, str]],
    content_pages: list[dict[str, object]] | None = None,
) -> DetailEvidence:
    content_pages = content_pages or []
    usable_results = [row for row in search_results if row.get("title") or row.get("snippet")]
    status = "ok" if usable_results else "empty_content"
    content_parts = []
    result_urls = []
    for row in usable_results[:5]:
        title = row.get("title", "").strip()
        snippet = row.get("snippet", "").strip()
        url = row.get("url", "").strip()
        if url:
            result_urls.append(url)
        content_parts.append(f"{title}\n{snippet}".strip())
    for page in content_pages:
        page_title = str(page.get("title", "")).strip()
        page_content = str(page.get("content", "")).strip()
        if page_content:
            content_parts.append(f"{page_title}\n{page_content}".strip())
    content = "\n\n".join(part for part in content_parts if part)
    return DetailEvidence(
        evidence_id=f"evidence_baidu_{record.id}",
        topic_key=record.title,
        related_hot_record_ids=[record.id],
        platform="baidu",
        source_role="required",
        source_method="search_results",
        query=record.title,
        url=record.url,
        title=f"百度搜索详情：{record.title}",
        content=content,
        author="",
        published_at="",
        metrics={"search_results": len(search_results), "content_pages": len(content_pages)},
        comments_preview=[],
        result_urls=result_urls,
        raw_snapshot_path="",
        screenshot_path="",
        fetched_at=fetched_at,
        fetch_status=status,
        error_type=None if status == "ok" else status,
        confidence="medium" if status == "ok" else "low",
        raw_payload={"search_results": search_results, "content_pages": content_pages},
    )
