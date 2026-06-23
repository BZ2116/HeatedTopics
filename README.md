# HeatedTopics

HeatedTopics 是一个热点话题采集和详情证据整理项目。它会先通过 DailyHot 获取多平台热榜，再对重点平台补充更具体的网页详情，最后生成可读的热点报告。

## 当前采集策略

项目目前分成两层采集：

1. 话题发现：继续使用 DailyHot API 采集所有已配置来源。
2. 详情采集：只对微博、百度、小红书、Bilibili、掘金做进一步详情补充。

其他来源仍然会保留在话题聚合和报告排布里，但不额外打开网页抓详情，以减少运行时间、降低请求频率，也避免不必要的登录和风控风险。

重点平台如下：

| 平台 | 详情策略 |
| --- | --- |
| 百度 | 直接搜索详情；遇到安全校验时尝试 Playwright 浏览器兜底 |
| 微博 | 使用已保存登录态的 Playwright 会话访问和抽取页面详情 |
| 小红书 | 使用已保存登录态的 Playwright 会话访问和抽取页面详情 |
| Bilibili | 使用热榜元数据补充视频类详情 |
| 掘金 | 使用 DailyHot 元数据补充技术类详情 |

## 安装和验证

推荐在项目目录运行：

```powershell
cd E:\.code\My\heatedTopics\heatedTopics
uv run pytest tests -q
```

如果需要显式设置模块路径：

```powershell
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

登录信息保存在 `data/browser_state/`，该目录不应提交到 Git。现在即使微博或小红书没有登录，主流程也会继续运行；缺失登录态的平台会被记录为提醒，其他可采集平台不会被阻断。

## 运行采集

采集今天的热点和详情：

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

只指定详情平台：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-recent-details --window today --detail-platforms baidu,weibo,xiaohongshu
```

`--detail-platforms` 只控制详情采集平台，不会改变 DailyHot 的整体话题发现范围。

## 缓存机制

项目会把 DailyHot 结果和详情证据写入本地缓存，默认有效期为 7 天。相同窗口和相同查询在一周内再次执行时，会优先读取缓存，避免重复访问 API 或网页。

常用行为：

| 场景 | 行为 |
| --- | --- |
| 普通运行 | 优先使用 7 天内缓存 |
| 添加 `--refresh` | 跳过读取缓存，重新采集并覆盖缓存 |
| 删除 `data/cache/` | 清空本地缓存，下次运行重新采集 |

缓存目录为 `data/cache/`，已在 `.gitignore` 中忽略。

## 输出文件

一次完整采集会写入这些主要文件：

| 路径 | 内容 |
| --- | --- |
| `data/raw/dailyhot_records.json` | DailyHot 原始热榜记录 |
| `data/processed/topic_clusters.json` | 去重和聚类后的话题 |
| `data/evidence/detail_evidence.json` | 详情证据汇总 |
| `data/evidence/detail_evidence_raw.jsonl` | 详情证据原始行记录 |
| `reports/recent_hot_topics_digest.md` | 最终热点报告 |
| `data/cache/` | 7 天缓存数据 |

## 风控和安全边界

项目当前采用低频、缓存优先、登录态复用的方式降低重复访问。遇到验证码、登录墙、安全校验或明显风控页面时，采集器会记录该平台的问题并继续处理其他平台。

项目不实现验证码绕过、账号规避检测、指纹伪装、代理池轮换或其他可能违反平台规则的策略。微博和小红书建议使用稳定、人工登录后的浏览器会话，并控制运行频率。

## 开发文档

相关设计和执行计划：

- `docs/superpowers/specs/2026-06-23-detail-cache-and-session-safety-design.md`
- `docs/superpowers/plans/2026-06-23-detail-cache-and-session-safety.md`

## 常见问题

### 为什么报告里不是所有来源都有网页详情？

这是当前的性能和风控取舍。DailyHot 仍会采集所有来源的话题；只有微博、百度、小红书、Bilibili 和掘金会进入详情采集。

### 微博或小红书没登录会怎样？

流程不会崩溃。对应平台会被标记为缺少登录态并跳过，百度、Bilibili、掘金以及其他 DailyHot 话题仍会继续处理。

### 如何彻底重新跑一遍？

可以先清理缓存，再使用 `--refresh`：

```powershell
Remove-Item -LiteralPath data\cache -Recurse -Force
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.core_pipeline.run collect-recent-details --window today --refresh
```
