# HeatedTopics Agent 快速接手指南

这份文档给负责运行、调试或继续开发本项目的 Agent 使用。目标是让 Agent 在首次接手时先完成环境确认，再运行推荐流程，避免把外部依赖、模型服务和本项目代码混在一起排查。

## 1. 项目定位

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
OPENBILICLAW_LLM_API_KEY=your-key
ZHIHU_COOKIE=your-zhihu-cookie
LAST30DAYS_CLI_PATH=
```

更推荐使用通用模型配置：

```env
HT_LLM_PROVIDER=openai_compatible
HT_LLM_API_KEY=your-llm-key
HT_LLM_BASE_URL=https://your-llm-provider.example/v1
HT_LLM_MODEL=your-chat-model

HT_EMBEDDING_PROVIDER=ollama
HT_EMBEDDING_MODEL=bge-m3
```

优先级：`HT_*` 环境变量高于 `LLM_*` / `EMBEDDING_*` 别名，也高于配置文件中对应字段。

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

## 7. 运行一个用户

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

## 8. 输出和缓存位置

```text
data/run_YYYYMMDD/
├── hot_cache/                 # 日期级热榜缓存
├── daily_summary/             # 独立热榜总结输出
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

## 9. 外部项目接入

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

## 10. 常见问题排查

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

## 11. 修改和提交规则

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
