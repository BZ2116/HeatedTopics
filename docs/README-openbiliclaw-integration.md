# HeatedTopics × OpenBiliClaw 多用户推荐（v2.1.7）

CLI 接受 Excel 用户画像，为每位用户生成独立目录：`input.json` 保存文章索引，`summary.txt` 汇总该用户的全部 query，`text/NN.txt` 保存每篇文章正文。

## v2.1.7 设计要点

- **单份整体摘要**：每个用户只生成一个 `summary.txt`，综合该用户命中的多个 query，不再按 query 拆分摘要文件。
- **正文独立落盘**：每篇文章正文写入 `text/01.txt`、`text/02.txt` 等文件，编号与推荐 rank 一致。
- **轻量文章索引**：`input.json` 的 `articles` 只保存元数据、query 来源和 `body_file`，不重复正文。
- **运行输入注册表**：`inputs/users.json` 记录本次运行的 `user_id → track_1/track_2/persona` 映射。
- **稳定用户编号**：桌面三列 Excel runner 使用 `u_<sha256(track_1\0track_2\0persona)[:8]>`，Excel 行顺序变化不会导致编号漂移。
- **LLM 关键词提取**：首次运行根据 `{track_1, track_2, persona}` 提炼查询词，并按 profile hash 缓存。
- **可关闭关键词提取**：`--no-keyword-extraction` 回退到直接使用 `track_1/track_2`。

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
<output-dir>/
├── inputs/
│   └── users.json
└── outputs/
    ├── u_001/
    │   ├── input.json
    │   ├── summary.txt
    │   └── text/
    │       ├── 01.txt
    │       └── 02.txt
    └── u_002/
        └── ...
```

`input.json` 示例：

```json
{
  "user_id": "u_001",
  "track_1": "AI 大模型",
  "track_2": "副业",
  "persona": "技术博主，35 岁",
  "generated_at": "2026-08-06T12:34:56+08:00",
  "recommendation_count": 1,
  "summary_file": "summary.txt",
  "articles": [
    {
      "rank": 1,
      "title": "...",
      "url": "https://...",
      "platform": "weibo",
      "query": "大模型应用",
      "heat": {"view": 12345, "like": 678, "comment": 90, "favorite": 12, "share": 5, "rank": 1},
      "published_at": "",
      "body_file": "text/01.txt"
    }
  ]
}
```

- `summary.txt`：一段中文整体简报，综合该用户的全部 query。
- `text/NN.txt`：对应 rank 文章的正文，最多 `--body-max-chars` 字符。
- `input.json` 不包含 `body_text`、`reason`、`topic_label` 或 `confidence`。
- 摘要失败时仍会创建空的 `summary.txt`，不影响正文消费。

## CLI 完整 flag 表

| flag | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--users-excel PATH` | ✅ | — | 4 列 xlsx 路径 |
| `--output-dir DIR` | ✅ | — | 分层目录根 |
| `--limit N` |  | 8 | 每用户返回 top-N |
| `--max-parallel N` |  | 5 | 并发用户数；1 = 串行 |
| `--per-user-timeout SEC` |  | 300 | 单用户超时 |
| `--body-max-chars N` |  | 50000 | 每个 `text/NN.txt` 的正文截断上限 |
| `--source {v3-hotlist,last30days,both}` |  | both | 候选源选择 |
| `--last30days-cli-path PATH` | source 含 last30days 时必填 | — | last30days `scripts/last30days.py` 路径 |
| `--last30days-days N` |  | 30 | last30days 回溯天数 |
| `--last30days-max-queries N` |  | 3 | 每用户最多运行的 last30days query 数 |
| `--last30days-low-water-mark N` |  | 3 | 候选数超过该值时停止扩展 query |
| `--last30days-fetch-bodies` |  | on | 启用 `--fetch-bodies` |
| `--no-last30days-fetch-bodies` |  | — | 关闭 `--fetch-bodies` |
| `--last30days-timeout SEC` |  | 120 | per-user last30days 子进程超时 |
| `--no-keyword-extraction` |  | — | 关闭 LLM 关键词提取；回退到 `track_1/track_2` 作查询词 |
| `--min-view-count N` |  | 0 | 最低浏览量；0 表示不筛选 |
| `--heat-source {rank,view}` |  | rank | 相关性分数中的热度来源 |
| `--llm-refilter` |  | off | embedding 预筛后再做 LLM 人设相关性过滤 |

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
if sim < 0.5: drop article (pre-filter)
```

**关键词嵌入**：`extract_or_load` 抽完 3 个关键词后，每个调 `EmbeddingService.embed`（bge-m3，1024-d，L1+L2 缓存 → 重复跑免费）。如果全部失败，**退回 v2.1.1 的 `1/rank`** 行为，pipeline 不崩。

**文章嵌入**：对每条候选文章用 `title + summary + body[:300]` 调一次 embed。空 body 或 embed 失败 → 该候选被视为无信号，直接丢弃。

**Pre-filter 阈值 0.5 的来源**（bge-m3 中文短文实测）：完全离题的文章（如 Flutter UI）sim 落在 0.30-0.42；强相关内容 sim 起点约 0.50；0.50 是干净的分离点。比 0.3 高很多，否则噪声文章会污染推荐列表。

**热度的角色**：保留为 tie-breaker。两个 sim=0.8 的候选里，rank-1 排前，rank-10 排后。但 sim=0.1 的 rank-1 永远打不过 sim=0.5 的 rank-50。

## 关键词缓存（v2.1）

LLM 抽出的关键词持久化在 `{output_dir}/_keyword_cache/{user_id}/keyword_cache.json`：

```json
{
  "spec_hash": "sha256 hex（来自 track_1\\0track_2\\0persona）",
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
| 推荐全是空白 / top-8 少于 8 条 | sim threshold 把候选过滤光 | ① 检查关键词是否合理（看 `_keyword_cache/<user_id>/`）；② 删关键词缓存强制重抽；③ 临时把代码里 `sim_threshold=0.5` 调低 |
| `Excel invalid: missing required columns` | xlsx 表头缺列 | 4 列都写上 |
| `Excel has zero users` | xlsx 没数据行 | 至少 1 行用户 |
| 退出码 1 | 部分用户失败 | 查看对应 `outputs/<user_id>/` 是否缺少推荐，结合 CLI 日志定位原因 |
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
