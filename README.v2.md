# HeatedTopics v2 使用说明

v2 是 HeatedTopics 的「搜索发现增强」链路，核心代码在 `src/search_discovery/`。它从创作者画像出发，自动拆解用户关键词，生成搜索 query，路由到 GitHub、博查、阿里百炼、百度千帆、天聚数行、Tavily、七牛等搜索源，最后输出候选选题索引、证据文件和 Markdown 选题分析报告。

当前重点面向「根据用户标签/关键词，发现适合内容生成参考的国内热点」。相比只把关键词丢给搜索 API，v2 会额外做两类质量处理：

- 关键词拆解和匹配：把用户输入拆成领域词、实体词、事件词、内容角度、排除词和风险词，再用标题、摘要、正文做匹配评分。
- 准确性和真实性：记录搜索结果总数、候选话题数、证据条目数；过滤“财经”“股票”“新浪财经客户端”这类泛词或频道页标题；对来源数量、新闻源、发布时间、官方信号和高风险表达做核验评分。

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
  --render-analysis `
  --analysis-mode rule
```

命令结束后会打印类似结果：

```json
{"analysis_topics_count": 8, "evidence_count": 12, "search_results_count": 35, "topics_count": 8}
```

如果某些 API key 没有配置，对应 source 会写入 `fetch_status=mock_unavailable` 的占位结果，不会阻断其他已配置 source。

财经/A 股场景可以直接用内置画像小样例：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/finance_creator.json `
  --render-analysis `
  --analysis-mode rule
```

## 用户画像检索库

真实用户画像以 Excel 中的 `一级赛道`、`二级赛道`、`人设` 三列为准。不要把真实画像直接提交到 `config/search_discovery/creator_profiles/`；该目录只保留可公开的样例配置。真实画像转换后的检索数据写入 `data/search_discovery/personas/`，该目录已被 `.gitignore` 忽略。

转换命令：

```powershell
uv run python -m src.search_discovery.persona_profiles `
  --input "E:\path\to\人设数据收集.xlsx" `
  --output-dir data/search_discovery/personas
```

输出文件：

| 路径 | 内容 |
| --- | --- |
| `data/search_discovery/personas/persona_profiles.jsonl` | 画像检索文档，每行包含 `profile_id`、赛道、人设、关键词、内容模式和 `retrieval_text`。 |
| `data/search_discovery/personas/creator_profiles.jsonl` | v2 搜索发现链路可复用的 `CreatorProfile` 兼容格式。 |
| `data/search_discovery/personas/persona_index.json` | 不含完整人设正文的本地索引摘要，用于快速查看画像数量、赛道和来源行号。 |

标准画像文档格式：

```json
{
  "schema_version": "0.1",
  "profile_id": "persona_0001",
  "primary_track": "职场成长",
  "secondary_track": "应届生求职",
  "persona_text": "Excel 中的人设原文",
  "profile_type": "general_hot_topic_creator",
  "track_tags": ["职场成长", "应届生求职"],
  "custom_keywords": ["简历", "面试", "校招"],
  "content_modes": ["案例拆解", "避坑清单"],
  "retrieval_text": "用于 BM25 或向量召回的拼接文本",
  "sensitivity_level": "internal",
  "source": {
    "file": "人设数据收集.xlsx",
    "sheet": "工作表1",
    "row": 2
  }
}
```

## API 配置

v2 的 API key 写在项目根目录的 `.env`。第一次运行配置助手时，如果 `.env` 不存在，会自动从 `.env.example` 复制一份。

支持的搜索源如下：

| source_id | 用途 | 环境变量 | 申请地址 |
| --- | --- | --- | --- |
| `github_search` | GitHub 仓库和开源项目发现 | `GITHUB_TOKEN` | https://github.com/settings/tokens |
| `news_api_cn` | 博查 AI 搜索，国内新闻和网页信息 | `BOCHA_API_KEY` | https://bochaai.com |
| `juejin_content` | 阿里百炼 Web Search，技术文章槽位 | `BAILIAN_API_KEY` | https://bailian.console.aliyun.com/ |
| `baidu_qianfan_search` | 百度千帆搜索，国内网页、博客、问答和新闻 | `QIANFAN_API_KEY`；旧版凭证可额外填 `QIANFAN_SECRET_KEY` | https://console.bce.baidu.com/qianfan/ |
| `tianapi_news` | 天聚数行新闻，媒体源和发布时间 | `TIANAPI_KEY` | https://www.tianapi.com/ |
| `tavily_search` | Tavily 搜索，英文/全球网页和摘要 | `TAVILY_API_KEY` | https://app.tavily.com/home |
| `qiniu_web_search` | 七牛 Web Search，国内网页搜索兜底 | `QINIU_WEB_SEARCH_API_KEY` | https://www.qiniu.com/ |

千帆特别注意：新版控制台生成的 `bce-v3/ALTAK...` API Key 只需要填 `QIANFAN_API_KEY`，`QIANFAN_SECRET_KEY` 可以留空。旧版 `API Key + Secret Key` 二件套仍然兼容，会自动走 OAuth token 兑换。

### 查看配置状态

```powershell
uv run python -m src.search_discovery.config_api --list
```

示例输出：

```text
Search API Configuration

