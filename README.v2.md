# HeatedTopics v2 — 搜索发现增强

> **v2 文档**：聚焦 `src/search_discovery/` 包的 v2 改动（基于 master 的搜索发现能力 + Hunter 风格 GitHub 检索 + 国内信源 + 推荐冷却历史）。DailyHot 热榜采集和核心 pipeline 部分未变化，参见根 `README.md`。

## v2 改了什么

| 维度 | master | v2 |
| --- | --- | --- |
| GitHub 检索元数据 | 只取 `stargazers_count` | 完整 `metrics`：`stars` / `forks` / `watchers` / `open_issues` / `language` / `topics` / `pushed_at` / `updated_at` / `license` |
| GitHub 查询 | 静态模板 `in:name,description stars:>50` | Hunter 风格 builder：`in:name,description,readme stars:>200 pushed:>YYYY-MM-DD [language:X]`，日期按 `today - days_since_update` 动态计算 |
| 国内信源 | 只有 baidu_qianfan_search / news_api_cn | 新增 tianapi_news 和 qiniu_web_search；news_trend / deep_article / product_trend 三种意图下国内信源优先于 GitHub |
| 推荐去重 | 无 | 持久化历史 `data/search_discovery/history/recommended_topics.json`；冷却期（默认 30 天）内 GitHub 结果在 raw row、topic source_hits、报告 evidence 三处标 `recently_recommended` |
| 报告 evidence | `github_search` [title](url) | `github_search` [title](url) `(stars: 1200, forks: 88, language: Python, updated: ..., recently recommended)` |

**未引入：** Hunter AI 包本体、Gradio UI、ChromaDB、Twitter/X / Reddit / 小红书登录采集、auto-publish。v2 仍然只是 Search API 驱动的话题发现。

## 快速开始

```bash
cd E:\.code\My\heatedTopics\heatedTopics
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' uv run pytest tests/search_discovery -q
```

跑一次端到端：

```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

输出（按文件）：

| 路径 | 内容 |
| --- | --- |
| `data/search_discovery/raw/search_results.jsonl` | 归一化后的搜索源结果，含完整 `metrics` 和 `recently_recommended` 标志 |
| `data/search_discovery/evidence/search_content_evidence.jsonl` | 摘要或正文补全证据 |
| `data/search_discovery/processed/search_topic_index.json` | 候选话题索引；每个 source_hit 都带 `metrics` 和 `recently_recommended` |
| `data/search_discovery/history/recommended_topics.json` | 推荐历史快照（自动写入，下次运行读取） |
| `reports/search_discovery/search_topic_recommendations.md` | 创作者检索报告，evidence 行展示 stars/forks/language/updated/recently recommended |

## 环境变量

`.env` / `.env.example` 新增两个 key（缺失时对应 provider 在 raw results 里以 `fetch_status=mock_unavailable` 出现，不阻断其他源）：

```text
# TianAPI news (https://www.tianapi.com/)
TIANAPI_KEY=

# Qiniu Web Search (https://www.qiniu.com/)
QINIU_WEB_SEARCH_API_KEY=
```

已有的 `GITHUB_TOKEN` / `BOCHA_API_KEY` / `BAILIAN_API_KEY` / `QIANFAN_API_KEY` / `QIANFAN_SECRET_KEY` 行为不变。

## Search API 配置助手

v2 新增 `src.search_discovery.config_api` CLI，专门管 `.env` 里的搜索 API key。核心特点：**保存即测**，确认写入 `.env` 后立刻跑一次连通性测试，立即反馈 key 是否可用。

### 支持的 source

| source_id | display_name | env_keys |
| --- | --- | --- |
| `github_search` | GitHub Search | `GITHUB_TOKEN` |
| `news_api_cn` | Bocha AI Search | `BOCHA_API_KEY` |
| `juejin_content` | Aliyun Bailian Web Search | `BAILIAN_API_KEY` |
| `baidu_qianfan_search` | Baidu Qianfan Search | `QIANFAN_API_KEY`, `QIANFAN_SECRET_KEY` |
| `tianapi_news` | TianAPI News | `TIANAPI_KEY` |
| `tavily_search` | Tavily Search | `TAVILY_API_KEY` |
| `qiniu_web_search` | Qiniu Web Search | `QINIU_WEB_SEARCH_API_KEY` |

每个 source 的注册地址和默认 test query 在 `src/search_discovery/api_config.py::api_source_configs()` 里。

### 命令

| 命令 | 作用 |
| --- | --- |
| `--list` | 列出全部 source，已配置的 key 显示掩码 (`ghp_****blW0`)，缺失的显示 `[MISS]` |
| `--set SOURCE_ID` | 交互式配置单个 source：提示输入每个 env_key → 确认 `[y/N]` → 保存 → 立刻连通性测试 |
| `--wizard` | 自动遍历所有未配齐的 source，逐个走 `--set` 流程 |
| `--test SOURCE_ID` | 不写盘，仅对已存在的 key 跑一次连通性测试 |

### 用法

查看现状：

```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run python -m src.search_discovery.config_api --list
```

输出示例（已配的会被掩码，不会打印完整 key）：

```text
Search API Configuration

