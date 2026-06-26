# 关键词搜索话题发现设计方案

## 目标

构建第一版「基于作者关键词的搜索式话题发现层」。

系统不再从 DailyHot 这类热榜源出发，而是从创作者画像出发：用户角色、赛道标签、自定义关键词、内容方向会被转换成一组搜索 query，然后调用 Search API、新闻 API、GitHub、掘金等垂直内容源，直接召回：

- 与作者关键词匹配的热点话题。
- 与作者关键词匹配的新闻、文章、项目、博客、社区内容。
- 可追溯的摘要、URL、来源、时间和正文补全信息。

DailyHot 在本方案里只作为可选热度校验，不作为第一版主链路。

## 非目标

- 不用 DailyHot 作为主要候选池。
- 不做对外 HTTP API。
- 不生成最终发布文案。
- 不抓取登录态平台，不绕过风控或验证码。
- 不把只有标题、没有 URL/摘要/正文的结果视为有效结果。
- 不把某一个搜索源作为唯一事实来源。

## 第一版核心流程

```text
CreatorProfile
  -> KeywordClassifier
  -> QueryGenerator
  -> SourcePlanner
  -> ProviderSearch
  -> ResultNormalizer
  -> FulltextEnricher
  -> TopicClusterer
  -> TopicRanker
  -> SearchTopicIndex + Markdown Report
```

解释：

1. `CreatorProfile`：输入作者角色、赛道标签、自定义关键词、内容模式。
2. `KeywordClassifier`：把关键词归入受控分类，例如热点发现、新闻文章、技术项目、教程实践。
3. `QueryGenerator`：按分类生成搜索 query，而不是只搜索原始关键词。
4. `SourcePlanner`：根据作者类型和关键词分类选择搜索源，并分配权重。
5. `ProviderSearch`：调用具体 Search API 或垂直源。
6. `ResultNormalizer`：把不同 provider 的返回值统一成同一种结构。
7. `FulltextEnricher`：如果搜索结果只有摘要，则尝试补正文或结构化详情。
8. `TopicClusterer`：把多个结果聚合成候选话题。
9. `TopicRanker`：根据匹配度、来源权重、详情质量、时效性和风险排序。

## 搜索源确认 v0.1

| Source ID | 域名 / 服务 | 角色 | 详情能力 | 默认权重 | 第一版状态 |
| --- | --- | --- | --- | ---: | --- |
| `baidu_qianfan_search` | `ai.baidu.com` / 百度千帆百度搜索 | 国内通用搜索主源 | 中 | 90 | P0 |
| `news_api_cn` | `juhe.cn` / `tianapi.com` / `tanshuapi.com` 三选一 | 新闻事实与背景补充 | 中高 | 85 | P0 |
| `github_search` | `api.github.com` | 技术项目搜索 | 高 | 80 | 技术类 P0 |
| `juejin_content` | `juejin.cn` / 社区整理接口 | 技术文章与社区内容 | 中高 | 75 | P1，实验源 |
| `serpapi_baidu` | `serpapi.com` | 百度 SERP 兜底 | 中 | 65 | P1，可选 |
| `dataforseo_baidu` | `dataforseo.com` | 百度 SERP 兜底，偏 SEO/地域 | 中 | 60 | P1，可选 |
| `searchapi_baidu` | `searchapi.io` | 百度 SERP 兜底 | 中 | 60 | P1，可选 |
| `dailyhot_reference` | DailyHotApi 或类似热榜源 | 热度参考，不参与主召回 | 低 | 25 | P2，可选 |

### 源定位

- 百度千帆搜索：第一版主搜索源，负责国内网页、新闻、博客、问答等宽召回。
- 新闻 API：补充事实、时间、媒体来源和事件背景。
- GitHub Search：技术类作者的高权重来源，适合开源项目、工具、框架趋势。
- 掘金：技术文章和工程实践内容源，但接口稳定性弱于官方 API，第一版标记为实验源。
- Baidu SERP 第三方服务：只作为百度搜索兜底，不作为默认主依赖。
- DailyHot：只用于后续热度校验，例如“这个搜索召回的话题是否也出现在热榜”。

