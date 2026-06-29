# Profile-driven Search Routing 设计方案

## 目标

构建一条以用户画像为入口的搜索式话题发现流程。

每次请求不从固定热榜出发，而是先读取某个创作者的人设、赛道标签、关键词和内容目标，再动态决定：

- 调用哪些搜索源。
- 每个搜索源的权重是多少。
- 每个搜索源应该使用什么 query。
- 返回结果如何被标准化、核验、总结，并输出为内容创作参考。

第一版测试阶段要求：每个启用的搜索源只调用一次。搜索质量主要通过源专属 query 提升，权重用于调度、排序和结果解释。

## 非目标

- 不使用 DailyHot 作为主链路候选池。
- 不让 LLM 编造热点或补充无来源事实。
- 不生成最终发布文案。
- 不做登录态抓取、验证码绕过或平台风控规避。
- 不把只有话题名、没有 URL 或摘要的信息视为有效证据。
- 不在第一版实现复杂反馈学习，只保留可扩展接口。

## 输入画像

第一版从 JSON profile 读取输入。

```json
{
  "user_id": "creator_001",
  "role": "科技类博主",
  "profile_type": "tech_ai_creator",
  "platforms": ["小红书", "公众号", "B站"],
  "track_tags": ["AI", "开发者工具", "开源项目"],
  "custom_keywords": ["AI Agent", "MCP", "RAG"],
  "content_goal": "寻找近期适合内容创作的技术趋势和项目",
  "exclude_keywords": ["纯营销", "无来源爆料"]
}
```

字段含义：

- `role`：自然语言人设，用于报告解释和 LLM 总结。
- `profile_type`：路由权重的主要配置键。
- `track_tags`：长期赛道标签，影响分类和权重。
- `custom_keywords`：本次请求的核心搜索词，生成 query 时优先级最高。
- `content_goal`：限定搜索意图，例如趋势观察、项目盘点、教程实践。
- `exclude_keywords`：过滤明显不适合的结果。

## 主流程

```text
CreatorProfile
  -> IntentClassifier
  -> DynamicSourceRouter
  -> PerSourceQueryGenerator
  -> SearchProviders
  -> ResultNormalizer
  -> EvidenceFilter
  -> TopicClusterer
  -> LlmOrTemplateAnalyzer
  -> CreatorReferenceReport
```

职责说明：

1. `IntentClassifier` 根据用户关键词识别搜索意图，例如技术项目、技术文章、新闻热点、产品趋势。
2. `DynamicSourceRouter` 根据用户画像和搜索意图选择搜索源，并计算动态权重。
3. `PerSourceQueryGenerator` 为每个搜索源生成一条专属 query。
4. `SearchProviders` 在测试阶段对每个启用源只调用一次。
5. `ResultNormalizer` 将不同 API 的返回值统一为同一种结构。
6. `EvidenceFilter` 丢弃没有可追溯来源的结果，并标记详细度和可信度。
7. `TopicClusterer` 对同 URL、同标题、同主题的结果去重合并。
8. `LlmOrTemplateAnalyzer` 基于真实结果做总结，不能新增无来源事实。
9. `CreatorReferenceReport` 输出分条创作参考。

## 搜索源 v0.1

| Source ID | 服务 / 域名 | 主要用途 | 基础权重 | 详情能力 | 第一版状态 |
| --- | --- | --- | ---: | --- | --- |
| `github_search` | `api.github.com` | 开源项目、repo、框架、开发者工具趋势 | 85 | 高 | P0，技术类优先 |
| `juejin_content` | 百炼搜索 / 掘金内容槽位 | 中文技术文章、教程、实践案例 | 80 | 中高 | P0/P1，取决于 API key |
| `baidu_qianfan_search` | 百度千帆搜索 | 国内综合网页、新闻、博客、问答 | 85 | 中 | P0 |
| `news_api_cn` | 博查 / 新闻搜索槽位 | 新闻事实、发布时间、媒体来源 | 75 | 中高 | P0/P1，取决于 API key |

