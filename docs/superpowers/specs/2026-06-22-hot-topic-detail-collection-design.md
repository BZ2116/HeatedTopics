# Hot Topic Detail Collection Design

## 1. 目标

第一版目标是完成一个稳定的热点详情收集闭环：

```text
选择采集窗口
→ 获取当日或近 7 天热点话题
→ 去重并形成候选话题
→ 为每个话题采集详细信息
→ 将详细信息保存为可追溯证据
→ 输出 JSON 和 Markdown 汇总
```

第一版必须确保系统拿到的不只是热点标题，而是每个话题对应的详细内容。后续分析、复杂检索词拆解、事实核验、可信度评分、长期专题研究和 skill/agent 封装都放到后续版本。

## 2. 第一版范围

### 2.1 包含

- 支持 `today` 和 `last_7_days` 两种采集窗口。
- 从 DailyHotApi 或已有热榜入口收集多平台热点标题。
- 对同一窗口内的热点标题做基础去重。
- 为每个候选热点采集详细信息。
- 将每条详情保存为 `DetailEvidence`。
- 记录详情来源、查询词、正文、链接、采集时间、采集状态和原始载荷。
- 输出机器可读 JSON 和人工可读 Markdown。

### 2.2 不包含

- 不做复杂事实核查。
- 不做可信度综合评分。
- 不做自动分析观点、立场或情绪。
- 不做社交平台文案生成。
- 不做自动发布。
- 不做定时任务。
- 不做 MCP Server 或完整 skill 封装。
- 不绕过验证码、登录限制或平台风控。

## 3. 设计原则

1. **详情优先**：热点标题只用于发现，最终交付必须包含详情正文或详情摘要。
2. **证据单独保存**：每个详情来源都保存为独立 `DetailEvidence`，不要只写进最终报告。
3. **采集失败可见**：如果某个平台拿不到详情，必须记录 `fetch_status` 和 `error_type`。
4. **先稳定再扩展**：第一版优先保证可运行、可复查、可迭代，不追求复杂分析。
5. **登录与风控前置**：需要登录的平台先检查登录态，遇到验证码或风控立即停止该平台采集。

## 4. 数据流

```text
run-detail-collection --window today
  → collect_hot_records
  → deduplicate_topics
  → collect_topic_details
  → write detail_evidence.json
  → render recent_hot_topics_digest.md
```

近 7 天窗口可以复用同一流程：

```text
run-detail-collection --window last_7_days
  → load or collect recent hot records
  → merge repeated topics across days
  → collect missing details
  → write evidence and report
```

## 5. 热点收集

热点入口沿用现有项目中的 DailyHotApi 方案。

第一版建议保留这些来源：

- 大众热点：`weibo`、`baidu`、`zhihu`、`toutiao`
- 科技商业：`36kr`、`ithome`、`juejin`、`csdn`
- 技术社区：`github`、`hellogithub`
- 内容热度：`bilibili`

输出继续使用 `HotRecord`：

```json
{
  "id": "hot_weibo_001",
  "source": "dailyhotapi",
  "platform": "weibo",
  "route": "weibo",
  "category": "core_discovery",
  "title": "热点标题",
  "rank": 1,
  "hot_value": "123456",
  "url": "https://example.com",
  "captured_at": "2026-06-22T20:00:00+08:00",
  "fetch_status": "ok",
  "error_type": null
}
```

## 6. 基础去重

第一版只做轻量去重，不做复杂主题聚类。

去重规则：

- 去除标题首尾空白。
- 统一大小写。
- 去除常见热搜装饰词，例如 `热`、`爆`、`新`、`荐`。
- 去除多余空格和常见标点。
- 同一规范化标题只保留一个候选话题。
- 如果多个平台出现同一标题，保留所有 `hot_record_ids`，但只生成一个候选话题。

输出可以使用现有 `TopicCluster`，也可以先使用简化的候选话题结构。为了减少改动，建议复用现有 `TopicCluster`。

## 7. 详情采集

第一版详情采集必须至少覆盖搜索详情来源。登录类平台能采到则采，采不到则记录状态，不阻塞全局流程。

### 7.1 百度 / 网页搜索详情

这是第一版最重要的详情来源。

每个话题至少执行以下查询：

```text
{title}
{title} 怎么回事
{title} 最新进展
```

采集内容：

- 搜索结果标题
- 搜索结果摘要
- 结果 URL
- 可读取页面正文或正文摘要
- 采集时间
- 原始搜索结果载荷

