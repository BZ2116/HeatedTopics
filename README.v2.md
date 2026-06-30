# HeatedTopics v2 使用说明

v2 是 HeatedTopics 的「搜索发现增强」链路，核心代码在 `src/search_discovery/`。它从创作者画像出发，自动生成搜索 query，路由到 GitHub、博查、阿里百炼、百度千帆、天聚数行、Tavily、七牛等搜索源，最后输出候选选题索引和 Markdown 推荐报告。

它不替代 `README.md` 里的 DailyHot 热榜采集主流程。简单说：

- `README.md`：采集多平台热榜和详情证据。
- `README.v2.md`：用搜索 API 主动发现更适合创作者的内容选题。

## 快速开始

进入项目目录：

```powershell
cd E:\.code\My\heatedTopics\heatedTopics
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
```

安装依赖、运行测试：

```powershell
uv sync
uv run pytest tests/search_discovery -q
```

使用内置科技 AI 博主画像跑一次 v2：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-report
```

命令结束后会打印类似结果：

```json
{"evidence_count": 12, "search_results_count": 35, "topics_count": 8}
```

如果某些 API key 没有配置，对应 source 会写入 `fetch_status=mock_unavailable` 的占位结果，不会阻断其他已配置 source。

## API 配置

v2 的 API key 写在项目根目录的 `.env`。第一次运行配置助手时，如果 `.env` 不存在，会自动从 `.env.example` 复制一份。

支持的搜索源如下：

| source_id | 用途 | 环境变量 | 申请地址 |
| --- | --- | --- | --- |
| `github_search` | GitHub 仓库和开源项目发现 | `GITHUB_TOKEN` | https://github.com/settings/tokens |
| `news_api_cn` | 博查 AI 搜索，国内新闻和网页信息 | `BOCHA_API_KEY` | https://bochaai.com |
| `juejin_content` | 阿里百炼 Web Search，技术文章槽位 | `BAILIAN_API_KEY` | https://bailian.console.aliyun.com/ |
| `baidu_qianfan_search` | 百度千帆搜索，国内网页、博客、问答和新闻 | `QIANFAN_API_KEY`, `QIANFAN_SECRET_KEY` | https://console.bce.baidu.com/qianfan/ |
| `tianapi_news` | 天聚数行新闻，媒体源和发布时间 | `TIANAPI_KEY` | https://www.tianapi.com/ |
| `tavily_search` | Tavily 搜索，英文/全球网页和摘要 | `TAVILY_API_KEY` | https://app.tavily.com/home |
| `qiniu_web_search` | 七牛 Web Search，国内网页搜索兜底 | `QINIU_WEB_SEARCH_API_KEY` | https://www.qiniu.com/ |

### 查看配置状态

```powershell
uv run python -m src.search_discovery.config_api --list
```

示例输出：

```text
Search API Configuration

[OK]   github_search          GITHUB_TOKEN=ghp_****blW0
[MISS] tavily_search          missing: TAVILY_API_KEY
[OK]   baidu_qianfan_search   QIANFAN_API_KEY=bce-****9d02, QIANFAN_SECRET_KEY=bce-****1def
```

`--list` 会对已配置的 key 做脱敏展示，不会打印完整密钥。

### 配置单个 source

```powershell
uv run python -m src.search_discovery.config_api --set tavily_search
```

交互流程：

```text
Configuring Tavily Search
Open: https://app.tavily.com/home

