from heated_topics_v3.contracts import ItemDetail, MatchResult, UserProfile


def render_juejin_report(
    profile: UserProfile,
    matches: list[MatchResult],
    fetched_at: str,
    item_details: list[ItemDetail] | None = None,
) -> str:
    details_by_item_id = {detail.item_id: detail for detail in item_details or []}
    lines = [
        "# Juejin Hot Topics Report",
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
                f"- URL: {item.url}",
                f"- Rank: {item.rank}",
                f"- Heat: {item.heat.value} ({item.heat.metric_name})",
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
