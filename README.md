# Toutiao 分支使用手册

## §1 项目是什么

HeatedTopics V3 的 toutiao 分支：为内容选题场景提供按用户画像驱动的头条热点采集、原文抓取和报告生成。

本分支只维护 Toutiao v2 流程；其他平台（Juejin / Weibo / Zhihu）继续在 main 分支。

非 LLM 跑得动（用 `core_keywords` + 启发式 persona 拆词），可选用 MiniMax LLM 做关键词提炼 / 摘要 / 重排。

## §2 数据流

```
profile (zhao_001.json)
       │
       ▼
关键词提炼 (LLM 或 core_keywords) → 5-10 个 ExtractedKeyword
       │
       ▼
日级热榜 (cache/hot_board/{date}.json, 含 is_toutiao_hot 标记)
       │
       ▼
Path A 构建 (build_hot_board_candidates)
       │
       ├── count ≥ min_hot_board_before_search → 直接进入评分
       │
       ▼
Path B/C 搜索补拉 (build_candidates, 跳过 search gate 时不调用)
       │
       ▼
原文抓取 (article_info content_html → 桌面 <article> → Path A 顶 N 兜底)
       │
       ▼
报告生成 (output/users/{user_id}/{date}/run_{ts}/)
```

## §3 四路径筛选策略

四路径共用同一组 `PathFilters`（`src/heated_topics_v3/toutiao_paths.py:51`），按以下顺序执行：

```
Path A  build_hot_board_candidates (热榜 + persona_keywords 命中过滤)
       │
       ├── 热榜候选数 ≥ min_hot_board_before_search → return Path A
       ▼
Path B  search(ExtractedKeyword)         → 命中 article_heat ≥ article_heat_min
       │
       ▼
Path C  is_toutiao_hot fallback            → 0 ≤ article_heat ≤ is_toutiao_hot_max_article_heat
       │
       ▼
Path D  metadata 兜底 (item.summary / item.title) — 已并入 Path B/C 的 fallback 分支
```

`min_hot_board_before_search` 是 skip-search 的总闸门：`src/heated_topics_v3/toutiao_paths.py:119` 处判断热榜候选数；满足阈值直接返回 Path A，不再触发搜索抓取（`src/heated_topics_v3/toutiao_paths.py:105`）。

| `PathFilters` 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `hot_board_min` | `1_000_000` | Path A 入场最低热度 |
| `article_heat_min` | `0` | Path B 入场最低热度 |
| `is_toutiao_hot_min_article_heat` | `0` | `is_toutiao_hot` 标记生效的最低热度 |
| `is_toutiao_hot_max_article_heat` | `500` | `is_toutiao_hot` 标记生效的最高热度 |
| `include_is_toutiao_hot_fallback` | `True` | 是否启用 Path C 兜底 |
| `search_pages` | `1` | 每个 keyword 搜索的翻页数 |
| `per_page` | `10` | 每页结果数 |
| `min_hot_board_before_search` | `5` | skip-search 阈值；达到此数 Path A 独占（`src/heated_topics_v3/toutiao_paths.py:59`） |

## §4 CLI

最小可跑（无需 API key）：

```bash
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao \
    --profile-v2 config/profiles/zhao_001.json \
    --no-llm --top-n 10
```

完整 LLM 模式（关键词 + 摘要 + 重排）：

```bash
export MINIMAX_API_KEY=...
export MINIMAX_BASE_URL=...
export MINIMAX_MODEL=...
PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao \
    --profile-v2 config/profiles/zhao_001.json \
    --llm-keywords --llm-summary --llm-rerank --top-n 10
```

