from dataclasses import replace

from heated_topics_v3.contracts import HotItem, MatchResult, TopicQuery


def match_hot_item_to_queries(
    item: HotItem,
    queries: tuple[TopicQuery, ...],
    excluded_keywords: tuple[str, ...] = (),
) -> MatchResult:
    searchable_text = _searchable_text(item)
    matched_query_ids: list[str] = []
    match_terms: list[str] = []

    for query in queries:
        if item.platform not in query.target_platforms:
            continue
        query_terms = [term for term in query.keywords if _contains(searchable_text, term)]
        if query_terms:
            matched_query_ids.append(query.query_id)
            match_terms.extend(query_terms)

    excluded_terms = tuple(term for term in excluded_keywords if _contains(searchable_text, term))
    unique_match_terms = _unique_tuple(match_terms)
    relevance_score = _score(unique_match_terms, excluded_terms)
    return MatchResult(
        item=replace(item, matched_query_ids=tuple(matched_query_ids)),
        match_terms=unique_match_terms,
        excluded_terms=excluded_terms,
        relevance_score=relevance_score,
        is_relevant=relevance_score > 0,
    )


def _searchable_text(item: HotItem) -> str:
    raw_bits: list[str] = []
    for value in item.raw_payload.values():
        if isinstance(value, str):
            raw_bits.append(value)
        elif isinstance(value, dict):
            raw_bits.extend(str(child) for child in value.values() if isinstance(child, str))
    return " ".join([item.title, item.summary, item.category, *raw_bits]).casefold()


def _contains(searchable_text: str, term: str) -> bool:
    return bool(term.strip()) and term.casefold() in searchable_text


def _score(match_terms: tuple[str, ...], excluded_terms: tuple[str, ...]) -> int:
    if excluded_terms:
        return 0
    return min(100, len(match_terms) * 40)


def _unique_tuple(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return tuple(unique)
