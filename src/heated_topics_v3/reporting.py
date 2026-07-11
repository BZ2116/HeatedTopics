from heated_topics_v3.contracts import MatchResult, UserProfile


def render_juejin_report(profile: UserProfile, matches: list[MatchResult], fetched_at: str) -> str:
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
        lines.extend(
            [
                f"### {index}. {item.title}",
                "",
                f"- URL: {item.url}",
                f"- Rank: {item.rank}",
                f"- Heat: {item.heat.value} ({item.heat.metric_name})",
                f"- Score: {match.relevance_score}",
                f"- Match terms: {', '.join(match.match_terms)}",
                "",
            ]
        )
    return "\n".join(lines)
