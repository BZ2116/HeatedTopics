# Hot Topic Data Pipeline Design

## 1. 目标

本项目第一版目标是打通一条手动运行的数据链路：

```text
DailyHotApi 多平台热点
→ 候选话题筛选
→ 微博 / 百度 / 小红书详情采集
→ 详情信息单独存储
→ LLM 同主题归并
→ LLM 热点内容整理
→ JSON + Markdown 输出
```

第一版不做定时自动化、HTTP API、MCP Server、文案生成、标签生成和自动发布。核心交付是可复用的数据资产：原始热榜、平台详情、主题聚合、热点内容整理结果。

## 2. 设计原则

1. **详情优先**：热点标题和热度只用于发现，最终整理必须基于具体详情。
2. **详情单独存储**：微博、百度、小红书采到的正文、评论预览、互动数据、截图和 HTML 快照要独立保存。
3. **登录态前置**：微博、小红书这类需要登录的平台，采集前必须先检查登录态；未登录时提醒人工登录或进入登录初始化流程。
4. **遇到风控即停**：验证码、滑块、登录失效、风控页出现时停止对应平台采集，不做绕过。
5. **LLM 只做整理**：LLM 负责同主题归并和热点内容整理，不做文案推荐、标签推荐、发布建议。
6. **来源可追溯**：所有摘要、事实和平台讨论差异都必须能回溯到 `platform_details` 或 `hot_records`。

## 3. 第一版范围

### 3.1 包含

- 通过 DailyHotApi 采集国内和国外/技术热点标题。
- 从热榜中筛选候选话题。
- 用微博、百度、小红书 Provider 采集具体详情。
- 将平台详情单独保存为结构化 JSON，并保存截图或 HTML 快照路径。
- 用 LLM 合并相同主题。
- 用 LLM 整理每个主题的摘要、关键事实、平台讨论差异、来源证据、待确认问题。
- 输出 JSON 结果和 Markdown 汇总。

### 3.2 不包含

- 定时自动化。
- 对外 HTTP API。
- MCP Server。
- Skill 封装。
- 社交平台文案生成。
- 标签推荐。
- 自动发布。
- 验证码绕过或高频批量采集。

## 4. DailyHotApi 热点采集

DailyHotApi 是第一层热点发现入口，只负责快速定位热点标题，不作为详情来源。

第一版建议采集平台：

```text
国内大众：
- weibo
- baidu
- zhihu
- bilibili

国内科技商业：
- 36kr
- ithome
- juejin
- csdn

国外/技术社区：
- github
- v2ex
- hellogithub
- producthunt / hackernews 如果当前自建 DailyHotApi 支持
```

输出为 `HotRecord`：

```json
{
  "id": "hot_001",
  "source": "dailyhotapi",
  "platform": "weibo",
  "category": "domestic_social",
  "title": "某事件上热搜",
  "rank": 3,
  "hot_value": "1200000",
  "url": "https://...",
  "captured_at": "2026-06-13 20:00:00",
  "raw_payload": {},
  "fetch_status": "ok",
  "error": null
}
```

## 5. 登录态初始化流程

微博和小红书采集前必须先执行登录态检查。

```text
run-pipeline
→ check_browser_sessions
  → weibo session exists?
    → valid: continue
    → missing/expired: prompt login
  → xiaohongshu session exists?
    → valid: continue
    → missing/expired: prompt login
→ collect_details
```

登录态文件只保存在本机私有目录，例如：

```text
data/browser_state/weibo.json
data/browser_state/xiaohongshu.json
```

这些文件必须加入 `.gitignore`，不得提交到仓库。

登录初始化命令建议：

```text
make login-weibo
make login-xiaohongshu
make check-sessions
```

登录初始化行为：

1. 打开 Playwright 浏览器。
2. 提示用户手动扫码或账号登录。
3. 用户确认登录完成后保存 `storage_state`。
4. 关闭浏览器。
5. 后续采集使用保存的登录态。

采集时如果检测到登录页、验证码、滑块、风控页：

```text
fetch_status = failed
error_type = login_required | captcha_required | rate_limited
```