| 参数 | 作用 | 是否必填 |
| --- | --- | --- |
| `--profile-v2 PATH` | 指向 `config/profiles/{user_id}.json` | 必填 |
| `--top-n INT` | 最终保留的候选条数 | 否（默认 `10`，`src/heated_topics_v3/cli.py:86`） |
| `--no-llm` | 完全跳过 LLM 调用 | 与各 `--llm-*` 互斥；启用后以下三项均被强制关闭 |
| `--llm-keywords` | LLM 提炼关键词 | 与 `--no-llm` 互斥；与 `--llm-summary` / `--llm-rerank` 彼此独立 |
| `--llm-summary` | LLM 生成文章摘要 | 与 `--no-llm` 互斥；可单独启用 |
| `--llm-rerank` | LLM 重排候选 | 与 `--no-llm` 互斥；可单独启用 |
| `--force-hot-board-refresh` | 忽略热榜缓存重新抓取 | 否 |
| `--offline` | 仅使用本地缓存，不发请求 | 否 |
| `--cache-root PATH` | 缓存根目录 | 否（默认 `cache`，`src/heated_topics_v3/cli.py:85`） |
| `--output-root PATH` | 输出根目录 | 否（默认 `outputs`，`src/heated_topics_v3/cli.py:83`） |

完整参数见 `--help`。

## §5 Profile schema

最小可跑示例（`config/profiles/zhao_001.json`）：

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

`personal` 四字段说明：

- `role` — 视角 / 身份定位，决定摘要口吻。
- `subject` — 关注的主题词，用于热榜与 persona 过滤。
- `scenarios` — 适用场景列表，影响关键词 `scenarios` 命中权重。
- `value` — 期望提供的价值，决定重排与摘要的取舍标准。

`core_keywords` 是非 LLM 模式的关键词种子（`src/heated_topics_v3/llm_keywords.py:6`），当 `--no-llm` 启用时直接落入 `ExtractedKeyword`。

> 修改 `personal.*` 任一字段都会让 `persona_signature` 漂移, 失效机制见 §6.

## §6 persona_signature 失效机制

`compute_persona_signature(level1, level2, personal)`（`src/heated_topics_v3/profile_loader.py:138`）把 6 个字段（`level1` / `level2` / `role` / `subject` / `scenarios` / `value`）做 `ensure_ascii=False` + `sort_keys=True` 的 canonical JSON（`src/heated_topics_v3/profile_loader.py:142`），再 `sha256` 取前 16 位（`src/heated_topics_v3/profile_loader.py:155`）。任何字段变更 → 签名不同 → `cache/core_keywords/{user_id}.json`（`src/heated_topics_v3/llm_keywords.py:23`）被判定失效，下次运行重新生成。契约由 `tests/test_profile_loader.py:79`、`tests/test_profile_loader.py:99` 与 `tests/test_llm_keywords.py:105` 共同锁定。

## §7 正文获取优先级

正文链路由 **Path 级预填充** + **单条 detail 兜底** 两层组成。优先级核心结论：**mobile API 的 `article_info.content_html` 永远优先于桌面页解析**。

**Path 级预填充**（在 `fetch_toutiao_item_details` 之前给所有候选填好正文，避免下游空 body）：

| 阶段 | 来源 | 说明 |
| --- | --- | --- |
| Path B/C 搜索循环 | mobile `article_info.content_html` | 搜索结果回流时调用 `attach_article_heat_fields`，把 `content_html` 写入 `raw_payload`（`src/heated_topics_v3/pipeline.py:355-366`） |
| Path A 顶 N enrichment | 同上, 补拉 | Path A 候选未进搜索循环，ranking 后用 `_enrich_top_path_a_candidates` 补拉一次 `article_info`（`src/heated_topics_v3/pipeline.py:469-506`） |

**单条 detail 兜底**（`fetch_toutiao_item_details` 内, `src/heated_topics_v3/providers/toutiao.py`）：

| 优先级 | 来源 | 触发场景 | 失败兜底 |
| --- | --- | --- | --- |
| 1 | mobile `article_info.content_html` | `raw_payload.content_html` 已存在且非空（搜索或 Path A enrichment 已写入） | 跳到优先级 2 |
| 2 | 桌面页 `<article>` 解析（`parse_toutiao_article_page`） | article_info 缺失或 desktop HTML 未被 JS 渲染时 | 跳到优先级 3 |
| 3 | metadata（`item.summary` / `item.title`） | 上述全部失败时仅落标题（`_partial_detail`, `src/heated_topics_v3/providers/toutiao.py:387`） | 输出文件只剩标题 |

