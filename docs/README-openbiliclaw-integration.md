# HeatedTopics × OpenBiliClaw 多用户推荐

CLI 接受多用户 JSON 画像，输出每个用户的 top-N 热点文章推荐（带热度、正文、理由、置信度）。

## 快速开始

```bash
# 1. 启动 Ollama + bge-m3
ollama serve &
ollama pull bge-m3

# 2. 配 LLM Key
export OPENBILICLAW_LLM_API_KEY=...

# 3. 准备配置
cp config/openbiliclaw.toml.example config/openbiliclaw.toml

# 4. 准备 users.json (见 tests/openbiliclaw_integration/fixtures/users_valid_3users.json)

# 5. 跑
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users users.json --output recs.json
```

## users.json 格式

必填：`user_id` + `interests`（≥1 个）。其余字段可选，详见 spec §数据流。

完整示例：`tests/openbiliclaw_integration/fixtures/users_valid_3users.json`。

## 输出 recs.json 格式

```json
{
  "generated_at": "2026-07-28T12:34:56Z",
  "config_version": "0.3.186+mur.1",
  "llm_model": "MiniMax-M2.7",
  "embedding_model": "bge-m3",
  "users": [
    {
      "user_id": "u1",
      "display_name": "...",
      "input_profile_summary": {...},
      "pipeline": {...},
      "recommendations": [
        {
          "rank": 1,
          "title": "...",
          "url": "...",
          "source_platform": "juejin",
          "heat": {"view": ..., "like": ..., "comment": ..., "rank": ...},
          "body_text_preview": "前 800 字…",
          "body_text_length": 2340,
          "topic_label": "...",
          "reason": "...",
          "confidence": 0.78,
          "published_at": "..."
        }
      ]
    }
  ]
}
```

## 故障排查

| 错误 | 原因 | 修复 |
|---|---|---|
| `OpenBiliClaw patch missing` | `openbiliclaw-sandbox` 未打 patch | 在 `E:\code\My\openbiliclaw-sandbox` 重打 `serve_external_candidates` |
| `Missing env vars: OPENBILICLAW_LLM_API_KEY` | 没设 key | `export OPENBILICLAW_LLM_API_KEY=...` |
| `Ollama at ... unreachable` | Ollama 没启动 | `ollama serve` |
| `Ollama has no 'bge-m3' model` | 模型未拉 | `ollama pull bge-m3` |
| 退出码 1 | 部分用户失败 | 看 recs.json `users[].error` 字段 |
| 退出码 4 | 写文件失败 | 检查 `--output` 路径权限 |

## CLI 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 所有用户成功 |
| 1 | 部分用户失败 |
| 2 | 启动期配置错误 |
| 3 | OpenBiliClaw 环境错误 |
| 4 | 写文件失败 |
| 130 | 用户中断 |