DailyHot 只作为后续热度参考，不参与第一版主召回。

## 动态路由权重

权重由三部分组成：

```text
final_weight = profile_base_weight + intent_boost + keyword_boost - risk_or_mismatch_penalty
```

### 作者画像基础权重

| Profile Type | GitHub | 技术内容 | 通用搜索 | 新闻搜索 |
| --- | ---: | ---: | ---: | ---: |
| `tech_ai_creator` | 95 | 90 | 80 | 65 |
| `developer_creator` | 100 | 95 | 70 | 45 |
| `business_startup_creator` | 35 | 35 | 85 | 90 |
| `general_hot_topic_creator` | 5 | 10 | 95 | 90 |
| `education_career_creator` | 15 | 40 | 90 | 85 |
| `consumer_lifestyle_creator` | 5 | 10 | 90 | 75 |

### 搜索意图加权

| Intent | GitHub | 技术内容 | 通用搜索 | 新闻搜索 |
| --- | ---: | ---: | ---: | ---: |
| `tech_project` | +20 | +10 | -10 | -20 |
| `tech_article` | +5 | +20 | +5 | -10 |
| `news_trend` | -20 | -10 | +15 | +20 |
| `product_trend` | -10 | 0 | +15 | +10 |
| `content_angle` | -5 | +5 | +15 | +10 |

### 调用规则

第一版测试阶段：

- 只调用 `final_weight > 0` 且 API key 可用的源。
- 每个源只调用一次。
- 每个源最多返回前 10 条结果。
- 如果某个源不可用，记录 `mock_unavailable` 或 `provider_unavailable`，不使用 mock 结果进入最终话题。

## 源专属 Query 生成

动态 query 是第一版质量核心。不同搜索源不共用同一个 query。

输入关键词先合并为核心关键词串：

```text
AI Agent MCP RAG
```

然后根据搜索源和意图生成不同 query。

### 科技 AI 博主示例

| Source ID | Query | 生成原因 |
| --- | --- | --- |
| `github_search` | `AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01` | GitHub 需要 repo 过滤、star 过滤和活跃度过滤 |
| `juejin_content` | `AI Agent MCP RAG 教程 实践 案例 开发者` | 技术内容源更适合中文实践、教程和案例 |
| `baidu_qianfan_search` | `AI Agent MCP RAG 最新进展 行业动态 应用` | 通用搜索负责综合网页、博客和行业资料 |
| `news_api_cn` | `AI Agent MCP RAG 最新 发布 融资 应用` | 新闻源负责时效事件和事实背景 |

### Query 模板

| Source ID | Template |
| --- | --- |
| `github_search` | `{keywords} in:name,description stars:>50 pushed:>2025-01-01` |
| `juejin_content` | `{keywords} 教程 实践 案例 开发者` |
| `baidu_qianfan_search` | `{keywords} 最新进展 行业动态 应用` |
| `news_api_cn` | `{keywords} 最新 发布 融资 应用` |

如果用户关键词超过 5 个，第一版只取优先级最高的 3 到 5 个，避免 query 过长导致召回变差。

## 标准化结果

所有搜索源输出统一为 `SearchResult`。

```json
{
  "result_id": "github_search_001",
  "source_id": "github_search",
  "source_role": "vertical_project",
  "query": "AI Agent MCP RAG in:name,description stars:>50 pushed:>2025-01-01",
  "route_weight": 95,
  "route_reason": "科技类创作者关注 AI Agent、MCP、RAG，GitHub 适合召回开源项目。",
  "title": "example/agent-framework",
  "url": "https://github.com/example/agent-framework",
  "domain": "github.com",
  "snippet": "Repository description or search snippet.",
  "content_type": "repo",
  "published_at": "2026-06-20T10:00:00+08:00",
  "fetched_at": "2026-06-29T12:00:00+08:00",
  "matched_keywords": ["AI Agent"],
  "metrics": {
    "stars": 1200
  },
  "fetch_status": "ok",
  "error_type": null
}
```