[OK]   github_search          GITHUB_TOKEN=ghp_****blW0
[MISS] tavily_search          missing: TAVILY_API_KEY
[OK]   baidu_qianfan_search   QIANFAN_API_KEY=bce-****9d02
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

### 省 API 的批量冒烟测试

如果只想确认「已配置的 source 能不能连上」，但不想跑完整搜索发现，可以用：

```powershell
uv run python -m src.search_discovery.config_api --smoke-test
```

这个命令会：

- 只测试 `.env` 里已经配好的 source，缺 key 的 source 会跳过。
- 每个 source 只调用一次。
- 每次请求都使用 `max_results=1`，也就是让上游尽量只返回 1 条结果。
- 不会生成搜索报告，也不会调用 LLM。

适合刚配完 API key 后做低成本验证。示例输出：

```text
[SMOKE] Testing configured sources with max_results=1

[OK] github_search connected successfully, returned 1 results.
[OK] baidu_qianfan_search connected successfully, returned 1 results.
```

### 手动编辑 `.env`

也可以直接编辑 `.env`：

```text
GITHUB_TOKEN=
BOCHA_API_KEY=
BAILIAN_API_KEY=
QIANFAN_API_KEY=bce-v3/ALTAK...
QIANFAN_SECRET_KEY=
TIANAPI_KEY=
TAVILY_API_KEY=
QINIU_WEB_SEARCH_API_KEY=

OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4.1-mini

MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M3
```

如果把 `MINIMAX_BASE_URL` 指向 MiniMax 的 Anthropic 兼容端点（路径含 `/anthropic`），代码会自动切到 Anthropic Messages API（`x-api-key` 鉴权、`/v1/messages` 端点、不再带 `response_format` JSON 模式，依赖 prompt 约束 JSON 输出）。

注意事项：

- GitHub 搜索没有 token 时仍可访问公开搜索 API，但 rate limit 较低；建议配置 `GITHUB_TOKEN`。
- 百度千帆新版 API Key 只需要配置 `QIANFAN_API_KEY`，请求时会以 `Authorization: Bearer <QIANFAN_API_KEY>` 发送。
- 当前 `baidu_qianfan_search` 使用千帆新版百度搜索接口 `https://qianfan.baidubce.com/v2/ai_search/web_search`，请求体包含 `messages`、`search_source=baidu_search_v2` 和 `resource_type_filter`。
- 如果你使用旧版千帆 `API Key + Secret Key` 凭证，则同时配置 `QIANFAN_API_KEY` 和 `QIANFAN_SECRET_KEY`，项目会先调用 `https://aip.baidubce.com/oauth/2.0/token` 换取 `access_token`。
- 任意单个 source 缺失或失败都不会让 v2 全流程崩溃，只会在结果中记录不可用状态。
- `MINIMAX_*` / `OPENAI_*` 只用于 `--analysis-mode model` 的归纳总结，不影响搜索 API 的连通性。
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

## 选题分析输出

如果希望在搜索推荐之外生成更完整的整理、归纳和统计结果，开启 `--render-analysis`：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode rule
```

输出文件：

| 路径 | 用途 |
| --- | --- |
| `data/search_discovery/processed/topic_analysis.json` | 面向程序和大语言模型的结构化统计、证据和话题上下文 |
| `reports/search_discovery/topic_analysis.md` | 面向用户的选题分析报告 |

`--analysis-mode rule` 不需要模型 key。`--analysis-mode model` 会调用 OpenAI-compatible Chat API，为总体归纳和每个话题生成建议。

`topic_analysis.md` 的稳定结构如下：

1. `# 搜索发现选题分析`：报告标题。
2. `## 总览`：包含搜索结果总数、进入候选话题数、证据条目数，以及本轮候选话题覆盖情况。
3. `## 话题速览`：表格列出话题、匹配分、核验分、证据等级、来源数、风险等级和可用内容角度。
4. `## 重点话题`：逐个话题展开，包含摘要、为什么值得写、创作角度、证据与核验提示。
5. `## 数据统计`：展示总话题数、搜索结果总数、证据条目、平均匹配分、平均核验分等指标。
6. `## 风险提示`：列出单一来源、缺少发布时间、高风险主题等需要人工复核的点。

