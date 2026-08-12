# HeatedTopics Agent 快速接手指南

这份文档给负责运行、调试或继续开发本项目的 Agent 使用。目标是让 Agent 在首次接手时先完成环境确认，再运行推荐流程，避免把外部依赖、模型服务和本项目代码混在一起排查。

## 1. 项目定位

项目有两个业务入口，均位于 `heated_topics_v3.openbiliclaw_integration.service`：

- `RecommendationService`：根据用户信息推荐相关文章，支持多用户并发；
- `HeatedTop`：每天读取共享热榜缓存，整理跨平台话题、搜索证据并生成创作者话题卡片，每天执行一次即可。

两条流程共享每日 `hot_cache`、LLM 和 embedding 配置，但 Web Search 只由 `HeatedTop` 使用。

本项目接收一个用户的：

- 一级赛道 `track_1`；
- 二级赛道 `track_2`；
- 人设 `persona`。

项目从 V3 热榜、平台搜索和 last30days 最近 30 天数据中获取候选文章，清洗资源分享类、话题讨论类等无效内容，尽量抓取完整正文，再按用户相关性输出推荐结果。

当前推荐主链路是：

```text
用户输入
→ 关键词提取
→ V3 热榜/搜索 + last30days
→ 正文抓取
→ 候选清洗
→ embedding 相关性预筛
→ OpenBiliClaw 推荐排序
→ round_xxx JSON 输出
```

每日热榜链路是：

```text
平台热榜及正文缓存
→ 只基于标题聚类
→ 合并明显同一事件
→ 平台权重排序
→ 每个话题生成搜索计划
→ Web Search MCP 获取并清洗证据
→ LLM Markdown 总结
→ 结构化创作者话题卡片
```

## 2. 必须先准备的外部依赖

### 2.1 OpenBiliClaw

heatedTopics 依赖的是已经加入 `serve_external_candidates()` 的专用分支：

```text
https://github.com/BZ2116/OpenBiliClaw.git
分支：feature/heatedtopics-external-candidates
```

`pyproject.toml` 已经指向这个 Git 依赖。不要改回本机绝对路径，也不要随意替换成上游 `main`，否则会缺少外部候选推荐入口。

安装后必须验证：

```bash
uv run python -c "from openbiliclaw.recommendation.engine import RecommendationEngine; print(hasattr(RecommendationEngine, 'serve_external_candidates'))"
```

预期输出：

```text
True
```

### 2.2 last30days

last30days 是独立仓库：

```text
https://github.com/Jesseovo/last30days-skill-cn.git
```

推荐放在 heatedTopics 同级目录：

```text
workspace/
├── heatedTopics/
└── last30days-skill-cn/
    └── scripts/last30days.py
```

下载：

```bash
git clone https://github.com/Jesseovo/last30days-skill-cn.git ../last30days-skill-cn
```

如果不放在同级目录，必须在 `.env` 配置：

```env
LAST30DAYS_CLI_PATH=/absolute/path/to/last30days-skill-cn/scripts/last30days.py
```

Windows、macOS、Linux 都使用当前机器自己的路径，不复制其他机器的盘符路径。

## 3. Python 和本地服务

要求：

- Python 3.11 或更高版本；
- `uv`；
- 可访问外部平台的网络；
- 一个可用的 LLM；
- 一个可用的 embedding 服务。

embedding 可以使用 Ollama，也可以使用 OpenAI 兼容服务。使用 Ollama 时：

```bash
ollama serve
ollama pull bge-m3
```

不使用 Ollama 时，不需要安装 `bge-m3`，改为配置通用 embedding：

```env
HT_EMBEDDING_PROVIDER=openai_compatible
HT_EMBEDDING_API_KEY=your-key
HT_EMBEDDING_BASE_URL=https://your-provider.example/v1
HT_EMBEDDING_MODEL=your-embedding-model
```

## 4. 安装项目

在 heatedTopics 项目根目录执行：

```bash
uv sync
```

如果修改了 `pyproject.toml` 中的 Git 依赖，重新执行：

```bash
uv lock
uv sync
```

不要手工修改 `uv.lock` 中 OpenBiliClaw 的 commit；让 `uv lock` 根据 `pyproject.toml` 更新。

## 5. 配置 `.env`

复制示例文件：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

最小配置示例：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-llm-key
HT_LLM_BASE_URL=https://your-llm-provider.example/v1
HT_LLM_MODEL=your-chat-model

HT_EMBEDDING_PROVIDER=ollama
HT_EMBEDDING_MODEL=bge-m3
ZHIHU_COOKIE=your-zhihu-cookie
LAST30DAYS_CLI_PATH=

