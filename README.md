# HeatedTopics

HeatedTopics 为内容创作者提供两类每日内容参考：

- **相关文章推荐**：根据用户的赛道、细分方向和人设，推荐相关的热点文章。
- **每日热榜整理**：读取多个平台的热榜和正文缓存，合并明显属于同一事件的话题，再搜索资料并生成创作参考卡片。

两个功能共享同一份每日热榜缓存、LLM 配置和 embedding 配置。

如果你是负责接手、启动或继续开发本项目的 Agent，请先阅读 [Agent 快速接手指南](https://github.com/BZ2116/HeatedTopics/blob/V-final/docs/AGENT_GUIDE.md)。

## 1. 每日热榜整理

每日热榜的处理链路：

```text
平台热榜及正文缓存
  → 标题标准化
  → 跨平台话题聚类
  → 合并明显属于同一事件的话题
  → 按平台权重和热度排序
  → 为每个话题生成搜索计划
  → Web Search MCP 获取证据
  → 证据去重和相关性清洗
  → LLM 生成 Markdown 总结
  → 解析为结构化话题卡片
```

聚类阶段只看标题。策略是优先合并明显的同一事件，无法确认的标题保留为独立话题，再按照平台权重、热榜排名和热度排序，避免过度合并。

每个话题卡片包含：

- 话题标题、话题 ID、趋势分数；
- 涉及平台和平台观察；
- 事实摘要、关键事实、时间线和关键数字；
- 争议点和适合创作者的选题角度；
- 搜索证据、来源 URL、发布时间和证据状态。

### 调用方式

```python
from heated_topics_v3.openbiliclaw_integration.service import HeatedTop

result = HeatedTop().run(
    run_dir="data/run_20260812",
    limit=50,
)

print(result["topics"])
```

`limit` 同时决定最终话题数量和需要搜索、总结的话题数量。默认建议使用 50 条。当天重复运行时，程序通过稳定 fingerprint 复用已有话题卡片，减少重复搜索和 LLM 调用；需要强制重跑时传入 `force=True`。

输入目录支持以下两种形式：

```text
data/run_20260812/hot_cache/*.json
data/run_20260812/hot_cache/2026-08-12/*.json
```

输出目录：

```text
data/run_20260812/daily_hot/
├── topics.json       # 结构化话题卡片
├── topics.md         # 便于人工查看的 Markdown 榜单
└── run_status.json   # 运行状态、缓存命中和搜索失败信息
```

当天原则上只执行一次。重复执行会覆盖当天输出，但会优先复用相同 fingerprint 的已有结果。

## 2. 相关文章推荐

推荐流程使用用户的一级赛道、二级赛道和人设，从平台热榜、平台搜索和最近 30 天数据中获取候选文章，然后完成正文抓取、清洗、相关性排序和输出。

```python
from heated_topics_v3.openbiliclaw_integration.service import RecommendationService

service = RecommendationService(max_concurrency=3)
result = await service.recommend_user(
    user_id="u_001",
    track_1="旅行攻略",
    track_2="穷游周末",
    persona="预算敏感型旅行爱好者，专做两天一夜短途攻略。",
    run_dir="data/run_20260812",
    source="both",
    limit=15,
)
```

并发服务会限制全局并发量，并保证同一个用户不会同时写入缓存和 round 目录。每次调用都会生成新的 `round_XXX`，不会覆盖该用户之前的推荐结果。

## 3. 对外接口

当前业务层对外提供：

```python
from heated_topics_v3.openbiliclaw_integration.service import (
    RecommendationService,
    HeatedTop,
)
```

- `RecommendationService`：相关文章推荐，支持多用户并发调用；
- `HeatedTop`：每日热榜整理，每天执行一次即可，不需要按用户并发调用。

接口实现位于：

```text
src/heated_topics_v3/openbiliclaw_integration/service.py
```

## 4. 安装

项目使用 `uv`：

```bash
uv sync
```

复制配置模板：

```bash
cp .env.example .env
```

推荐把 `HeatedTopics` 与 `last30days-skill-cn` 放在同级目录：

```bash
git clone https://github.com/Jesseovo/last30days-skill-cn.git ../last30days-skill-cn
```

如果路径不同，设置：

```env
LAST30DAYS_CLI_PATH=/your/path/last30days-skill-cn/scripts/last30days.py
```

## 5. 共享配置

推荐和热榜使用同一份 `.env`。

### LLM

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-api-key
HT_LLM_BASE_URL=https://api.example.com/v1
HT_LLM_MODEL=your-model
```

项目支持以下 LLM provider：

| Provider | 配置值 | 适用场景 |
| --- | --- | --- |
| OpenAI | `openai` | OpenAI 官方模型 |
| DeepSeek | `deepseek` | DeepSeek 官方模型 |
| Gemini | `gemini` | Google Gemini API |
| Claude | `claude` | Anthropic Claude |
| Ollama | `ollama` | 本地部署模型 |
| OpenRouter | `openrouter` | 通过统一网关选择多家模型 |
| OpenAI-compatible | `openai_compatible` | 兼容 Chat Completions 的云服务、本地网关和自建模型服务 |

MiniMax、通义千问/DashScope、硅基流动、Moonshot、智谱、DeepSeek、OpenRouter，以及 vLLM、Ollama 等本地网关，通常可以通过 `openai_compatible` 接入。具体模型名、接口路径、上下文长度和额外参数以对应服务为准。

#### OpenAI-compatible 配置示例

MiniMax：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-minimax-key
HT_LLM_BASE_URL=https://api.minimaxi.com/v1
HT_LLM_MODEL=MiniMax-Text-01
```

DeepSeek：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-deepseek-key
HT_LLM_BASE_URL=https://api.deepseek.com/v1
HT_LLM_MODEL=deepseek-chat
```

本地 Ollama 的 OpenAI 兼容接口：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=ollama
HT_LLM_BASE_URL=http://127.0.0.1:11434/v1
HT_LLM_MODEL=qwen2.5:14b
```

统一 LLM adapter 当前调用 `/chat/completions`，负责：

- 跨平台话题合并；
- 话题搜索计划生成；
- 搜索结果归纳和创作者话题总结；
- 相关文章推荐中的关键词提取和相关性处理。

`HT_LLM_PROVIDER` 主要用于 OpenBiliClaw runtime 选择 provider；每日热榜使用的通用 `LLMAdapter` 重点读取 `HT_LLM_API_KEY`、`HT_LLM_BASE_URL` 和 `HT_LLM_MODEL`。

如果服务不兼容标准 Chat Completions，不能只修改环境变量，需要在 `llm_adapter.py` 中增加对应 adapter。

### Embedding

```env
HT_EMBEDDING_PROVIDER=ollama
HT_EMBEDDING_BASE_URL=http://127.0.0.1:11434
HT_EMBEDDING_MODEL=bge-m3
```

Embedding 可使用以下 provider：

| Provider | 配置值 | 说明 |
| --- | --- | --- |
| Ollama | `ollama` | 推荐的本地 embedding 方案 |
| OpenAI | `openai` | 使用 OpenAI embedding API |
| OpenAI-compatible | `openai_compatible` | 使用兼容 embedding 接口 |
| Gemini | `gemini` | 使用 Gemini embedding 能力 |
| OpenRouter | `openrouter` | 由 OpenRouter 提供 embedding 模型 |
| DashScope | `dashscope` | 使用阿里云 DashScope embedding |

Embedding 主要用于相关文章推荐中的相似度计算和相关性排序，不负责每日热榜的事实搜索。使用本地 Ollama 时：

```bash
ollama pull bge-m3
```

## 6. Web Search MCP

LLM 和 Web Search 是两个独立能力：LLM 负责分析、合并和总结；`ResearchProvider` 负责获取带 URL 的外部证据。当前默认使用 MiniMax Token Plan MCP，并复用长连接执行多个话题的搜索。

```env
HT_WEB_SEARCH_PROVIDER=minimax_mcp
HT_WEB_SEARCH_MCP_COMMAND=uvx
HT_WEB_SEARCH_MCP_ARGS=--with fastmcp minimax-coding-plan-mcp -y
HT_WEB_SEARCH_MCP_TOOL=web_search
MINIMAX_API_KEY=your-token-plan-key
MINIMAX_API_HOST=https://api.minimaxi.com
```

也可以接入其他 stdio MCP：

```env
HT_WEB_SEARCH_PROVIDER=generic_mcp
HT_WEB_SEARCH_MCP_COMMAND=your-mcp-command
HT_WEB_SEARCH_MCP_ARGS=--stdio
HT_WEB_SEARCH_MCP_TOOL=web_search
HT_WEB_SEARCH_MCP_ENV_JSON={"API_KEY":"your-key"}
```

当前已接入 MiniMax MCP 和通用 stdio MCP。OpenAI 原生 Web Search、Gemini Search grounding、Anthropic Web Search 和 Perplexity Search API 暂未作为独立 `ResearchProvider` 接入，因此不能仅通过更换 LLM provider 自动启用。

## 7. 推荐输出目录

```text
data/run_20260812/
├── hot_cache/                 # 每日共享热榜缓存
├── daily_hot/                 # HeatedTop 输出
└── u_001/
    ├── keyword_cache/         # 用户关键词缓存
    ├── hard_cache/            # 用户推荐缓存
    └── round_001/             # 一次推荐调用
        ├── input/input.json
        └── outputs/
            ├── recommended/
            ├── search/
            └── text/
```

## 8. CLI 调试

CLI 只用于本地调试和批量验证，业务项目优先使用 Python 接口。

```bash
uv run python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users-excel data/users.xlsx \
  --output-dir data/run_20260812 \
  --source both \
  --max-parallel 3 \
  --limit 15
```

Excel 至少包含：`user_id`、`track_1`、`track_2`、`persona`。

## 9. 测试

运行核心测试：

```bash
uv run pytest -q
uv run python -m compileall -q src
```

热榜核心测试：

```bash
uv run pytest -q tests/hot_topics tests/test_hot_topic_cache.py tests/test_heated_top_integration.py
```

## 10. 主要代码结构

```text
src/heated_topics_v3/
├── hot_topics/
│   ├── run_hot_topics.py          # 热榜总流程
│   ├── hot_topic_clustering.py   # 跨平台话题聚类
│   ├── hot_topic_ranking.py      # 话题排序
│   ├── search_planner.py          # 搜索计划
│   ├── research_provider.py      # Web Search/MCP provider
│   └── creator_brief.py          # 创作者话题总结
├── llm_adapter.py                 # 共享 LLM adapter
└── openbiliclaw_integration/
    ├── service.py                 # RecommendationService、HeatedTop
    ├── heated_top.py              # 每日热榜门面
    ├── recommender.py             # 相关文章推荐
    └── runtime.py                 # LLM、embedding 和环境配置
```