## 作者画像权重矩阵

权重范围为 0-100。第一版先使用固定矩阵，后续再根据点击、采纳、收藏等反馈动态学习。

| 作者画像 | 百度搜索 | 新闻 API | GitHub | 掘金 | Baidu SERP 兜底 | DailyHot 参考 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `tech_ai_creator` 科技/AI 博主 | 80 | 60 | 95 | 90 | 55 | 20 |
| `developer_creator` 开发者博主 | 70 | 40 | 100 | 95 | 50 | 15 |
| `business_startup_creator` 商业/创业博主 | 85 | 90 | 35 | 30 | 60 | 20 |
| `general_hot_topic_creator` 泛热点博主 | 95 | 90 | 5 | 5 | 65 | 35 |
| `education_career_creator` 教育/职场博主 | 90 | 85 | 15 | 35 | 60 | 20 |
| `consumer_lifestyle_creator` 消费/生活博主 | 90 | 75 | 5 | 10 | 55 | 25 |
| `game_acg_creator` 游戏/ACG 博主 | 70 | 45 | 35 | 40 | 50 | 25 |
| `local_policy_creator` 本地/政策博主 | 90 | 95 | 5 | 5 | 65 | 15 |

## 关键词分类 v0.1

这里按「搜索意图」分类，而不是按热榜平台分类。

| Category ID | 中文名 | 典型关键词 | 优先搜索源 |
| --- | --- | --- | --- |
| `topic_discovery` | 热点发现 | 最新、热点、热议、趋势、爆火、刷屏、今日、刚刚、新进展 | 百度搜索、新闻 API |
| `news_article` | 新闻文章 | 新闻、报道、官方回应、通报、发布、调查、进展、事件 | 新闻 API、百度搜索 |
| `deep_article` | 深度文章 | 分析、解读、复盘、观点、原因、影响、争议、长文 | 百度搜索、掘金、新闻 API |
| `tech_project` | 技术项目 | GitHub、开源、框架、工具、库、repo、star、release | GitHub、掘金 |
| `tech_tutorial` | 技术教程 | 教程、实践、案例、源码、部署、测评、对比、最佳实践 | 掘金、GitHub、百度搜索 |
| `product_update` | 产品动态 | 发布、上线、更新、版本、价格、功能、体验、内测 | 百度搜索、新闻 API |
| `industry_signal` | 行业趋势 | 融资、裁员、并购、政策、监管、市场、增长、财报 | 新闻 API、百度搜索 |
| `community_discussion` | 社区讨论 | 网友、评论、讨论、争议、吐槽、体验、反馈 | 百度搜索、掘金 |
| `local_policy` | 本地政策 | 城市名、政策、通知、补贴、医保、社保、地铁、天气 | 新闻 API、百度搜索 |
| `risk_sensitive` | 风险敏感 | 医疗、投资、未成年、事故、案件、违法、辟谣、监管 | 新闻 API、百度搜索 |

## Query 生成规则

一个作者关键词不只生成一个 query，而是按搜索意图生成 query bundle。

输入示例：

```json
{
  "creator_id": "creator_001",
  "role": "科技类博主",
  "profile_type": "tech_ai_creator",
  "track_tags": ["AI", "开发者工具", "开源项目"],
  "custom_keywords": ["AI Agent", "MCP", "RAG"],
  "content_modes": ["趋势观察", "工具测评", "教程实践"]
}
```

输出 query bundle 示例：

```json
{
  "query_bundles": [
    {
      "category": "topic_discovery",
      "queries": [
        "AI Agent 最新进展",
        "MCP 热点",
        "RAG 今日 新闻"
      ]
    },
    {
      "category": "tech_project",
      "queries": [
        "AI Agent GitHub open source",
        "MCP GitHub repo",
        "RAG framework GitHub"
      ]
    },
    {
      "category": "tech_tutorial",
      "queries": [
        "AI Agent 掘金 实践",
        "MCP 教程",
        "RAG 最佳实践"
      ]
    }
  ]
}
```