TAVILY_API_KEY: tvly_xxxx
Save these keys to .env? [y/N] y
[OK] Saved TAVILY_API_KEY
[TEST] Testing tavily_search with query: AI Agent 最新进展
[OK] tavily_search connected successfully, returned 10 results.
```

配置助手采用「保存后立即测试」：写入 `.env` 后会立刻用默认 query 做一次连通性验证。返回码为 `0` 表示测试通过，非 `0` 表示配置失败或上游不可用。

如果不想保存后立即测试（避免烧 API 配额，或批量配完再统一验证），可以加 `--no-test-after-set`：

```powershell
uv run python -m src.search_discovery.config_api --set tavily_search --no-test-after-set
```

跳过时打印：

```text
[OK] Saved TAVILY_API_KEY
[SKIP] Test skipped (use --test tavily_search to verify later).
```

如果确认时输入 `n` 或直接回车，本次配置不会写入 `.env`：

```text
Save these keys to .env? [y/N] n
Cancelled.
```

### 配齐所有缺失 source

```powershell
uv run python -m src.search_discovery.config_api --wizard
```

`--wizard` 会按 source 列表依次检查 `.env`。已经配置完整的 source 会跳过，缺 key 的 source 会进入和 `--set` 相同的交互流程。

如果想一次性配齐所有缺失 source 后再统一测试（避免每个 source 都跑一次连通性），加 `--no-test-after-wizard`：

```powershell
uv run python -m src.search_discovery.config_api --wizard --no-test-after-wizard
```

写完后手动跑一次 `--test` 复验：

```powershell
uv run python -m src.search_discovery.config_api --test tavily_search
uv run python -m src.search_discovery.config_api --test github_search
```

### 只测试已有配置

```powershell
uv run python -m src.search_discovery.config_api --test github_search
uv run python -m src.search_discovery.config_api --test baidu_qianfan_search
```

`--test` 不会修改 `.env`，适合手动改完 `.env` 后验证 key 是否可用。

### 手动编辑 `.env`

也可以直接编辑 `.env`：

```text
GITHUB_TOKEN=
BOCHA_API_KEY=
BAILIAN_API_KEY=
QIANFAN_API_KEY=
QIANFAN_SECRET_KEY=
TIANAPI_KEY=
TAVILY_API_KEY=
QINIU_WEB_SEARCH_API_KEY=
```

注意事项：

- GitHub 搜索没有 token 时仍可访问公开搜索 API，但 rate limit 较低；建议配置 `GITHUB_TOKEN`。
- 百度千帆需要同时配置 `QIANFAN_API_KEY` 和 `QIANFAN_SECRET_KEY`。
- 任意单个 source 缺失或失败都不会让 v2 全流程崩溃，只会在结果中记录不可用状态。
- `.env` 包含密钥，不要提交到 Git。

## 运行搜索发现

基础命令：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json
```

生成 Markdown 报告：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-report
```

`--profile` 必填，指向一个创作者画像 JSON。`--render-report` 可选，开启后会额外生成可读报告。

## 输出文件

默认输出路径如下：

| 路径 | 内容 |
| --- | --- |
| `data/search_discovery/raw/search_results.jsonl` | 各 source 返回的归一化搜索结果，包含 `metrics`、`route_weight`、`route_reason`、`fetch_status` 等字段 |
| `data/search_discovery/evidence/search_content_evidence.jsonl` | 搜索结果补充证据，例如摘要、正文片段或错误信息 |
| `data/search_discovery/processed/search_topic_index.json` | 聚合后的候选选题索引，供下游筛选和生成报告使用 |
| `data/search_discovery/history/recommended_topics.json` | 推荐历史，用来标记 30 天内已经推荐过的 GitHub 结果 |
| `reports/search_discovery/search_topic_recommendations.md` | 可读的选题推荐报告，仅在传入 `--render-report` 时生成 |

## 创作者画像

内置示例：

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

常用字段：

| 字段 | 作用 |
| --- | --- |
| `creator_id` | 创作者或账号标识 |
| `role` | 人设说明，会进入路由理由和搜索意图判断 |
| `profile_type` | 影响 source 权重，目前包含 `tech_ai_creator`、`developer_creator`、`business_startup_creator`、`general_hot_topic_creator` |
| `track_tags` | 领域标签，作为 query 候选关键词 |
| `custom_keywords` | 优先级最高的关键词；存在时会优先用于 query |
| `content_modes` | 内容形态，例如趋势观察、工具测评、教程实践，也会影响 intent 判断 |

新增画像时，可以复制 `config/search_discovery/creator_profiles/tech_ai_creator.json`，改名后调整字段，再用 `--profile` 指向新文件。

## 路由规则

v2 会先用 `classify_search_intent()` 判断搜索意图，再用 `build_search_routes()` 生成 source-specific query。

| intent | 典型触发词 | 优先 source |
| --- | --- | --- |
| `tech_project` | `github`、`开源`、`repo`、`框架`、`sdk`、`mcp`、`rag` | `github_search`、`juejin_content`、`baidu_qianfan_search`、`tavily_search` |
| `tech_article` | `教程`、`实践`、`案例`、`源码`、`部署`、`架构` | `juejin_content`、`github_search`、`baidu_qianfan_search`、`tavily_search` |
| `news_trend` | `新闻`、`最新`、`发布`、`融资`、`政策`、`行业` | `tianapi_news`、`news_api_cn`、`baidu_qianfan_search`、`tavily_search`、`qiniu_web_search` |
| `product_trend` | `产品`、`应用`、`商业化`、`saas`、`工具` | `baidu_qianfan_search`、`news_api_cn`、`tianapi_news`、`tavily_search`、`qiniu_web_search` |
| `content_angle` | 兜底意图 | 按画像默认权重选择 |

GitHub query 使用 Hunter 风格构造：

```text
AI Agent MCP RAG in:name,description,readme stars:>200 pushed:>YYYY-MM-DD
```

其中 `pushed:>` 默认取最近 180 天，避免推荐长期未维护的仓库。

## 推荐历史和冷却期

v2 会维护 `data/search_discovery/history/recommended_topics.json`。默认规则是：30 天内已经推荐过的 GitHub 结果会被标记为 `recently_recommended`，并在 raw result、topic source hits 和报告 evidence 中展示。

当前冷却逻辑只做「标记和展示」，不做强制降权。这样可以让报告保留透明度，同时避免因为历史记录误伤高质量项目。

## 连通性状态

`--set` 和 `--test` 最终会调用 `test_source_connection()`，常见状态如下：

| status | 含义 | 建议 |
| --- | --- | --- |
| `ok` | provider 已配置并正常返回结果 | 无需处理 |
| `missing_key` | `.env` 缺 key，或 key 为空 | 使用 `--set SOURCE_ID` 配置 |
| `auth_failed` | 鉴权失败，例如 token 过期、key 无效、权限不足 | 检查平台后台的 key 状态 |
| `upstream_failed` | 上游服务错误、网络错误或限流 | 稍后重试，或检查服务状态 |
| `parse_failed` | 返回内容无法解析 | 检查 provider 协议是否变化 |
| `empty_result` | 连接成功但 query 没有结果 | 通常不严重，可换 query 或稍后重试 |

## 开发和测试

运行 v2 全量测试：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run pytest tests/search_discovery -q
```