对应平台停止采集，其他平台继续。

## 6. 平台详情采集

### 6.1 微博 Provider

目标：采集热点在微博中的原平台语境。

流程：

```text
HotRecord.title
→ 微博登录态搜索
→ 采集前 N 条高相关微博
→ 读取正文、作者、发布时间、互动数据、评论预览
→ 保存详情、截图、HTML 快照
```

第一版限制：

- 每个话题最多采 3-5 条微博。
- 每条微博最多采 10-20 条评论预览。
- 不深翻页。
- 遇到验证码或登录失效立即停止微博采集。

### 6.2 百度 Provider

目标：采集热点对应的搜索摘要和可读结果页。

流程：

```text
HotRecord.title
→ 百度千帆搜索 API 优先
→ 百度搜索页 Playwright 兜底
→ 提取前 5 条自然结果
→ 用 Jina Reader / Firecrawl 读取结果 URL
→ 保存搜索摘要和结果页正文
```

百度搜索页本身只作为来源入口，不作为最终事实来源。

### 6.3 小红书 Provider

目标：采集热点在小红书中的笔记讨论和用户语境。

流程：

```text
HotRecord.title
→ 小红书登录态搜索
→ 采集前 N 条相关笔记
→ 读取笔记标题、正文、作者、互动数据、评论预览
→ 保存详情、截图、HTML 快照
```

第一版限制：

- 每个话题最多搜索 1 次。
- 每个话题最多采 5 条笔记。
- 不采推荐流，不做无限滚动。
- 遇到验证码、滑块、风控页立即停止小红书采集。

## 7. 详情数据存储

平台详情必须独立保存到 `platform_details.json`。

```json
{
  "detail_id": "detail_001",
  "related_hot_record_ids": ["hot_001", "hot_008"],
  "platform": "weibo",
  "source_method": "browser_session",
  "query": "某事件上热搜",
  "url": "https://...",
  "title": "某事件相关微博正文",
  "content": "采集到的正文内容...",
  "author": "作者名",
  "published_at": "2026-06-13 18:20:00",
  "metrics": {
    "likes": 1200,
    "comments": 300,
    "reposts": 80
  },
  "comments_preview": [
    "评论 1",
    "评论 2"
  ],
  "raw_snapshot_path": "data/snapshots/weibo/detail_001.html",
  "screenshot_path": "data/screenshots/weibo/detail_001.png",
  "fetched_at": "2026-06-13 20:10:00",
  "fetch_status": "ok",
  "error_type": null,
  "confidence": "medium"
}
```

百度详情可以包含 `result_urls`：

```json
{
  "detail_id": "detail_021",
  "related_hot_record_ids": ["hot_002"],
  "platform": "baidu",
  "source_method": "search_api",
  "query": "某事件 怎么回事",
  "title": "搜索结果摘要",
  "content": "百度搜索摘要和结果页正文整理...",
  "result_urls": ["https://..."],
  "metrics": {},
  "comments_preview": [],
  "fetch_status": "ok",
  "confidence": "medium"
}
```

## 8. LLM 主题归并

LLM 输入必须包含标题和详情，不允许只基于标题归并。

输入：

```text
- HotRecord 标题、平台、排名、热度
- PlatformDetail 正文
- 评论预览
- 百度搜索摘要
- 外部来源正文或摘要
```

输出 `topic_clusters.json`：

```json
{
  "topic_id": "topic_001",
  "canonical_title": "某事件引发跨平台讨论",
  "aliases": [
    "某事件上热搜",
    "某事件怎么回事",
    "小红书某事件讨论"
  ],
  "platforms": ["weibo", "baidu", "xiaohongshu"],
  "hot_record_ids": ["hot_001", "hot_008"],
  "detail_ids": ["detail_001", "detail_021", "detail_041"],
  "merge_reason": "这些标题和详情都围绕同一事件的起因、讨论和用户反馈展开。",
  "cluster_confidence": "high"
}
```

归并策略：

1. 规则预聚类：标题归一化、关键词重合、实体重合、平台重复。
2. LLM 复核：判断是否同一事件，生成 `canonical_title` 和 `merge_reason`。
3. 低置信度聚类保留为独立主题，不强行合并。

