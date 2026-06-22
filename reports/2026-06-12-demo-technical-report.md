# Hot Topic Demo — 技术汇报

> 2026-06-12

## 1. 目标

构建一条端到端 pipeline：采集国内热榜 → 筛选重点话题 → 读取可访问来源 → 生成 Markdown/HTML 简报。

## 2. 技术架构

```
DailyHotApi (本地 Node.js 服务)
        ↓
Python CLI (src/demo_collect_hot_topics.py)
        ↓
  ┌─────┴─────┐
  ↓ ↓
fetch select
  ↓           ↓
enrich     build_cards
  ↓           ↓
sources render
              ↓
          reports/
```

## 3. 技术栈

| 层级 | 技术 |
|------|------|
| 热榜聚合 | DailyHotApi（imsyy/DailyHotApi）本地运行，端口 6688 |
| 数据采集 | Python 标准库 `urllib.request`，支持多 API base fallback |
| 数据建模 | `dataclasses`（HotRecord、SelectedTopic、TopicSource、TopicCard） |
| 话题选择 | 规则引擎：跨平台去重 + 排名评分 + 关键词加权 |
| 来源丰富 | Jina Reader（`r.jina.ai`）读取详情页 |
| 报告生成 | 纯 Python字符串模板，Markdown + 静态 HTML 输出 |
| 错误恢复 | API 请求失败时使用缓存数据；来源读取失败时降级为 fallback |

## 4. 核心模块

### fetch_hot_lists.py
- 遍历 PLATFORMS 列表（weibo/baidu/zhihu/bilibili/36kr/ithome）
- 每个平台取 TOP_N_PER_PLATFORM=10 条记录
- 支持 `DAILY_HOT_API_BASES` 多 base 切换（`api-hot.imsyy.top` → `dailyhot.imsyy.top`）
- 失败时记录 FetchIssue，不中断整个流程

### select_topics.py
- `normalize_title_key()` — 去除空格 + 英文小写，消除跨平台标题差异
- `keyword_bonus()` — AI/人工智能/大模型/商业/融资 等关键词 +5 分
- `cross_platform_bonus` — 每跨一个平台 +30 分
- `rank_score` — 排名越靠前分数越高（20 - rank，最低0）
- 按 score 降序返回 Top 8

### enrich_sources.py
-优先用 `r.jina.ai/{url}` 读取详情页
- 内容 >= 120 字符视为成功
- 失败时返回 fallback 状态，内容为"未能稳定读取详情页..."

### generate_reports.py
- `build_cards()` — 合并 topic + source 生成 TopicCard
- `render_topic_cards()` — 生成话题详情卡 Markdown
- `render_daily_digest()` — 生成每日简报 Markdown，含：今日概览、重点热点、跨平台共同热点、建议继续跟踪、数据来源说明
- `render_static_html()` — 将 Markdown 转成带样式的静态 HTML

## 5. 数据模型

```
HotRecord        # 原始热榜记录（platform/rank/title/hot/url/crawl_time）
    ↓
SelectedTopic # 筛选后话题（title/platforms/ranks/urls/score）
    ↓
TopicSource      # 来源详情（title/source_url/content_preview/status）
    ↓
TopicCard       # 最终话题卡（title/platforms/ranks/summary/background/why_hot/confidence）
```

## 6. 输出文件

| 文件 | 说明 |
|------|------|
| `data/hot_list.json` | 原始热榜记录（60 条） |
| `data/selected_topics.json` | 精选话题（8 条） |
| `data/topic_sources.json` | 来源详情（8 条） |
| `reports/hot_topic_cards.md` | 8 张话题详情卡 |
| `reports/daily_digest_demo.md` | 每日简报 |
| `reports/daily_digest_demo.html` | HTML 版简报 |

## 7. 置信度说明

- **medium** — Jina Reader 成功读取详情页且 status=ok
- **low** — 详情页读取失败，使用 fallback 内容

当前 Demo 所有卡片均为 low，因为微博等平台 URL 需要登录态，Jina Reader 无法访问。

## 8. 一键执行

```bash
/Users/BZ/code/heatedTopics/tools/run-demo.sh
```

## 9. 后续扩展方向

1. **LLM 增强** — 用 `OPENAI_API_KEY` 环境变量触发，替代模板填充，生成真正的 summary/background/why_hot
2. **定时任务** — 配合 cron 定时采集，支持历史追踪
3. **详情源扩展** — 接入需要登录态的来源（如微博正文页）
4. **MCP Server** — 封装为 MCP Tool，供 Agent 调用
5. **数据库** — 持久化历史热榜，支持趋势分析

## 10. 当前局限

- 依赖本地运行的 DailyHotApi 服务
- Jina Reader 无法读取需要登录的详情页
- 话题选择使用规则引擎，非 ML 模型
- LLM 生成尚未实现（计划中的 Task 7）