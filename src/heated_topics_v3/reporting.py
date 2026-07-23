from typing import Any

from heated_topics_v3.contracts import ItemDetail, MatchResult, PersonaProfile, UserProfile
from heated_topics_v3.llm_keywords import PersonaKeywordExtraction
from heated_topics_v3.toutiao_paths import Candidate


def render_juejin_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    return _render_platform_report("Juejin Hot Topics Report", profile, matches, fetched_at, item_details)


def render_baidu_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    body = _render_platform_report("Baidu 热搜日报", profile, matches, fetched_at, item_details)
    if not matches:
        # Design spec: empty Baidu run must surface a dedicated notice so a
        # human reader does not mistake a quiet board for a healthy run.
        notice = "<h3>本次未抓到任何条目</h3>"
        return body.replace("No matched hot topics.", notice)
    return body


def render_toutiao_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    return _render_platform_report("Toutiao Hot Topics Report", profile, matches, fetched_at, item_details)


def _render_platform_report(
    title: str,
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    details_by_item_id = {detail.item_id: detail for detail in item_details or []}
    lines = [
        f"# {title}",
        "",
        f"- Profile: {profile.display_name} (`{profile.profile_id}`)",
        f"- Fetched at: {fetched_at}",
        f"- Matches: {len(matches)}",
        "",
        "## Matched Topics",
        "",
    ]
    if not matches:
        lines.append("No matched hot topics.")
        return "\n".join(lines) + "\n"

    for index, match in enumerate(matches, start=1):
        item = match.item
        detail = details_by_item_id.get(item.item_id)
        lines.extend(
            [
                f"### {index}. {item.title}",
                "",
                f"- Rank: {item.rank}",
                f"- Heat: {item.heat.value} ({item.heat.metric_name})",
                f"- Source: {item.raw_payload.get('source_kind', item.platform)}",
                f"- Heat signal: {item.raw_payload.get('heat_signal_strength', item.heat.metric_name)}",
                f"- Score: {match.relevance_score}",
                f"- Match terms: {', '.join(match.match_terms)}",
                f"- Detail status: {_detail_status(detail)}",
                "",
            ]
        )
    return "\n".join(lines)


def _detail_status(detail: ItemDetail | None) -> str:
    if detail is None:
        return "not fetched"
    if detail.fetch_status != "success":
        return detail.fetch_status
    return f"{detail.extraction_method}, {len(detail.content)} chars"


def render_bilibili_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
    cache_stats: "BaiduCacheStats | None" = None,
) -> str:
    body = _render_platform_report("B站专栏日报", profile, matches, fetched_at, item_details)
    if cache_stats is not None:
        section = _render_cache_stats_section(cache_stats)
        marker = "## Matched Topics"
        body = body.replace(marker, section + marker, 1) if marker in body else body.rstrip() + "\n\n" + section + "\n"
    if not matches:
        return body.replace("No matched hot topics.", "<h3>本次未抓到任何条目</h3>")
    return body


# ---------------------------------------------------------------------------
# Toutiao v2 report (persona-driven)
# ---------------------------------------------------------------------------


def render_toutiao_report_v2(
    profile: PersonaProfile,
    extraction: PersonaKeywordExtraction,
    candidates: list[Candidate],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    """Render a Markdown report for the v2 pipeline."""
    details_by_url = {_detail_url_key(d.url): d for d in item_details or []}
    lines = [
        f"# 头条热点日报 — {profile.user_id}",
        "",
        f"- 一级赛道: {profile.level1}",
        f"- 二级赛道: {profile.level2}",
        f"- 人设: {profile.personal.role}",
        f"- 对象: {profile.personal.subject}",
        f"- 场景: {', '.join(profile.personal.scenarios)}",
        f"- 价值: {profile.personal.value}",
        f"- Persona signature: `{profile.persona_signature}`",
        f"- 抓取时间: {fetched_at}",
        f"- 关键词来源: {extraction.source}（生成于 {extraction.generated_at}）",
        "",
        "## 提取的检索词",
        "",
        "| 关键词 | 命中预期 |",
        "| --- | --- |",
    ]
    for kw in extraction.keywords:
        lines.append(f"| {kw.keyword} | {kw.match_expectation} |")
    lines.append("")

    paths_count: dict[str, int] = {}
    for c in candidates:
        for token in c.source_path.split("+"):
            paths_count[token] = paths_count.get(token, 0) + 1
    lines.append("## 候选来源统计")
    lines.append("")
    if paths_count:
        for path, count in sorted(paths_count.items()):
            lines.append(f"- Path {path}: {count}")
    else:
        lines.append("- (无候选)")
    lines.append("")

    lines.append("## 重点文章")
    lines.append("")
    if not candidates:
        lines.append("本次未抓到符合条件的文章。")
    else:
        lines.append("| Rank | 标题 | Score | 路径 | 命中关键词 | is_toutiao_hot | URL |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for index, c in enumerate(candidates, start=1):
            title = c.item.title.replace("|", "\\|")
            lines.append(
                f"| {index} | {title} | {c.preliminary_score:.2f} | {c.source_path} | "
                f"{c.matched_keyword or '-'} | {c.is_toutiao_hot} | {c.item.url} |"
            )
    lines.append("")

    lines.extend(
        [
            "## 操作建议",
            "",
            "- 优先关注 Path A（热榜优先）中的条目，这些来自平台官方榜单，热度真实。",
            "- 对 Path B 高 article_heat 文章，可直接复用文章结构；正文已落盘在 `articles/`。",
            "- 路径统计在 raw/candidates_by_path.json 可查（若启用）。",
            "",
        ]
    )
    return "\n".join(lines)


def _detail_url_key(url: str) -> str:
    return url.split("?", maxsplit=1)[0]


def _truncate(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:max_chars]


def _build_summary_prompt(
    profile: PersonaProfile,
    candidates: list[Candidate],
    details_by_url: dict[str, ItemDetail],
) -> str:
    rows = []
    for c in candidates[:10]:
        detail = details_by_url.get(_detail_url_key(c.item.url))
        excerpt = _truncate(detail.content if detail else c.item.title, 200)
        rows.append(
            f"- [{c.source_path}] {c.item.title} | score={c.preliminary_score:.2f} | "
            f"keyword={c.matched_keyword} | excerpt={excerpt}"
        )
    return (
        f"Persona: {profile.personal.role} / {profile.personal.subject} / "
        f"{', '.join(profile.personal.scenarios)}\n\n"
        "今日 Top 文章:\n" + "\n".join(rows) +
        "\n\n请用 3-5 句中文总结今日热点主题趋势。"
    )
