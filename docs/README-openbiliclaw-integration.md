# HeatedTopics × OpenBiliClaw 多用户推荐（v2）

CLI 接受 Excel 用户画像（4 列），按 user / date 分层目录输出每个用户的 top-N 热点素材（带标题、出处、URL、完整正文、热度），下游创作者按目录取用。

## 设计要点（v2 相对 v1 的变化）

- **输入**：Excel `.xlsx`，4 列 `user_id / track_1 / track_2 / persona`，真人填表成本极低
- **输出**：`{output_dir}/{user_id}/{YYYY-MM-DD}/recommendations.json` 三层目录，每用户每天一个文件
- **素材**：标题 / 出处 / URL / 完整正文（≤50000 字）/ 热度，**不含** LLM 写的 `reason`/`topic_label`/`confidence`（创作者要素材不要文案）
- **数据源**：默认 `both`（V3 hotlist + last30days，URL 去重）
- **配置**：CLI flag 大幅瘦身，移除 `--use-search`/`--prefer-search`/`--search-*`/`--providers`/`--config`/`--body-preview-chars`/`--data-dir` 等 V1 knob

## 快速开始

```bash
# 1. 启动 Ollama + bge-m3（用于 embedding）
ollama serve &
ollama pull bge-m3

# 2. 配 LLM Key
export OPENBILICLAW_LLM_API_KEY=...

# 3. 准备 users.xlsx（4 列；首行表头）

# 4. 跑
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users-excel users.xlsx \
  --output-dir recs/ \
  --last30days-cli-path "E:/.code/My/last30days-skill-cn/scripts/last30days.py" \
  --max-parallel 5 \
  --per-user-timeout 300
```

## users.xlsx 格式

4 列必填，第 1 行表头（支持中英文别名）：

| 列名（英文） | 列名（中文别名） | 必填 | 用途 |
|---|---|---|---|
| `user_id` | 用户ID / 用户编号 | ✅ | 唯一标识；用作输出目录名 |
| `track_1` | 第一赛道 / 赛道一 | ✅ | 灌入 openbiliclaw `interests`（驱动排序） |
| `track_2` | 第二赛道 / 赛道二 | ✅ | 同上；可与 track_1 同主题 |
| `persona` | 人设 / 画像 | ✅ | 写入 `personality_portrait`（引擎当前不消费，但保留供下游 / 未来扩展） |

空行自动跳过；缺 `user_id` 或 `track_1` 直接报错。

示例（任意一列填空字符串即视为缺值）：

| user_id | track_1 | track_2 | persona |
|---|---|---|---|
| u_001 | AI 大模型 | 副业 | 技术博主，35 岁 |
| u_002 | 美妆护肤 | 生活方式 | 25-30 岁女性 KOC |
| u_003 | 商业观察 | 创业故事 | 财经编辑 |

## 输出结构

```text
recs/
├── u_001/
│   └── 2026-08-01/
│       └── recommendations.json
├── u_002/
│   └── 2026-08-01/
│       └── recommendations.json
└── ...
```

每份 `recommendations.json` 形状：

```json
{
  "user_id": "u_001",
  "input": {"track_1": "AI 大模型", "track_2": "副业", "persona": "技术博主，35 岁"},
  "generated_at": "2026-08-01T12:34:56+08:00",
  "recommendations": [
    {
      "rank": 1,
      "title": "...",
      "url": "https://...",
      "source": "juejin",
      "heat": {"view": 12345, "like": 678, "comment": 90, "favorite": 12, "share": 5, "rank": 1},
      "body_text": "完整正文（≤50000 字）",
      "body_text_length": 4321,
      "body_truncated": false,
      "published_at": "2026-07-31T10:00:00"
    }
  ]
}
```

失败时输出（替换上面 `recommendations` 数组）：

```json
{
  "user_id": "u_001",
  "error": "no_candidates",
  "error_detail": "Fetched 0 articles from providers=['juejin']"
}
```

## CLI 完整 flag 表

| flag | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--users-excel PATH` | ✅ | — | 4 列 xlsx 路径 |
| `--output-dir DIR` | ✅ | — | 分层目录根 |
| `--limit N` |  | 8 | 每用户返回 top-N |
| `--max-parallel N` |  | 5 | 并发用户数；1 = 串行 |
| `--per-user-timeout SEC` |  | 300 | 单用户超时 |
| `--body-max-chars N` |  | 50000 | 正文截断阈值（超出标 `body_truncated: true`） |
| `--source {v3-hotlist,last30days,both}` |  | both | 候选源选择 |
| `--last30days-cli-path PATH` | source 含 last30days 时必填 | — | last30days `scripts/last30days.py` 路径 |
| `--last30days-days N` |  | 30 | last30days 回溯天数 |
| `--last30days-fetch-bodies` |  | on | 启用 `--fetch-bodies` |
| `--no-last30days-fetch-bodies` |  | — | 关闭 `--fetch-bodies` |
| `--last30days-timeout SEC` |  | 120 | per-user last30days 子进程超时 |

## 候选源（v3 / last30days / both）

| 模式 | 覆盖 | 备注 |
|---|---|---|
| `v3-hotlist` | 8 个 V3 provider | juejin / 头条 / 百度热榜 / 知乎热榜 / 知乎日报 / 新浪 / 澎湃 / 网易 |
| `last30days` | 8 个中文平台 | 详见 [README-last30days-source.md](README-last30days-source.md) |
| `both` | V3 + last30days，URL 去重 | 跨平台最大覆盖（默认） |

走 last30days 时 query 默认取用户的 `track_1`（v1 是 `--last30days-query` 共享词，v2 自动每用户不同）。

## 故障排查

| 错误 | 原因 | 修复 |
|---|---|---|
| `OpenBiliClaw patch missing` | `openbiliclaw-sandbox` 未打 patch | 在 `E:\code\My\openbiliclaw-sandbox` 重打 `serve_external_candidates` |
| `Missing env vars: OPENBILICLAW_LLM_API_KEY` | 没设 key | `export OPENBILICLAW_LLM_API_KEY=...` |
| `Ollama at ... unreachable` | Ollama 没启动 | `ollama serve` |
| `Ollama has no 'bge-m3' model` | 模型未拉 | `ollama pull bge-m3` |
| `Last30DaysSourceError` | last30days 子进程失败 | 检查 `--last30days-cli-path`、拉大 `--last30days-timeout` |
| `Last30DaysParseError` | 报告 JSON 损坏或格式变更 | 看 `data/last30days/<user_id>/last30days.json` |
| `Excel invalid: missing required columns` | xlsx 表头缺列 | 4 列都写上 |
| `Excel has zero users` | xlsx 没数据行 | 至少 1 行用户 |
| 退出码 1 | 部分用户失败 | 看每个 `recommendations.json` 的 `error` 字段 |
| 退出码 2 | 启动期配置错误 | 看 stderr（xlsx 缺失、env 缺失、`--source last30days/both` 但没 `--last30days-cli-path`） |
| 退出码 4 | 致命异常 | 看 stderr 堆栈 |

## CLI 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 所有用户成功 |
| 1 | 部分用户失败（仍写成功用户文件） |
| 2 | 启动期配置错误 |
| 3 | OpenBiliClaw 环境错误 |
| 4 | 致命异常 |
| 130 | 用户中断 |