最低有效条件：

- 必须有 `url`。
- 必须有 `title`。
- 必须有 `snippet`、`content`、`description` 或可结构化详情之一。
- 必须能标记 `source_id` 和 `query`。

不满足最低条件的结果不进入最终创作参考。

## LLM 总结与准确性约束

LLM 只在结果标准化和证据过滤之后工作。

输入给 LLM 的内容只包含真实搜索结果：

- 标题。
- URL。
- 来源。
- 摘要或正文片段。
- 发布时间或抓取时间。
- 命中关键词。
- 来源权重。

LLM 输出必须满足：

- 每条结论都能回溯到至少一个 `source_hit`。
- 不新增搜索结果里不存在的事实。
- 对不确定信息标记“待核验”。
- 对医疗、投资、法律、公共安全、未成年等内容标记高风险。

没有 LLM key 时，第一版使用模板总结，仍然输出证据来源。

## 最终报告格式

输出 Markdown，面向内容创作者阅读。

```md
## 1. AI Agent 开源项目仍在快速更新

- 匹配原因：用户关注 AI Agent、MCP、RAG，且人设偏科技和开发者工具。
- 关键信息：搜索结果中多个相关 repo 或技术文章近期活跃，适合做项目盘点或实践类内容。
- 创作角度：
  - 值得关注的 AI Agent 开源项目
  - MCP 是否正在成为 Agent 工具调用基础设施
- 证据来源：
  - GitHub: https://github.com/example/agent-framework
  - 技术文章: https://example.com/article
- 可信度：高
- 风险提示：不要把单个项目热度夸大成行业共识。
```

每条报告必须包含：

- 话题标题。
- 匹配原因。
- 关键信息摘要。
- 可创作角度。
- 证据来源 URL。
- 可信度。
- 风险提示。

## 输出路径

为了和旧 DailyHot 项目隔离，第一版继续使用独立目录：

```text
data/search_discovery/raw/search_results.jsonl
data/search_discovery/evidence/search_content_evidence.jsonl
data/search_discovery/processed/search_topic_index.json
reports/search_discovery/search_topic_recommendations.md
```

旧路径不写入：

```text
data/raw/dailyhot_records.json
data/evidence/detail_evidence_raw.jsonl
data/processed/creator_topic_index.json
reports/creator_topic_cards.md
```

## 错误处理

- API key 缺失：记录不可用状态，不进入最终结果。
- API 鉴权失败：记录 `auth_failed`，提示具体 source。
- API 限流：记录 `rate_limited`，本轮不重试过多。
- 上游结构变化：记录 `parse_failed`，保留原始错误摘要。
- 所有源失败：输出空报告和 provider 状态，不静默成功。
- LLM 不可用：使用模板分析，不阻塞搜索主流程。

## 测试标准

第一版实现需要覆盖：

- 用户画像能生成搜索意图。
- 科技类画像下 GitHub 和技术内容源权重高于新闻源。
- 每个源只生成一条 query。
- 每个源只被调用一次。
- 不同源生成不同 query。
- 无 URL 或无摘要的结果被过滤。
- 不可用 provider 不进入最终话题。
- Markdown 报告每条推荐都带来源 URL。
- 没有 LLM key 时能使用模板总结。

## 第一版验收

以 `tech_ai_creator` profile 运行后，应满足：

- GitHub query 包含 `in:name,description`、`stars:>50`、`pushed:>2025-01-01`。
- 技术内容 query 包含 `教程`、`实践`、`案例`。
- 通用搜索 query 包含 `最新进展`、`行业动态`。
- 新闻搜索 query 包含 `最新`、`发布`。
- 每个可用 source 在 `search_results.jsonl` 中只出现一个 query。
- 最终报告每条内容都有至少一个真实 URL。

