# HeatedTopics

HeatedTopics 是一个热点话题采集和详情证据整理项目。流程会先发现多平台热榜话题，再对核心平台补充网页详情，最后输出结构化 JSON/JSONL 和 Markdown 报告。

## 当前采集策略

项目分两层采集：

1. 话题发现：默认使用 DailyHot API 采集已配置来源。
2. 详情采集：只对百度、微博、小红书、Bilibili 和掘金做进一步详情补充，其他来源继续参与话题聚合和报告排布，但不额外打开网页抓详情。

核心平台策略如下：

| 平台 | 话题来源 | 详情策略 |
| --- | --- | --- |
| 百度 | DailyHot，必要时回退百度热搜页 | 搜索并抓取可用详情页内容 |
| 微博 | DailyHot | 使用已保存登录态的 Playwright 会话访问搜索页 |
| 小红书 | 今日热榜小红书页、TopHub 小红书热榜，必要时回退小红书网页 | 当前项目只采集话题、热度和排序；笔记详情写入占位，后续由外部小红书笔记采集项目补齐 |
| Bilibili | DailyHot | 使用热榜元数据补充视频类详情 |
| 掘金 | DailyHot | 使用 DailyHot 元数据补充技术类详情 |

小红书的 DailyHot API 当前没有稳定热榜数据，所以项目会优先从：

- https://rebang.today/?tab=xiaohongshu
- https://tophub.today/n/L4MdA5ldxD

提取榜单标题、热度值和排名。当前项目不再进入小红书官网搜索页采集笔记正文，而是在详情文件中写入 `notes_placeholder` 占位，便于后续外部笔记采集项目按 `topic_key` 补齐。

## 安装和验证

推荐在项目目录运行：

```powershell
cd E:\.code\My\heatedTopics\heatedTopics
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests -q
```

## 登录态管理

微博和小红书详情采集依赖本地浏览器登录态。先检查状态：

```powershell
uv run python -m src.browser.session_manager check
```

需要登录时分别执行：

```powershell
uv run python -m src.browser.session_manager login weibo
uv run python -m src.browser.session_manager login xiaohongshu
```

登录信息保存在 `data/browser_state/`，该目录不应提交到 Git。即使微博或小红书没有登录，主流程也会继续运行；缺少登录态的平台会记录提醒并跳过对应官网详情。

## 运行采集

采集今天的所有热点和核心详情：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-recent-details --window today
```

强制跳过缓存、重新采集：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-recent-details --window today --refresh
```

采集最近 7 天窗口：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-recent-details --window last_7_days
```

只采集百度、微博和小红书的话题与详情：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-core-hot-details --window today --refresh
```

这个命令会把热榜 route 和详情平台都限制为 `baidu,weibo,xiaohongshu`。其中小红书热榜会先走今日热榜/TopHub，详情阶段只写入外部笔记采集占位，不在当前项目中抓取笔记正文。

## 创作者热点分类索引

在已有采集结果基础上生成创作者检索推荐用的结构化索引：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run build-creator-topic-index --render-report
```

主要输出：

| 路径 | 内容 |
| --- | --- |
| `data/processed/creator_topic_index.json` | 面向下游检索推荐的结构化话题索引 |
| `reports/creator_topic_cards.md` | 从索引渲染出来的创作者热点卡片报告 |

分类索引采用受控的 `domain_path`、`content_modes`、`audience_tags` 做稳定召回，用 `entity_keywords`、`event_keywords` 和 `match_terms` 做补充检索证据。

## 缓存机制

项目会把 DailyHot、外部小红书榜单、详情证据写入本地缓存，默认有效期为 7 天。相同窗口和相同查询在一周内再次执行时，会优先读取缓存，避免重复访问 API 或网页。

常用行为：

| 场景 | 行为 |
| --- | --- |
| 普通运行 | 优先使用 7 天内缓存 |
| 添加 `--refresh` | 跳过读取缓存，重新采集并覆盖缓存 |
| 删除 `data/cache/` | 清空本地缓存，下次运行重新采集 |

彻底重新跑一遍：

```powershell
Remove-Item -LiteralPath data\cache -Recurse -Force
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-core-hot-details --window today --refresh
```

## 输出文件

一次完整采集会写入这些主要文件：

| 路径 | 内容 |
| --- | --- |
| `data/raw/dailyhot_records.json` | 热榜原始记录，包括 DailyHot 和小红书外部榜单补充记录 |
| `data/raw/platforms/xiaohongshu_topics.jsonl` | 小红书热榜话题 RAW，包含榜单来源、标题、热度、URL、原始榜单片段 |
| `data/raw/platforms/xiaohongshu_notes.jsonl` | 小红书话题对应详情占位 RAW，包含空 `notes`、外部采集状态和占位原因 |
| `data/raw/platforms/baidu_topics.jsonl` | 百度热榜话题 RAW |
| `data/raw/platforms/baidu_details.jsonl` | 百度详情 RAW，包含搜索结果和 query attempts |
| `data/raw/platforms/weibo_topics.jsonl` | 微博热榜话题 RAW |
| `data/raw/platforms/weibo_posts.jsonl` | 微博详情 RAW，包含帖子、browser_raw、页面文本、DOM 抽取结果 |
| `data/processed/topic_clusters.json` | 去重和聚类后的话题 |
| `data/evidence/detail_evidence.json` | 详情证据汇总 |
| `data/evidence/detail_evidence_raw.jsonl` | 详情证据 RAW 行记录 |
| `reports/recent_hot_topics_digest.md` | 最终热点报告 |
| `data/cache/` | 7 天缓存数据 |

## 风控和安全边界

项目采用低频、缓存优先、登录态复用的方式降低重复访问。遇到验证码、登录墙、安全校验或明显风控页面时，采集器会记录该平台的问题并继续处理其他平台。

项目不实现验证码绕过、账号规避检测、指纹伪装、代理池轮换或其他可能违反平台规则的策略。微博和小红书建议使用稳定、人工登录后的浏览器会话，并控制运行频率。

## 开发文档

相关设计和执行计划：

- `docs/superpowers/specs/2026-06-23-detail-cache-and-session-safety-design.md`
- `docs/superpowers/plans/2026-06-23-detail-cache-and-session-safety.md`

## 关键词搜索话题发现

新链路从作者画像和关键词出发，通过独立的 `src/search_discovery/` 包生成搜索 query、规划搜索源、归一化结果、补全内容、聚合候选话题并输出报告。它不覆盖原有 DailyHot 热榜采集链路。

示例运行：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.cli --profile config/search_discovery/creator_profiles/tech_ai_creator.json --render-report
```

输出文件：

| 路径 | 内容 |
| --- | --- |
| `data/search_discovery/raw/search_results.jsonl` | 搜索源返回的归一化结果 |
| `data/search_discovery/evidence/search_content_evidence.jsonl` | 摘要或正文补全证据 |
| `data/search_discovery/processed/search_topic_index.json` | 候选话题索引 |
| `reports/search_discovery/search_topic_recommendations.md` | 可读推荐报告 |