HT_WEB_SEARCH_PROVIDER=minimax_mcp
HT_WEB_SEARCH_MCP_COMMAND=uvx
HT_WEB_SEARCH_MCP_ARGS=--with fastmcp minimax-coding-plan-mcp -y
HT_WEB_SEARCH_MCP_TOOL=web_search
MINIMAX_API_KEY=your-token-plan-key
MINIMAX_API_HOST=https://api.minimaxi.com
```

用户只需要填写一个 LLM 和一个 embedding。平台 Cookie、last30days 路径以及其他搜索平台 key 按实际启用的数据源填写。

通用模型配置：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-llm-key
HT_LLM_BASE_URL=https://your-llm-provider.example/v1
HT_LLM_MODEL=your-chat-model

HT_EMBEDDING_PROVIDER=ollama
HT_EMBEDDING_MODEL=bge-m3
```

优先级：`HT_*` 环境变量高于配置文件中对应字段。LLM 统一使用 `HT_LLM_*`；Web Search MCP 使用 `HT_WEB_SEARCH_*` 和对应 MCP 所需的环境变量。

LLM provider 支持 OpenAI、DeepSeek、Gemini、Claude、Ollama、OpenRouter 和 `openai_compatible`。MiniMax、DashScope、硅基流动、Moonshot、智谱以及 vLLM/Ollama 网关通常通过 `openai_compatible` 接入。统一 adapter 调用 `/chat/completions`。

默认 Web Search 是 MiniMax Token Plan MCP，使用长连接复用多个话题搜索。也可以配置 `HT_WEB_SEARCH_PROVIDER=generic_mcp` 接入其他 stdio MCP：

```env
HT_WEB_SEARCH_PROVIDER=generic_mcp
HT_WEB_SEARCH_MCP_COMMAND=your-mcp-command
HT_WEB_SEARCH_MCP_ARGS=--stdio
HT_WEB_SEARCH_MCP_TOOL=web_search
HT_WEB_SEARCH_MCP_ENV_JSON={"API_KEY":"your-key"}
```

绝对禁止把 `.env`、Cookie、API key、运行缓存和用户推荐结果提交到 Git。

## 6. 启动前检查

依次执行：

```bash
uv run python -m compileall -q src
uv run python -c "from openbiliclaw.recommendation.engine import RecommendationEngine; assert hasattr(RecommendationEngine, 'serve_external_candidates')"
uv run pytest tests/openbiliclaw_integration/test_runtime.py tests/openbiliclaw_integration/test_cli.py -q
```

如果使用 Ollama，再检查：

```bash
ollama list
```

确认模型列表中有 `bge-m3`。

## 7. 默认运行方式：Python 接口

每日热榜：

```python
from heated_topics_v3.openbiliclaw_integration.service import HeatedTop

result = HeatedTop().run(run_dir="data/run_20260812", limit=50)
```

`limit` 同时决定话题数、搜索数和总结数。当天重复运行会按 fingerprint 复用已有卡片；需要完全重跑时使用 `force=True`。

正式业务调用和其他项目接入，优先使用 Python 接口，不要通过子进程拼接 CLI：

```python
from heated_topics_v3.openbiliclaw_integration.service import RecommendationService

service = RecommendationService(max_concurrency=3)
result = await service.recommend_user(
    user_id="u_001",
    track_1="旅行攻略",
    track_2="穷游周末",
    persona="预算敏感型旅行爱好者。",
    run_dir="data/run_20260809",
    source="both",
)
```

返回值中的 `recommendations` 可直接用于业务匹配，`round_dir` 指向本次标准文件输出目录。接口已经负责用户级缓存、日期级热榜缓存、轮次目录、最大 3 个并发以及同一用户串行保护。

## 8. CLI 调试和批量运行

当前 CLI 使用 Excel 输入。Excel 字段：

```text
user_id | track_1 | track_2 | persona
```

运行：

```bash
uv run python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users-excel data/users.xlsx \
  --output-dir data/run_$(date +%Y%m%d) \
  --source both \
  --max-parallel 3 \
  --limit 15
```

如果自动找不到 last30days，追加：

```bash
--last30days-cli-path /absolute/path/to/last30days-skill-cn/scripts/last30days.py
```

PowerShell 示例：

```powershell
$runDate = Get-Date -Format yyyyMMdd
uv run python -m heated_topics_v3.openbiliclaw_integration.cli `
  --users-excel data/users.xlsx `
  --output-dir "data/run_$runDate" `
  --source both `
  --max-parallel 3 `
  --limit 15
