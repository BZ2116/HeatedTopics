# 2026-06-24 新数据结构规划

## 目标

旧版本采集结果、缓存、浏览器状态和报告已迁入本地归档目录：

`local_archive/previous-data-2026-06-24/`

该目录只作为本机回溯使用，不参与上传。后续新数据从空的 `data/` 和 `reports/` 目录重新生成，并统一按当前详情 raw 格式输出。

## 新目录职责

`data/raw/dailyhot_records.json`

保存热点发现阶段的原始热榜记录。每条记录仍使用 `HotRecord.to_dict()` 的完整结构，作为后续详情补采、去重、补齐 `cover/hotvalue/rank` 的基础数据。

`data/evidence/detail_evidence.json`

保存详情证据的完整内部结构。这里保留 `DetailEvidence` 的完整字段，供报告、调试、缓存和完整证据链使用。

`data/evidence/detail_evidence_raw.jsonl`

保存面向外部使用的精简 raw 数据。一行一个 JSON 对象，只允许以下字段：

```json
{
  "source": "weibo",
  "url": "https://example.com/post",
  "title": "热点标题",
  "content": "页面或详情侧抓到的完整文本",
  "cover": "https://example.com/cover.jpg",
  "hotvalue": "100万",
  "rank": 1
}
```

`data/processed/topic_clusters.json`

保存去重后的话题簇，只放聚合索引字段，不放长正文。

`reports/recent_hot_topics_digest.md`

保存人工阅读报告。报告是派生产物，可以随时重跑生成，不作为 raw 数据来源。

## raw 字段合约

`source`

热点来源平台，例如 `baidu`、`weibo`、`xiaohongshu`、`bilibili`、`juejin`。来自详情证据的 `platform`。

`url`

优先使用详情结果 URL，其次使用证据 URL，再次使用热榜原始 URL 或移动端 URL。

`title`

优先使用对应热榜记录的原始标题，找不到热榜记录时退回详情 query 或 evidence title。

`content`

不再输出截断摘要。取值优先级为：

1. `raw_payload.raw_page_text`
2. `raw_payload.browser_raw.page_text`
3. `raw_payload.search_results` 的完整标题、摘要、URL 拼接
4. `raw_payload.posts` 或 `raw_payload.notes` 的完整内容拼接
5. `DetailEvidence.content`

`cover`

来自热榜记录的 `cover`。详情证据本身不负责生成封面。

`hotvalue`

来自热榜记录的 `hot_value`，外部字段名固定为 `hotvalue`。

`rank`

来自热榜记录的 `rank`。如果是补采来源，使用补采记录的排名。

## 采集流程

1. 热点发现：`collect_dailyhot_records` 拉取 DailyHot route；小红书 DailyHot 为空时，用今日热榜/TopHub 等榜单来源补采热榜种子。
2. 话题去重：`deduplicate_hot_records` 用热榜记录生成 topic。
3. 详情采集：按平台采集详情；微博用浏览器登录态抓搜索页博文和完整 `page_text`；小红书详情只写入外部笔记项目占位；百度保留搜索结果并尽量抓取结果页正文。
4. 完整证据写入：`detail_evidence.json` 保留内部完整结构。
5. 外部 raw 写入：`raw_detail_rows()` 将 evidence 和 hot records 合并成七字段 JSONL。
6. 报告生成：报告只消费 evidence/topic，不反向作为 raw 数据来源。

## 推荐命令

重新采集核心三平台热点和详情：

```bash
uv run python -m src.core_pipeline.run collect-core-hot-details --window today --refresh
```

只跑普通近期详情：

```bash
uv run python -m src.core_pipeline.run collect-recent-details --window today --refresh
```

指定详情平台：

```bash
uv run python -m src.core_pipeline.run collect-recent-details --window today --refresh --detail-platforms baidu,weibo,xiaohongshu
```

## 上传边界

不上传：

- `local_archive/`
- `data/browser_state/`
- `data/cache/`
- `data/raw/`
- `data/evidence/`
- `data/processed/*.json`
- 运行生成的 `reports/recent_hot_topics_digest.md`

可以上传：

- `src/`
- `tests/`
- `docs/`
- `README.md`
- `pyproject.toml`
- `uv.lock`

## 后续检查点

新数据跑完后，先检查 `data/evidence/detail_evidence_raw.jsonl`：

1. 每行只有七个字段：`source/url/title/content/cover/hotvalue/rank`
2. `content` 不是摘要字段，也不是被截断的 5 条详情片段
3. 微博在登录态可用时应优先保留页面全文；小红书应保留话题、热度、排序和详情占位，暂不抓取笔记正文
4. `cover/hotvalue/rank` 能从对应热榜记录补齐
