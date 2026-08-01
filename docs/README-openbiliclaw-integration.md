# HeatedTopics × OpenBiliClaw 多用户推荐（v2.1）

CLI 接受 Excel 用户画像（4 列），按 user / date 分层目录输出每个用户的 top-N 热点素材（带标题、出处、URL、完整正文、热度），下游创作者按目录取用。

## 设计要点（v2.1 相对 v2 的变化）

- **LLM 关键词提取（v2.1 新增）**：每位用户首次运行时调 LLM，把 `{track_1, track_2, persona}` 提炼成 3 个精准中文搜索词，**替代** 原 `track_1/track_2` 作为 V3 search + last30days query。命中度比单赛道词好得多（窄众用户尤其明显）。
- **关键词缓存（v2.1 新增）**：结果按 `sha256(track_1|track_2|persona)` 缓存在 `{output_dir}/_keyword_cache/{user_id}/keyword_cache.json`。老用户修改了 track_1/track_2/persona 自动失效重抽。
- **可关闭（v2.1 新增）**：`--no-keyword-extraction` 回退到 v2 行为（直接用 `track_1/track_2`）。

## v2 相对 v1 的变化（背景）

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
| `--no-keyword-extraction` |  | — | 关闭 LLM 关键词提取；回退到 `track_1/track_2` 作查询词。默认开启（抽 3 个词，按用户缓存） |

## 候选源（v3 / last30days / both）

| 模式 | 覆盖 | 备注 |
|---|---|---|
| `v3-hotlist` | 8 个 V3 provider | juejin / 头条 / 百度热榜 / 知乎热榜 / 知乎日报 / 新浪 / 澎湃 / 网易 |
| `last30days` | 8 个中文平台 | 详见 [README-last30days-source.md](README-last30days-source.md) |
| `both` | V3 + last30days，URL 去重 | 跨平台最大覆盖（默认） |

走 last30days 时 query 来源（按优先级）：
1. v2.1 起：`extract_or_load` 抽出的 3 个关键词的**第一个**（命中度最高）
2. v2：`track_1`（兜底）

## 候选排序（v2.1.2）

候选进 OpenBiliClaw 引擎前会算一个 `relevance_score`，决定它们在 top-N 里的相对位置：

```
sim         = max(cosine(article_vec, kw_vec) for kw in keywords)   # 0-1
heat_factor = clamp(1/rank, 0.05, 1.0)
score       = sim * heat_factor                                    # 0-1
if sim < 0.3: drop article (pre-filter)
```

**关键词嵌入**：`extract_or_load` 抽完 3 个关键词后，每个调 `EmbeddingService.embed`（bge-m3，1024-d，L1+L2 缓存 → 重复跑免费）。如果全部失败，**退回 v2.1.1 的 `1/rank`** 行为，pipeline 不崩。

**文章嵌入**：对每条候选文章用 `title + summary + body[:300]` 调一次 embed。空 body 或 embed 失败 → 该候选被视为无信号，直接丢弃。

**Pre-filter**：sim < 0.3 的文章直接丢弃，根本进不了引擎；top-N 一定全是语义相关的。这是 v2.1.2 修掉 juejin Flutter UI / Apache Tika 跑进非遗用户推荐列表的根因。

**热度的角色**：保留为 tie-breaker。两个 sim=0.8 的候选里，rank-1 排前，rank-10 排后。但 sim=0.1 的 rank-1 永远打不过 sim=0.5 的 rank-50。

## 关键词缓存（v2.1）

LLM 抽出的关键词持久化在 `{output_dir}/_keyword_cache/{user_id}/keyword_cache.json`：

```json
{
  "spec_hash": "sha256 hex（来自 track_1|track_2|persona）",
  "keywords": ["非遗手工艺", "传统节气", "老字号"],
  "track_1": "文化生活",
  "track_2": "非遗与民俗",
  "persona": "研究地方习俗、节气、非遗和老手艺"
}
```

**失效逻辑**：

- `spec_hash` 变了（track_1 / track_2 / persona 任一修改）→ 失效重抽
- `user_id` 变了 → 视为新用户（hash 不包含 user_id）

**手动重抽**：删 `_keyword_cache/{user_id}/keyword_cache.json` 或修改 xlsx 让 spec_hash 变化。

**故障兜底**：LLM 调用失败（超时 / 解析失败 / 配额耗尽）→ 自动回退 `[track_1, track_2]`，pipeline 不会崩。

## 故障排查

| 错误 | 原因 | 修复 |
|---|---|---|
| `OpenBiliClaw patch missing` | `openbiliclaw-sandbox` 未打 patch | 在 `E:\code\My\openbiliclaw-sandbox` 重打 `serve_external_candidates` |
| `Missing env vars: OPENBILICLAW_LLM_API_KEY` | 没设 key | `export OPENBILICLAW_LLM_API_KEY=...` |
| `Ollama at ... unreachable` | Ollama 没启动 | `ollama serve` |
| `Ollama has no 'bge-m3' model` | 模型未拉 | `ollama pull bge-m3` |
| `Last30DaysSourceError` | last30days 子进程失败 | 检查 `--last30days-cli-path`、拉大 `--last30days-timeout` |
| `Last30DaysParseError` | 报告 JSON 损坏或格式变更 | 看 `data/last30days/<user_id>/last30days.json` |
| 关键词抽得不相关 / 离线时 LLM 不可用 | 关键词质量差或网络问题 | ① 看日志 `keyword cache hit`/`miss` 确认是否命中缓存；② 删 `_keyword_cache/<user_id>/` 强制重抽；③ 用 `--no-keyword-extraction` 回退 |
| 推荐全是空白 / top-8 少于 8 条 | sim threshold 把候选过滤光 | ① 检查关键词是否合理（看 `_keyword_cache/<user_id>/`）；② 删关键词缓存强制重抽；③ 临时把代码里 `sim_threshold=0.3` 调低 |
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