运行配置助手相关测试：

```powershell
uv run pytest tests/search_discovery/test_api_config.py `
  tests/search_discovery/test_env_file.py `
  tests/search_discovery/test_connectivity.py `
  tests/search_discovery/test_config_api.py -q
```

运行路由和 GitHub query 测试：

```powershell
uv run pytest tests/search_discovery/test_routing.py `
  tests/search_discovery/test_github_query.py `
  tests/search_discovery/test_providers_github.py -q
```

新增 provider 时，通常需要做四件事：

1. 在 `src/search_discovery/providers_xxx.py` 实现 provider。
2. 在 `src/search_discovery/cli.py::_REAL_PROVIDER_CLASSES` 注册 provider。
3. 在 `src/search_discovery/api_config.py::api_source_configs()` 增加配置元数据。
4. 补充 provider、连通性、CLI 或路由测试。

## 常见问题

### 没有配置任何 API key 能跑吗？

能跑，但基本只会得到 `mock_unavailable` 占位结果。建议至少配置 `GITHUB_TOKEN` 和一个国内搜索源，例如 `BOCHA_API_KEY`、`QIANFAN_API_KEY`/`QIANFAN_SECRET_KEY` 或 `TIANAPI_KEY`。

### 为什么配置了 key 还是显示 `missing_key`？

先确认当前目录是项目根目录：

```powershell
pwd
```

应该位于：

```text
E:\.code\My\heatedTopics\heatedTopics
```

然后重新加载并测试：

```powershell
$env:PYTHONPATH='E:\.code\My\heatedTopics\heatedTopics'
uv run python -m src.search_discovery.config_api --list
uv run python -m src.search_discovery.config_api --test SOURCE_ID
```

### 报告没有生成怎么办？

确认命令里带了 `--render-report`：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-report
```

报告路径是 `reports/search_discovery/search_topic_recommendations.md`。

### v2 会修改 DailyHot 主流程吗？

不会。v2 只读画像、调用搜索源，并写入 `data/search_discovery/` 与 `reports/search_discovery/`。DailyHot 热榜采集、浏览器登录态管理、主报告生成仍按 `README.md` 的说明运行。

## 相关文档

- `README.md`：DailyHot 热榜采集和详情证据整理主流程。
- `docs/superpowers/plans/2026-06-30-search-api-config-assistant.md`：Search API 配置助手实施计划。
- `docs/superpowers/specs/2026-06-29-profile-driven-search-routing-design.md`：画像驱动搜索路由设计。
- `docs/superpowers/specs/2026-06-27-search-discovery-real-providers-design.md`：真实搜索 provider 接入设计。