## 9. LLM 内容整理

LLM 不做文案推荐、标签推荐和发布建议，只整理热点内容。

输出 `topic_briefs.json`：

```json
{
  "topic_id": "topic_001",
  "canonical_title": "某事件引发跨平台讨论",
  "summary": "该事件因某原因在微博、百度和小红书形成讨论。",
  "key_facts": [
    "事实 1",
    "事实 2",
    "事实 3"
  ],
  "platform_discussion": {
    "weibo": "微博讨论集中在争议观点和情绪扩散。",
    "baidu": "百度搜索集中在事件背景、原因和后续。",
    "xiaohongshu": "小红书讨论集中在体验、感受和生活场景。"
  },
  "timeline": [
    {
      "time": "2026-06-13 18:00",
      "event": "事件开始扩散"
    }
  ],
  "source_evidence": [
    {
      "detail_id": "detail_001",
      "platform": "weibo",
      "evidence": "可支撑摘要的关键片段",
      "confidence": "medium"
    }
  ],
  "open_questions": [
    "仍缺少官方回应。",
    "部分平台讨论是否为二次传播仍需确认。"
  ],
  "confidence": "medium"
}
```

## 10. 输出文件

第一版运行后生成：

```text
data/raw/hot_records.json
data/details/platform_details.json
data/processed/topic_clusters.json
data/processed/topic_briefs.json
reports/daily_topic_digest.md
```

Markdown 汇总结构：

```md
# 每日热点内容汇总

## 今日概览
- 采集热榜平台：
- 采集详情数量：
- 聚合主题数量：
- 高置信度主题数量：

## 1. 某事件引发跨平台讨论

### 摘要

### 合并来源

### 关键事实

### 平台讨论差异

### 详情证据

### 待确认问题

### 综合置信度
```

## 11. 推荐目录结构

```text
data/
  raw/
    hot_records.json
  details/
    platform_details.json
  processed/
    topic_clusters.json
    topic_briefs.json
  browser_state/
  snapshots/
    weibo/
    baidu/
    xiaohongshu/
  screenshots/
    weibo/
    baidu/
    xiaohongshu/

reports/
  daily_topic_digest.md

src/
  collectors/
    daily_hot_collector.py
    weibo_provider.py
    baidu_provider.py
    xiaohongshu_provider.py
  browser/
    session_manager.py
    page_guards.py
  details/
    detail_schema.py
    detail_store.py
  clustering/
    topic_clusterer.py
  summarization/
    topic_brief_generator.py
  reports/
    daily_digest_renderer.py
```

`data/browser_state/`、`data/snapshots/`、`data/screenshots/` 需要作为本地运行产物处理，登录态文件不得进入 git。

## 12. 运行命令

分步运行：

```text
make check-sessions
make login-weibo
make login-xiaohongshu
make collect-hot
make collect-details
make cluster-topics
make generate-digest
```

一条命令：

```text
make run-pipeline
```

`run-pipeline` 行为：

1. 检查微博和小红书登录态。
2. 如果缺失或失效，提示先执行登录命令。
3. 登录态有效后继续采集详情。
4. 百度如果 API Key 缺失，则用浏览器搜索兜底。
5. 任何平台失败都记录错误，不中断全局流程。

## 13. 验证标准

第一版完成后应满足：

- 能通过 DailyHotApi 采集多平台热点标题。
- 能采集并保存微博、百度、小红书的具体详情。
- 详情数据独立保存在 `platform_details.json`。
- 登录态缺失时会先提醒登录，不会静默失败。
- 遇到验证码或风控时停止对应平台并记录错误。
- LLM 能把同主题热点归并成 `topic_clusters.json`。
- LLM 能基于详情生成 `topic_briefs.json`。
- 能输出人工可读的 `reports/daily_topic_digest.md`。

## 14. 后续扩展

第二版再考虑：

- 每日定时自动运行。
- SQLite 或 Postgres 替代纯 JSON。
- 对外 HTTP API。
- MCP Server。
- 接入上层大项目。
- 文案生成和标签推荐。