`article_info` 对部分聚合型（aggregator）热搜主题会返回空 `content`，桌面页又 JS 渲染时落盘文件只包含标题，正文留空。

## §8 缓存目录

```
cache/
├── hot_board/{YYYY-MM-DD}.json      # 今日优先; 缺则 yesterday 兜底
├── core_keywords/{user_id}.json     # 7 天 TTL, persona_signature 触发失效
└── llm/{prompt_hash}.json           # sha256(model+system+prompt)[:24]
```

三条兜底规则：

- 热榜今日缺则回退昨日快照（`src/heated_topics_v3/hot_board_cache.py:36`）。
- 关键词缓存 7 天 TTL + 签名校验（`src/heated_topics_v3/llm_keywords.py:6` / `:24`）。
- LLM 缓存按 prompt hash 命中，重复请求不重复计费。

`--force-hot-board-refresh` 跳过热榜缓存，`--offline` 仅在热榜环节生效 — 把 `fetcher=None` 传给 `get_or_fetch_hot_board`，等于禁用当日热榜抓取、回退到 `cache/hot_board/{date}.json` 命中或 yesterday 兜底；其它阶段（搜索 / `article_info` / 桌面页解析）依然会发请求。

## §9 反爬梯子

抓取侧采用三阶段 fetcher 梯子（`src/heated_topics_v3/fetcher_factory.py:1`），按运行期失败率自动升降级。

| 阶段 | 实现 | 触发 |
| --- | --- | --- |
| 1 | `urllib + cookies`（`src/heated_topics_v3/fetcher_factory.py:143`） | 默认 |
| 2 | Playwright live Chromium | 阶段 1 连续失败 ≥ `DEMOTE_AFTER_FAILS=3`（`src/heated_topics_v3/fetcher_factory.py:57`） |
| 3 | DrissionPage live Chromium | 阶段 2 也连续失败 ≥ 3 次 |

阶段升级 / 降级 / 整段禁用规则与诊断细节见 [`docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md`](docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md)。该 spec 覆盖了热榜、搜索回包、桌面 `/article` 解析三阶段的失败模式诊断（不仅是搜索），是反爬梯子的完整因果说明书。

## §10 辅助脚本

| 脚本 | 一句话 |
| --- | --- |
| `tmp_3users_test/build_personas_from_xlsx.py` | 把人设 xlsx 批量转成 `config/profiles/{user_id}.json`（`--no-llm` / `--use-llm`，`--regenerate`）。 |
| `tmp_3users_test/harvest_cookies.py` | Playwright + DrissionPage 取 `toutiao.com` 首页 cookie 并 merge 到 `.toutiao_cookie`。 |
| `tmp_3users_test/run_pipeline.py` | 单用户烟测，打印 `kept_total` / `paths` / `fetcher.stage` 关键指标。 |

`tmp_3users_test/` 已 `.gitignore`，cookie 与 `fetcher_log` 不进仓库。

## §11 输出结构

```
output/users/{user_id}/{YYYY-MM-DD}/run_{YYYYMMDD_HHMMSS}/
├── report.md
├── focused.json
├── raw/
│   ├── hot_board.json          # 软链 → cache/hot_board/{date}.json
│   ├── search_{slug}.json      # 每个 keyword 一份
│   └── article_info.json       # {canonical_url: {impression_count, ...}}
└── articles/
    ├── 01_{slug}.txt
    ├── ...
    └── summary.md              # --llm-summary 时
```

## §12 测试

```bash
PYTHONPATH=src uv run pytest -q
```

整套 ~3100 行，包含 toutiao v2 端到端、四路径、persona 失效契约、jump URL 解包、anti-bot 降级等。