```

## 9. 输出和缓存位置

```text
data/run_YYYYMMDD/
├── hot_cache/                 # 日期级热榜缓存
├── daily_hot/                 # HeatedTop 输出
│   ├── topics.json
│   ├── topics.md
│   └── run_status.json
└── u_xxxx/
    ├── keyword_cache/         # 用户关键词缓存
    ├── hard_cache/            # 用户级 OpenBiliClaw 缓存
    └── round_001/
        ├── input/input.json
        └── outputs/
            ├── recommended/
            ├── search/hot/
            ├── search/search/
            └── text/
```

同一个用户再次调用生成下一个 round，不覆盖旧结果。`data/` 默认被 Git 忽略，只用于本地运行和验证。

## 10. 外部项目接入

外部项目只需要依赖两个公共对象：

```python
from heated_topics_v3.openbiliclaw_integration.service import (
    RecommendationService,
    HeatedTop,
)
```

不要复制热榜聚类、MCP 搜索、缓存 fingerprint 或推荐排序逻辑。

外部项目优先调用：

```python
from heated_topics_v3.openbiliclaw_integration.service import RecommendationService

service = RecommendationService(max_concurrency=3)
result = await service.recommend_user(
    user_id="u_001",
    track_1="旅行攻略",
    track_2="穷游周末",
    persona="预算敏感型旅行爱好者。",
    run_dir="data/run_20260809",
    source="both",
)
```

不要在外部项目中复制 CLI 参数解析、缓存路径拼接或正文筛选逻辑。并发限制和同一用户串行保护已经由 `RecommendationService` 负责。

## 11. 常见问题排查

### Web Search MCP 启动失败

先确认 `HT_WEB_SEARCH_PROVIDER`、MCP 命令和参数正确；MiniMax 模式还要确认 `MINIMAX_API_KEY`。MCP provider 是长连接，单次 `HeatedTop` 运行结束后才关闭。

### OpenBiliClaw 补丁缺失

现象：

```text
RecommendationEngine has no serve_external_candidates
```

处理：检查 `uv.lock` 是否指向 `BZ2116/OpenBiliClaw` 的 `feature/heatedtopics-external-candidates` 分支，然后执行：

```bash
uv lock
uv sync
```

### 找不到 last30days

检查：

```bash
test -f ../last30days-skill-cn/scripts/last30days.py
```

或显式设置 `LAST30DAYS_CLI_PATH`。

### embedding 不可用

确认 `HT_EMBEDDING_PROVIDER`、模型名、API key 和 base URL 是否匹配。没有 embedding 时项目可以降级运行，但相关性预筛和多样性排序效果会下降。

### 知乎抓取失败

检查 `.env` 中 `ZHIHU_COOKIE` 是否仍有效。Cookie 只放本机环境变量，不要写进 README、测试或日志。

## 12. 修改和提交规则

修改后至少运行：

```bash
uv run python -m compileall -q src
uv run pytest tests/openbiliclaw_integration -q
git diff --check
```

提交前确认：

```bash
git status --short
git diff --stat
```

不要提交：

- `.env`；
- `data/` 下的运行结果、Cookie、缓存、SQLite 数据库；
- `.openbiliclaw_shared/`；
- 临时脚本和本地日志；
- 任何 Windows 或 macOS 专属的本地绝对路径。

如果修改 OpenBiliClaw 的推荐引擎，先在 OpenBiliClaw fork 中建立独立分支并推送，再更新 heatedTopics 的 Git 依赖和 `uv.lock`。

## 13. 项目启动最终验收

完成依赖安装、模型配置和启动前检查后，最后必须执行 Python 接口验收测试：

```bash
uv run pytest tests/openbiliclaw_integration/test_service.py -q
```

该测试使用隔离的临时目录和模拟推荐引擎，不会调用真实 LLM、embedding 或平台接口，但会验证正式业务入口的关键契约：

- `RecommendationService` 可以接收一个完整用户输入；
- 用户输入可以转换为内部 `UserSpec`；
- 用户级 round 目录能够正确生成；
- `input/input.json` 能够写出；
- `outputs/` 和推荐结果目录能够写出；
- 多用户并发上限和同一用户串行锁有效；
- 当天热榜总结接口能够读取共享缓存并写出结果。

验收成功时应看到类似结果：

```text
4 passed
```

如果该测试失败，Agent 不应直接运行真实推荐或修改数据源，应先根据失败信息检查 `service.py`、缓存路径、OpenBiliClaw 安装和 Python 环境。