[OK]   github_search          GITHUB_TOKEN=ghp_****blW0
[MISS] tavily_search          missing: TAVILY_API_KEY
[OK]   baidu_qianfan_search   QIANFAN_API_KEY=bce-****9d02, QIANFAN_SECRET_KEY=bce-****1def
```

单 source 配置（保存后自动测）：

```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run python -m src.search_discovery.config_api --set tavily_search
```

流程：

```text
Configuring Tavily Search
Open: https://app.tavily.com/home

TAVILY_API_KEY: tvly_xxxx
Save these keys to .env? [y/N] y
[OK] Saved TAVILY_API_KEY
[TEST] Testing tavily_search with query: AI Agent 最新进展
[OK] tavily_search connected successfully, returned 10 results.
```

拒绝确认则不写盘：

```text
Save these keys to .env? [y/N] n
Cancelled.
```

一次性配齐所有缺失项：

```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run python -m src.search_discovery.config_api --wizard
```

只测不写（改完 `.env` 后验证）：

```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run python -m src.search_discovery.config_api --test tavily_search
```

### 连通性状态语义

`test_source_connection()` 返回 `ConnectionTestResult`，状态字段含义：

| status | 含义 | 建议 |
| --- | --- | --- |
| `ok` | provider 已配置且 query 正常返回 | 无需处理 |
| `missing_key` | `.env` 里没有对应的 key，或 key 为空 | 走 `--set` 配 key |
| `auth_failed` | 鉴权失败（401 / token 过期 / 千帆 token 兑换失败等） | 检查 key 是否过期或配额 |
| `upstream_failed` | 上游 5xx / 网络层失败 | 重试或换时段 |
| `parse_failed` | 返回内容无法解析 | 排查 provider 协议变更 |
| `empty_result` | provider 配置 OK 但 query 没结果 | 通常无害，可能是分词过窄 |

`--set` / `--wizard` 在 `status != "ok"` 时退出码 1，方便 CI 检查。

### `.env` 安全

- `mask_secret(value)`：空值 → `<empty>`；≤4 字符 → `***`；其他 → `{前4}****{后4}`。`--list` 永远不打印完整 key。
- `upsert_env_values()`：保留原有注释、空行、未涉及的 key；只替换或追加传入的 key。原 `.env` 的结构基本不变。
- `ensure_env_file()`：首次运行自动从 `.env.example` 复制生成 `.env`，避免手动新建。

## 路由规则

`build_search_routes()` 根据 `classify_search_intent()` 的结果选路：

| Intent | 触发条件（关键词命中） | 选路 |
| --- | --- | --- |
| `tech_project` | github / 开源 / 框架 / sdk / mcp / rag / 开发者工具 等 | 走 `PROFILE_BASE_WEIGHTS` 默认源（含 github_search + juejin_content + baidu_qianfan_search + news_api_cn） |
| `tech_article` | 教程 / 实践 / 案例 / 源码 / 部署 / 架构 | 同上，但 github 权重被 `INTENT_BOOSTS` 下调 |
| `news_trend` | 新闻 / 最新 / 发布 / 融资 / 政策 / 行业 | **tianapi_news → news_api_cn → baidu_qianfan_search → qiniu_web_search**，github_search 兜底（max(5, weight-30)） |
| `deep_article` | 分析 / 解读 / 复盘 / 观点 / 原因 / 影响 | **baidu_qianfan_search → news_api_cn → qiniu_web_search → juejin_content**，github 兜底 |
| `product_trend` | 产品 / 应用 / 商业化 / saas / 工具 | **baidu_qianfan_search → news_api_cn → tianapi_news → qiniu_web_search**，github 兜底 |
| `content_angle` | 兜底 | 同 `tech_article` 风格（默认权重） |

每条 route 一条 source-specific query：plan 文件里禁止"一个 source 多 query"。

## 冷却历史

`src/search_discovery/history.py` 是核心模块，导出 4 个 helper：

```python
read_recommendation_history(path)   # 读 history；文件不存在返回 {}
write_recommendation_history(path, data)   # 写 history（ensure_ascii=False, sort_keys=True）
mark_recent_recommendations(results, history=..., now=..., cooldown_days=30)
update_recommendation_history(history, results, recommended_at=...)
```

CLI 流程：
1. 读 `data/search_discovery/history/recommended_topics.json`（首次不存在则空 dict）
2. **在 `enrich_results()` 和 `cluster_results()` 之前**调用 `mark_recent_recommendations()`，把 `metrics.recently_recommended` / `metrics.last_recommended_at` 写入每条 result
3. `cluster_results()` 复制 metrics 到 `source_hits[i].metrics` 和 `source_hits[i].recently_recommended`
4. `render.py` 的 `_hit_suffix()` 在 evidence 行追加 `(stars: ..., recently recommended)` 片段
5. 报告生成后 `update_recommendation_history()` + `write_recommendation_history()` 写回

冷却判定：`(now - recommended_at) <= 30 days`。`recommended_at` 支持 ISO8601 带/不带 tzinfo；不带时按 UTC 解析。

调整冷却期：改 `cli.py` 里的 `cooldown_days=30` 参数和 `history.py` 的默认值。

## Provider 接口约定

新加 provider 走标准 `BaseHTTPSearchProvider`：

```python
class XxxProvider(BaseHTTPSearchProvider):
    source_id = "xxx_xxx"
    rpm_limit = 60
    timeout_seconds = 10.0

    def __init__(self, *, api_key: str, transport=None): ...
    @classmethod
    def from_env(cls) -> "XxxProvider | None": ...
    def _build_request(self, query) -> httpx.Request: ...
    def _parse_response(self, response, query) -> list[dict]: ...