报告里的“话题”应该是具体事件、具体帖子、具体政策变化或具体市场异动，不应该是“财经”“股票”这种输入关键词本身，也不应该是“新浪财经客户端”这类来源或频道名称。

如果使用 MiniMax，推荐直接配置 `MINIMAX_*`：

```text
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M3
```

如果使用其他 OpenAI-compatible 服务，再配置 `OPENAI_*`：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

配置步骤：

1. 选择模型服务。MiniMax 可直接使用上面的 `MINIMAX_*`；其他兼容 `/chat/completions` 的网关使用 `OPENAI_*`。
2. 在 `.env` 中填写：
   - MiniMax：`MINIMAX_API_KEY`、`MINIMAX_BASE_URL`、`MINIMAX_MODEL`。
   - 其他服务：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`。
   - `*_BASE_URL` 填接口根地址，不带 `/chat/completions`。
   - 如果 `MINIMAX_BASE_URL` 含 `/anthropic`，自动改用 Anthropic Messages API（`/v1/messages`、`x-api-key` 鉴权），不依赖 `response_format`。
3. 先用 `rule` 模式确认搜索和统计输出正常：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode rule
```

4. 再启用模型归纳：

```powershell
uv run python -m src.search_discovery.cli `
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json `
  --render-analysis `
  --analysis-mode model
```

模型调用失败时，流程仍会输出规则版分析，并在 `topic_analysis.json` 的 `model_error` 字段记录原因。

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
| `platforms` | 期望内容发布平台，例如小红书、微博、公众号；当前主要作为画像上下文保留 |
| `content_goal` | 本轮内容目标，例如涨粉、转化、观点输出；用于后续生成策略扩展 |
| `exclude_keywords` | 排除词；匹配到这些词时会降低匹配分，适合屏蔽不想覆盖的主题 |

新增画像时，可以复制 `config/search_discovery/creator_profiles/tech_ai_creator.json`，改名后调整字段，再用 `--profile` 指向新文件。

推荐把用户背景数据标准化成下面这种结构，再传给 `--profile`：

```json
{
  "creator_id": "creator_finance_001",
  "role": "财经类博主（A 股市场观察、政策解读与个股复盘）",
  "profile_type": "business_startup_creator",
  "track_tags": ["A股", "股票", "财经", "宏观经济", "行业政策"],
  "custom_keywords": ["A股", "央行", "涨停", "复盘", "投资"],
  "content_modes": ["市场观察", "复盘分析", "新闻解读"],
  "platforms": ["公众号", "小红书"],
  "content_goal": "为内容生成系统提供可写的国内热点选题",
  "exclude_keywords": ["美股", "港股", "纯英文资讯"]
}
```

字段填写建议：

- `track_tags` 放长期稳定领域，例如 A 股、教育、医疗、AI、消费、本地生活。
- `custom_keywords` 放本轮用户真正想搜的词，优先级高于领域标签。
- `content_modes` 放输出方式，不要混入泛关键词，例如趋势观察、复盘分析、避坑清单、观点评论。
- `exclude_keywords` 用来控制噪音，尤其适合国内热点任务中过滤海外市场、英文站点或不相关品类。

## 国内热点质量策略

面向国内热点画像时，v2 会启用额外的质量过滤和修复逻辑：

| 问题类型 | 处理方式 |
| --- | --- |
| 泛关键词标题，例如“财经”“股票”“新闻” | 不直接作为话题；如果摘要里有具体事件，会尝试从摘要抽取具体标题 |
| 频道/客户端标题，例如“新浪财经客户端”“A股动态” | 优先过滤；有具体事件线索时修复成事件标题 |
| 纯英文或海外站点结果 | 对国内热点画像默认过滤，避免污染选题池 |
| 单一来源或缺少发布时间 | 保留但降低核验评分，并在报告中提示复核 |
| 高风险表达，例如“网传”“内幕”“稳赚” | 降低真实性评分，并输出风险提示 |

这套规则的目标不是替代人工判断，而是把明显不适合作为内容生成参考的结果先拦掉，把“可写的具体话题”排到前面。

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

能跑，但基本只会得到 `mock_unavailable` 占位结果。建议至少配置 `GITHUB_TOKEN` 和一个国内搜索源，例如 `BOCHA_API_KEY`、`QIANFAN_API_KEY` 或 `TIANAPI_KEY`。

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
