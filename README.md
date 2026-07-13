# HeatedTopics V3

HeatedTopics V3 是一个面向内容选题的多平台热点采集项目。它根据用户画像筛选平台热点，保存原始数据与文章正文，并生成便于复盘的 Markdown 报告和结构化 JSON。

当前重点维护 Toutiao v2 流程，同时保留 Juejin、Weibo、Zhihu 与旧版 Toutiao profile 入口。

## Toutiao v2 特性

- Profile-driven：基于一级赛道、二级赛道和结构化人设生成检索词。
- MiniMax LLM：兼容 Anthropic Messages API，可用于关键词提炼、摘要和候选重排。
- 日级热榜缓存：按 UTC+8 日期缓存官方热榜，并支持昨日快照回退。
- 四路径筛选：热榜高热条目、关键词搜索、高热文章兜底和可选 LLM 重排。
- 统一热度评分：综合平台 `HotValue`、文章互动数据和 persona 匹配度。
- 按用户归档：每次运行保存报告、Top N、原始响应和文章正文。

## 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

安装依赖：

```bash
uv sync --dev
```

运行命令时将 `src` 加入 `PYTHONPATH`：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli --help
```

Windows PowerShell 可使用：

```powershell
$env:PYTHONPATH = "src"
uv run python -m heated_topics_v3.cli --help
```

## Profile v2

示例文件位于 `config/profiles/zhao_001.json`：

```json
{
  "user_id": "zhao_001",
  "level1": "科技AI",
  "level2": "AI工具应用",
  "personal": {
    "role": "经管学生视角的AI工具体验官",
    "subject": "AI工具",
    "scenarios": ["写作", "学习", "办公", "内容生产"],
    "value": "真实使用建议"
  },
  "core_keywords": ["AI工具", "AI写作", "AI办公", "AI学习"]
}
```

`personal` 的四个子字段和 `core_keywords` 均为必填项。Persona 发生变化时，系统会通过签名自动使旧的关键词缓存失效。

## 运行 Toutiao v2

### 无 LLM 模式

使用 `core_keywords` 作为检索词，不需要 API key：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao \
  --profile-v2 config/profiles/zhao_001.json \
  --output-root output \
  --cache-root cache \
  --top-n 10 \
  --no-llm
```

### MiniMax 模式

先通过环境变量配置密钥，密钥不要写入 profile、代码或 Git：

```bash
export MINIMAX_API_KEY="your-api-key"
export MINIMAX_BASE_URL="https://api.minimaxi.com/anthropic"
export MINIMAX_MODEL="MiniMax-Text-01"
```

然后启用所需能力：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao \
  --profile-v2 config/profiles/zhao_001.json \
  --output-root output \
  --cache-root cache \
  --top-n 10 \
  --llm-keywords \
  --llm-summary \
  --llm-rerank
```

主要参数：

| 参数 | 作用 |
| --- | --- |
| `--profile-v2 PATH` | 使用 v2 persona profile |
| `--profile PATH` | 使用旧版 profile 和旧版 Toutiao 流程 |
| `--top-n N` | 保留前 N 个候选，默认 10 |
| `--cache-root PATH` | 设置热榜、关键词和 LLM 缓存根目录 |
| `--llm-keywords` | 使用 LLM 从 persona 提炼检索词 |
| `--llm-summary` | 生成趋势与文章摘要 |
| `--llm-rerank` | 使用 LLM 重排候选 |
| `--no-llm` | 统一关闭全部 LLM 功能 |
| `--force-hot-board-refresh` | 忽略当日热榜缓存并重新抓取 |
| `--offline` | 只使用已有热榜缓存，不实时请求热榜 |

查看完整参数：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao --help
```

## 输出结构

每次运行使用独立目录，避免覆盖同一用户当天的历史结果：

```text
output/users/{user_id}/{YYYY-MM-DD}/run_{timestamp}/
├── report.md
├── focused.json
├── raw/
│   ├── hot_board.json
│   ├── search_{keyword}.json
│   └── article_info.json
└── articles/
    ├── 01_{title}.txt
    ├── ...
    └── summary.md
```

缓存默认位于：

```text
cache/
├── hot_board/{YYYY-MM-DD}.json
├── core_keywords/{user_id}.json
└── llm/{prompt_hash}.json
```

## 其他平台

其他平台继续使用旧版 profile：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli juejin \
  --profile config/profiles/tech_ai_creator.json \
  --output-root outputs
```

## 测试

```bash
PYTHONPATH=src uv run pytest -q
```

历史 Toutiao 热度实验保留在 `demos/toutiao_heat_filter/`，仅用于对比，不再作为正式采集入口。