```

注册到 `src/search_discovery/cli.py::_REAL_PROVIDER_CLASSES` 即生效；`MockProvider(source_id, rows=[])` 是无 key 时的回退占位。

## 测试

`tests/search_discovery/` 共 108 个测试（v2 累计新增 36 个）：

- `test_providers_github.py` — 含 `test_search_rows_parses_rich_repo_metadata`（10 字段 metrics）
- `test_github_query.py` — 关键词限长 5、`pushed:>` 注入、language 可选
- `test_routing.py` — 含 `test_github_route_uses_hunter_style_query` 和国内信源顺序
- `test_domestic_sources.py` — news_trend 优先级、source-specific query 模板、business profile 路由
- `test_providers_tianapi.py` / `test_providers_qiniu.py` — code != 200/0 时返回 error_row
- `test_history.py` — read/write/mark 三件套
- `test_cli.py` — 含 `test_run_discovery_command_marks_recent_github_recommendations`，断言 raw row、topic source_hits、history 三处都被同步
- `test_api_config.py` — source 元数据、KeyError、mask_secret 行为
- `test_env_file.py` — `.env` 复制、读、upsert 三件套
- `test_connectivity.py` — `missing_key` / `ok` / provider error_row 三种结果
- `test_config_api.py` — `--list` 掩码、`--set` 保存即测、`--set` 拒绝不写盘

跑特定文件：
```bash
PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics' \
  uv run pytest tests/search_discovery/test_history.py -q
```

## 已知边界

- GitHub 未配置 token 时，rate limit 60 req/h；本项目每个 profile 一次运行 1 个 GitHub query，不会撞限
- TianAPI / 七牛 / 博查 / 千帆 / 阿里百炼 任一缺失不会阻塞其他源；缺失的 provider 写入 `fetch_status=mock_unavailable` 的占位 row
- 冷却历史只过滤 GitHub 列表结果；国内信源不受冷却影响（新闻类话题时效性强）
- v2 没有把冷却信息写进 cluster 排序权重；只是"标记+展示"，不做降权。如果要降权，改 `cluster_results()` 里 `_source_hits()` 之后的 `score_topic()` 调用前一步即可

## 相关文档

- 设计计划：`docs/superpowers/plans/2026-06-29-hunter-ai-github-enhancement.md`
- 配置助手实施计划：`docs/superpowers/plans/2026-06-30-search-api-config-assistant.md`
- 决策参考：Hunter AI（`Pangu-Immortal/hunter-ai-content-factory`）的 `github_hunter.py` / `github_trending.py` 思路，仅借鉴不引入