如果 API 不可用，可以使用现有浏览器兜底或先保存搜索摘要。第一版验收重点是详情可用，不要求所有网页正文都完整读取。

### 7.2 微博详情

微博是核心热点现场来源，但可能受登录态和风控影响。

采集策略：

- 采集前检查微博登录态。
- 登录态有效时，搜索热点标题。
- 只读取首屏或前 3-5 条相关内容。
- 保存正文、链接、互动指标和评论预览。
- 遇到登录失效、验证码或风控，记录状态并停止微博采集。

### 7.3 小红书详情

小红书用于补充生活方式、消费、体验类热点语境。

采集策略：

- 采集前检查小红书登录态。
- 登录态有效时，搜索热点标题。
- 只读取首屏或前 3-5 条相关笔记。
- 保存标题、正文、链接、互动指标和评论预览。
- 遇到登录失效、验证码或风控，记录状态并停止小红书采集。

### 7.4 辅助详情

DailyHotApi 自带的 `desc`、`url`、`hot_value` 可以保存为辅助证据，但不能替代详情证据。

## 8. DetailEvidence 合同

第一版继续使用现有 `DetailEvidence`。

```json
{
  "evidence_id": "evidence_baidu_hot_weibo_001",
  "topic_key": "热点标题",
  "related_hot_record_ids": ["hot_weibo_001"],
  "platform": "baidu",
  "source_role": "required",
  "source_method": "search_results",
  "query": "热点标题 怎么回事",
  "url": "https://example.com/detail",
  "title": "详情标题",
  "content": "采集到的详情正文或搜索摘要",
  "author": "",
  "published_at": "",
  "metrics": {},
  "comments_preview": [],
  "result_urls": ["https://example.com/detail"],
  "raw_snapshot_path": "",
  "screenshot_path": "",
  "fetched_at": "2026-06-22T20:10:00+08:00",
  "fetch_status": "ok",
  "error_type": null,
  "confidence": "medium",
  "raw_payload": {}
}
```

第一版 `content` 不能为空才算采集到有效详情。只有标题、热度或排名不算有效详情。

## 9. 输出文件

第一版输出：

```text
data/raw/dailyhot_records.json
data/processed/topic_clusters.json
data/evidence/detail_evidence.json
reports/recent_hot_topics_digest.md
```

如果后续需要保留运行窗口元信息，可以增加：

```text
data/processed/detail_collection_runs.json
```

## 10. Markdown 报告

报告先保持朴素可读，重点展示详情是否采到。

```md
# 近期热点详情汇总

- 采集窗口：today
- 热点数量：
- 去重后话题数量：
- 有详情话题数量：
- 缺失详情话题数量：

## 1. 热点标题

### 热榜来源

- weibo：排名 1，热度 123456
- baidu：排名 3，热度 98765

### 详细信息

- 来源：baidu
- 查询词：热点标题 怎么回事
- 链接：https://example.com
- 内容摘要：……

### 平台详情状态

- baidu：ok
- weibo：login_required
- xiaohongshu：empty_content
```

## 11. 命令设计

建议增加一个第一版主命令：

```bash
make collect-recent-hot-details
```

或 Python CLI：

```bash
python -m src.core_pipeline.run collect-recent-details --window today
python -m src.core_pipeline.run collect-recent-details --window last_7_days
```

第一版命令职责：

1. 收集热点。
2. 去重话题。
3. 采集详情。
4. 写入 `detail_evidence.json`。
5. 渲染 Markdown 报告。

## 12. 验收标准

第一版完成后应满足：

- 能运行 `today` 窗口并生成热点列表。
- 能运行 `last_7_days` 窗口，至少能读取或合并近 7 天已有热点记录。
- 每个候选话题都会尝试采集详情。
- 采集成功的话题在 `detail_evidence.json` 中有非空 `content`。
- 采集失败的话题有明确 `fetch_status` 和 `error_type`。
- Markdown 报告能区分“已有详情”和“只有标题/缺失详情”。
- DailyHotApi 的标题、排名和热度只作为发现信息，不被当成详细内容。

## 13. 后续版本

后续再扩展：

- 更系统的检索词拆解。
- 官方来源和媒体来源识别。
- 多来源事实核验。
- 可信度评分。
- 时间线生成。
- 长期趋势跟踪。
- skill 或 agent 封装。
