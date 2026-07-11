# V3 Data Contract

V3 uses five primary data objects:

- `UserProfile`: describes the creator or user who needs topic recommendations.
- `TopicQuery`: carries profile intent into filtering, matching, scoring, and enrichment.
- `HotItem`: stores one platform hot-list record with heat metrics and raw payload.
- `ItemDetail`: stores detailed content for a matched hot item.
- `TopicCluster`: groups related hot items into one usable topic.
- `ReportBundle`: packages human-readable report text with structured output.

`TopicQuery` is required even when a platform can collect hot lists without query input.

`ItemDetail` is required for matched items when a platform can provide detail through a JSON API, public page, or browser-supported page extraction.
