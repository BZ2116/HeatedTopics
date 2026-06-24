# Creator Topic Classification Design

## Goal

Build a creator-oriented classification layer on top of the existing hot-topic data pipeline.

The new layer should help downstream retrieval and recommendation systems find hot topics that match a creator's domain, audience, and content style. The output must be structured and stable enough for programmatic use, while still supporting a readable Markdown report.

The design intentionally avoids a flat pile of tags. It separates stable controlled labels from flexible keyword evidence so the taxonomy can stay useful as the data grows.

## Non-Goals

- Do not replace raw collection outputs such as `data/raw/dailyhot_records.json` or `data/evidence/detail_evidence_raw.jsonl`.
- Do not build a full creator recommendation engine in this step.
- Do not let generated free-form tags become the primary taxonomy.
- Do not require an LLM for the first implementation. A later version may use one only to choose among controlled candidates or to review uncertain cases.

## Inputs

The classifier consumes existing pipeline outputs:

- `data/raw/dailyhot_records.json`: hot-list records with platform, rank, hot value, cover, URL, title, and raw payload.
- `data/evidence/detail_evidence_raw.jsonl`: compact detail rows with source, URL, title, content, cover, hotvalue, and rank.
- `data/processed/topic_clusters.json`: deduplicated topic clusters with canonical title, topic key, platforms, rank, and hot record ids.

The classifier should tolerate missing files or partial data by producing lower-confidence cards rather than failing the whole run when possible.

## Primary Output

Create a structured JSON index:

`data/processed/creator_topic_index.json`