Query 模板：

| Category | Templates |
| --- | --- |
| `topic_discovery` | `{keyword} 最新进展`、`{keyword} 热点`、`{keyword} 今日`、`{keyword} 趋势` |
| `news_article` | `{keyword} 新闻`、`{keyword} 官方回应`、`{keyword} 最新报道`、`{keyword} 进展` |
| `deep_article` | `{keyword} 分析`、`{keyword} 解读`、`{keyword} 影响`、`{keyword} 复盘` |
| `tech_project` | `{keyword} GitHub`、`{keyword} open source`、`{keyword} repo`、`{keyword} release` |
| `tech_tutorial` | `{keyword} 教程`、`{keyword} 实践`、`{keyword} 案例`、`{keyword} 源码` |
| `product_update` | `{keyword} 发布`、`{keyword} 上线`、`{keyword} 更新`、`{keyword} 测评` |
| `industry_signal` | `{keyword} 融资`、`{keyword} 裁员`、`{keyword} 政策`、`{keyword} 市场` |
| `community_discussion` | `{keyword} 网友热议`、`{keyword} 讨论`、`{keyword} 争议`、`{keyword} 体验` |

## 源调度规则

每个 query bundle 会根据作者画像和分类选择 source。

示例：科技/AI 博主

```json
{
  "profile_type": "tech_ai_creator",
  "source_plan": [
    {
      "category": "topic_discovery",
      "sources": [
        {"source_id": "baidu_qianfan_search", "weight": 80},
        {"source_id": "news_api_cn", "weight": 60}
      ]
    },
    {
      "category": "tech_project",
      "sources": [
        {"source_id": "github_search", "weight": 95},
        {"source_id": "juejin_content", "weight": 90}
      ]
    },
    {
      "category": "tech_tutorial",
      "sources": [
        {"source_id": "juejin_content", "weight": 90},
        {"source_id": "github_search", "weight": 95},
        {"source_id": "baidu_qianfan_search", "weight": 80}
      ]
    }
  ]
}
```

## 统一数据结构

### SearchResult

```json
{
  "result_id": "search_result_001",
  "source_id": "baidu_qianfan_search",
  "source_role": "primary_search",
  "query": "AI Agent 最新进展",
  "keyword_category": "topic_discovery",
  "title": "某 AI Agent 产品发布新功能",
  "url": "https://example.com/article",
  "domain": "example.com",
  "snippet": "文章摘要或搜索摘要",
  "content_type": "news_or_article",
  "published_at": "2026-06-26T10:00:00+08:00",
  "fetched_at": "2026-06-26T12:00:00+08:00",
  "metrics": {},
  "raw_payload": {},
  "fetch_status": "ok",
  "error_type": null
}
```

`content_type` 可选值：

- `news`
- `article`
- `blog`
- `repo`
- `docs`
- `community_post`
- `search_snippet`
- `unknown`

### EnrichedContent

```json
{
  "result_id": "search_result_001",
  "url": "https://example.com/article",
  "title": "某 AI Agent 产品发布新功能",
  "content": "正文或结构化内容摘要",
  "author": "作者或媒体",
  "published_at": "2026-06-26T10:00:00+08:00",
  "content_quality": "medium_high",
  "extraction_method": "provider_snippet_or_reader",
  "evidence_confidence": "medium"
}
```

### CandidateTopic

```json
{
  "topic_id": "search_topic_001",
  "title": "AI Agent 工具出现新的开源实践热潮",
  "matched_keywords": ["AI Agent", "开源项目"],
  "keyword_categories": ["topic_discovery", "tech_project", "tech_tutorial"],
  "profile_match_score": 88,
  "freshness": "breaking",
  "detail_level": "high",
  "risk_level": "low",
  "source_hits": [
    {
      "source_id": "github_search",
      "title": "example/agent-framework",
      "url": "https://github.com/example/agent-framework",
      "content_type": "repo",
      "source_weight": 95
    },
    {
      "source_id": "baidu_qianfan_search",
      "title": "AI Agent 最新进展报道",
      "url": "https://example.com/news",
      "content_type": "news",
      "source_weight": 80
    }
  ],
  "summary": "用于推荐卡片的中性摘要，必须能回溯到 source_hits。",
  "open_questions": [],
  "created_at": "2026-06-26T12:00:00+08:00"
}
```

