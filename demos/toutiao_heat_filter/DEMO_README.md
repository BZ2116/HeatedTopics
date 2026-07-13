# Toutiao Heat Filter Demo

`demo.py` 是验证 Toutiao HotValue、article info 和复合热度阈值的历史实验脚本，不再作为正式采集入口，也不再承接新功能。

正式流程使用 profile v2、日级热榜缓存、persona 关键词、四路径筛选和按用户归档输出：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao \
  --profile-v2 config/profiles/zhao_001.json \
  --output-root output \
  --cache-root cache \
  --top-n 10 \
  --no-llm
```

启用 MiniMax LLM 功能时，按项目环境配置 API，执行：

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

输出位于 `output/users/{user_id}/{YYYY-MM-DD}/run_{timestamp}/`，缓存位于 `cache/hot_board/`、`cache/core_keywords/` 和 `cache/llm/`。