Top-level shape:

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-06-24T00:00:00+08:00",
  "source_files": [],
  "topics": []
}
```

Markdown is a derived view:

`reports/creator_topic_cards.md`

The Markdown report groups topics by high-level domain and renders one card per topic.

## Topic Record Shape

Each topic record should contain:

```json
{
  "topic_id": "topic_001",
  "topic_key": "hebei_gaokao_score_line",
  "title": "河北高考分数线",
  "domain_path": ["教育升学", "高考", "分数线"],
  "secondary_domain_paths": [["本地城市", "河北"]],
  "content_modes": ["数据整理", "经验攻略", "实时跟进"],
  "audience_tags": ["学生", "家长"],
  "entity_keywords": ["河北", "2026高考", "本科线"],
  "event_keywords": ["分数线公布", "志愿填报"],
  "match_terms": ["河北高考分数线", "河北本科线", "志愿填报"],
  "hotness": {
    "best_rank": 1,
    "platforms": ["weibo"],
    "hot_values": [
      {"platform": "weibo", "value": "1784276"}
    ]
  },
  "traceability": "high",
  "freshness": "breaking",
  "risk_level": "low",
  "creator_fit_score": 88,
  "classification_confidence": "high",
  "match_signals": {
    "domain_terms": ["高考", "分数线"],
    "content_mode_terms": ["指南", "汇总"],
    "audience_terms": ["考生", "家长"]
  },
  "card": {
    "source_platforms": ["weibo"],
    "summary": "河北公布 2026 年高考分数线，适合教育、升学和本地城市类创作者做数据整理、志愿填报攻略和实时跟进。",
    "detail": "具体内容来自已采集的热榜记录和详情证据。",
    "evidence_urls": []
  }
}
```

## Controlled Taxonomy

The retrieval backbone uses controlled labels. These labels must come from a local taxonomy definition rather than free generation.

### Domain Path

`domain_path` is the most important retrieval field. It is hierarchical and controlled:

- Level 1: broad creator vertical.
- Level 2: more specific topic family.
- Level 3: concrete subtopic when available.

Examples:

- `["教育升学", "高考", "分数线"]`
- `["教育升学", "高考", "志愿填报"]`
- `["财经商业", "汽车消费", "新车上市"]`
- `["科技AI", "AI应用", "医疗AI"]`
- `["社会民生", "公共安全", "案件通报"]`

Each topic has exactly one `domain_path` and up to two `secondary_domain_paths`.

### Content Modes

`content_modes` describe how a creator can make content from the topic, not what the topic is about.

Allowed first-version values:

- `数据整理`
- `经验攻略`
- `政策解读`
- `科普解释`
- `观点评论`
- `情绪共鸣`
- `案例复盘`
- `避坑提醒`
- `清单合集`
- `实时跟进`
- `趋势观察`

Each topic may have up to five content modes.

### Audience Tags

`audience_tags` describe likely creator audiences.

Allowed first-version values:

- `学生`
- `家长`
- `打工人`
- `年轻消费群体`
- `女性用户`
- `城市居民`
- `中老年`
- `创业者`
- `投资者`
- `技术从业者`
- `内容创作者`
- `泛大众`

Each topic may have up to three audience tags.

## Flexible Keyword Fields

Flexible keywords are useful for recall and explanation, but they must not pollute the controlled taxonomy.

### Entity Keywords

`entity_keywords` capture concrete entities:

- locations: `河北`, `上海`
- people or organizations
- products and brands
- schools, exams, institutions
- years and numeric identifiers such as `2026高考`

Limit to twelve items.

### Event Keywords

`event_keywords` capture what happened:

- `分数线公布`
- `新车上市`
- `政策发布`
- `判决结果`
- `活动开售`

Limit to eight items.

### Match Terms

`match_terms` are generated search phrases. They may combine title words, entities, and domain words.

Examples:

- `河北高考分数线`
- `河北本科线`
- `高考志愿填报`

Limit to twelve items. These terms are for retrieval assistance and match explanations, not taxonomy management.

## Classification Method

Use rules first.

1. Normalize text from title, hot records, and detail evidence.
2. Match controlled taxonomy entries using keyword dictionaries and aliases.
3. Score candidate domain paths by weighted term hits:
   - title hit: strongest
   - hot-list metadata hit: medium
   - detail content hit: medium
   - platform-specific raw text hit: lower, because it can contain noisy page chrome
4. Select the highest-scoring `domain_path`.
5. Add up to two `secondary_domain_paths` when they are meaningfully close but not redundant.
6. Assign `content_modes` from mode dictionaries and topic patterns.
7. Assign `audience_tags` from domain defaults plus explicit text matches.
8. Extract flexible keywords with simple deterministic rules and filters.
9. Compute traceability, freshness, risk, and creator fit score.

If no domain path passes the minimum threshold, use:

```json
{
  "domain_path": ["未分类", "待人工确认"],
  "classification_confidence": "low"
}
```

## Alias Normalization

Aliases map noisy or similar expressions to controlled labels.

Example:

```json
{
  "经验攻略": ["攻略", "指南", "教程", "怎么选", "避坑"],
  "数据整理": ["汇总", "名单", "表格", "分数线", "清单"],
  "情绪共鸣": ["破防", "焦虑", "吐槽", "共鸣"],
  "教育升学>高考>志愿填报": ["志愿填报", "报志愿", "专业选择", "院校选择"]
}
```

The output should always use the canonical controlled label.

## Score Fields

### Traceability

`traceability` estimates whether the topic has follow-up value.

Values:

- `high`: official source, ongoing public updates, multi-platform discussion, or clear future milestones.
- `medium`: enough detail exists, but follow-up path is limited or platform-specific.
- `low`: one-off entertainment, vague meme, weak source, or low detail depth.

### Freshness

Values:

- `breaking`: just emerged or tied to today's event.
- `ongoing`: active but not brand new.
- `evergreen`: can be used beyond the current trend window.
- `fading`: likely past its best publishing window.

### Risk Level

Values:

- `low`: ordinary consumer, education, entertainment, or lifestyle topic.
- `medium`: public controversy, legal details, medical advice, finance, minors, or sensitive claims.
- `high`: politically sensitive, highly disputed, reputationally risky, or likely to require strict source verification.

### Creator Fit Score

`creator_fit_score` is a 0-100 score for general creator usefulness, not personalized ranking.

Recommended components:

- hotness and rank
- detail depth
- traceability
- number of usable content modes
- domain clarity
- risk penalty

Downstream personalized recommendation should combine this score with creator profile match scores.

## Downstream Recommendation Contract

This classification layer supports recommendation by separating recall, ranking, and explanation.

Recall fields:

- `domain_path`
- `secondary_domain_paths`
- `content_modes`
- `audience_tags`
- `match_terms`

Ranking fields:

- `creator_fit_score`
- `traceability`
- `freshness`
- `risk_level`
- `hotness`

Explanation fields:

- `match_signals`
- `entity_keywords`
- `event_keywords`
- `card.summary`

Example downstream scoring:

```text
final_score =
  domain_match
  + keyword_match
  + audience_match
  + content_mode_match
  + hotness_score
  + traceability_score
  + freshness_score
  - risk_penalty
```

The classifier should not personalize for one creator. It should produce clean topic metadata that a recommendation layer can personalize later.

## Markdown Card Format

The derived report should group topics by top-level domain.

Each card includes:

- title
- hotness: rank, hot value, and source platforms
- domain path
- content modes
- audience tags
- concrete detail
- traceability
- freshness
- risk level
- creator fit score
- useful keywords
- evidence URLs when available

## Error Handling

- If evidence detail is missing, still produce a card using hot-list title and metadata.
- If title or content appears garbled, preserve the original data but lower classification confidence when matching is uncertain.
- If a topic matches only broad-level categories, set a shorter `domain_path` and mark confidence as `medium` or `low`.
- If controlled labels cannot be assigned, use `未分类` and keep extracted keywords for manual review.

## Testing

Add focused tests for:

- controlled taxonomy matching
- alias normalization
- domain path selection
- content mode selection
- keyword extraction limits
- score field bounds
- Markdown rendering from JSON
- graceful behavior with missing evidence

Tests should include representative topics such as:

- 高考分数线
- 志愿填报指南
- 新车上市价格
- 医疗 AI 观点
- 明星娱乐事件

## Rollout

Implement as a new, additive pipeline step.

Suggested command:

```powershell
uv run python -m src.core_pipeline.run build-creator-topic-index
```

Suggested optional report rendering:

```powershell
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report
```

Existing collection and detail commands should keep working unchanged.