## 排名公式 v0.1

第一版使用可解释分数。

```text
topic_score =
  source_score * 0.25
  + profile_keyword_score * 0.25
  + detail_score * 0.20
  + freshness_score * 0.15
  + evidence_diversity_score * 0.10
  - risk_penalty * 0.05
```

字段解释：

- `source_score`：来源权重的加权平均。
- `profile_keyword_score`：作者关键词与 query、标题、摘要、正文的重合度。
- `detail_score`：正文、项目 README、新闻详情越完整分数越高。
- `freshness_score`：越新、越有时效性，分数越高。
- `evidence_diversity_score`：多个独立来源支持同一候选话题时加分。
- `risk_penalty`：医疗、投资、未成年、案件、公共安全、争议事件等减分。

## 错误处理

- 如果某个 provider 缺少 API key，跳过并记录 `provider_unavailable`。
- 如果主搜索源失败，尝试一个配置好的 Baidu SERP 兜底源。
- 如果结果只有标题，没有 URL、摘要或正文，直接丢弃。
- 如果正文补全失败，保留搜索结果，但标记 `content_quality = low`。
- 如果所有 provider 都失败，输出空索引和 provider 状态报告，不静默失败。
- 如果来源是非官方或稳定性未知，标记 `stability = experimental`。

## 输出文件

主索引：

```text
data/processed/search_topic_index.json
```

原始搜索结果：

```text
data/raw/search_results.jsonl
```

正文与证据：

```text
data/evidence/search_content_evidence.jsonl
```

可读报告：

```text
reports/search_topic_recommendations.md
```

## 第一版命令

建议命令：

```powershell
uv run python -m src.core_pipeline.run discover-topics-by-profile --profile config/creator_profiles/tech_ai_creator.json --render-report
```

建议画像文件：

```text
config/creator_profiles/tech_ai_creator.json
```

## 测试范围

第一版测试应覆盖：

- source registry 加载。
- 作者画像对应的 source 权重选择。
- 关键词分类匹配。
- query bundle 生成。
- provider 结果归一化。
- 过浅结果丢弃规则。
- 排名公式边界。
- 风险敏感话题降权。
- CandidateTopic 到 Markdown 报告的渲染。

测试画像：

- 科技 AI 博主：`AI Agent`、`MCP`、`开源项目`。
- 开发者博主：`Python`、`数据库`、`DevOps`。
- 商业创业博主：`SaaS`、`融资`、`裁员`。
- 教育职场博主：`高考`、`就业`、`公务员`。

## 实施顺序建议

1. 增加配置文件：sources、profile weights、keyword categories、query templates。
2. 增加 provider-neutral 的 planner 和 normalized result schema。
3. 先实现一个通用搜索 provider 和一个新闻 provider。
4. 增加 GitHub Search，用于技术类画像。
5. 核心链路稳定后，再增加掘金，并标记为 experimental。
6. 最后再加 DailyHot 热度参考，不改变 Search API 主链路。

## 资料来源

- 百度千帆百度搜索文档：https://ai.baidu.com/ai-doc/AppBuilder/pmaxd1hvy
- 百度千帆智能搜索生成文档：https://ai.baidu.com/ai-doc/AppBuilder/amaxd2det
- SerpApi Baidu Search API：https://serpapi.com/baidu-search-api
- DataForSEO Baidu SERP API：https://docs.dataforseo.com/v3/serp-baidu-overview/
- GitHub REST API 文档：https://docs.github.com/rest
- 聚合数据新闻头条接口：https://www.juhe.cn/docs/api/id/235
- 天行数据新闻接口：https://www.tianapi.com/apiview/4
- 探数新闻接口：https://www.tanshuapi.com/market/detail-85
- 掘金社区 API 参考项目：https://github.com/chenzijia12300/juejin-api
