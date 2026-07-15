# Toutiao README Rewrite Design

## Purpose

The current `README.md` is 380+ lines covering the toutiao branch's full feature surface plus cross-platform (Juejin / Weibo / Zhihu / v1 profile) and cross-branch ("本分支相对 V3 的新增") commentary. With the branch gaining complexity — four-path filtering with a 5-result gate, daily hot-board caching, the three-stage anti-bot fetcher, persona v2 schema, persona_signature invalidation — readers wade through cross-branch context to find the toutiao-relevant lines. The new README trims to toutiao-only and surfaces the contract that handoff maintainers need to **use** and **modify** the pipeline without jumping between files.

## Audience

接手维护者 / 使用者. A maintainer who has the repo and needs to:

1. Run a hot-topic pipeline against a Toutiao persona within ~10 minutes of cloning.
2. Understand the four-path selection logic and the thresholds that gate it.
3. Modify a profile JSON or a `PathFilters` field and have it take effect on the next run.

## Out of Scope

The new README explicitly will NOT cover:

- **Other platforms** — Juejin / Weibo / Zhihu / legacy v1 Toutiao flow live on the `main` branch. Drop the "其他平台" section entirely.
- **Cross-branch delta** — "本分支相对 V3 的新增" comparison; git log / `git diff main..toutiao` carries that narrative.
- **21-row persona catalog** — `config/profiles/*.json` directory listing is the source of truth; the new README names `zhao_001.json` as the worked example and points readers to the directory.
- **Module index table** — `src/heated_topics_v3/` docstrings handle this. The exception is naming the 3-4 modules a maintainer will most likely touch (profile_loader / persona_structurer / toutiao_paths / llm_keywords).
- **Test file decomposition** — one `pytest` invocation covers everything; the per-file table is reference noise.
- **Anti-bot ladder detailed diagnosis** — `docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md` already does this in full. New README keeps 1 paragraph + 3-line table.

## Target Outline (≈ 230 lines)

| # | Section | Content | Lines |
| --- | --- | --- | --- |
| 1 | 项目是什么 | 5-line summary; explicitly state "本分支只维护 Toutiao", 其他平台见 `main`. | 5 |
| 2 | 数据流 | One ASCII: `profile → 热榜 → 候选 → 报告`. No per-path enumeration. | 22 |
| 3 | 四路径筛选策略 | Decision ASCII (Path A → count>=5 → return Path A; else Path B → C → D) + `PathFilters` field table. | 35 |
| 4 | CLI | 最小 (`--no-llm`) / 完整 (`--llm-keywords --llm-summary --llm-rerank`) two commands + parameter table. | 25 |
| 5 | Profile schema | `zhao_001.json` example + `personal` 四字段 + `core_keywords` 说明 + the rule that 改 `personal.*` 等于改检索词 (with cross-ref to §6). | 25 |
| 6 | persona_signature 失效机制 | One paragraph: 6 fields canonical JSON → sha256[:16]; any change invalidates `cache/core_keywords/{user_id}.json`. Reference this from §5, do not repeat the spec. | 12 |
| 7 | 正文获取优先级 | 4-row table (桌面页 `<article>` → mobile `article_info` content_html → Path A 顶 N 兜底 → metadata 兜底); 1 caveat paragraph (聚合型热搜会拿到空 content). | 15 |
| 8 | 缓存目录 | Directory tree + 1 line of fail-over rules (热榜 yesterday 回退 / 关键词 persona_signature 触发 / LLM 按 prompt hash). | 10 |
| 9 | 反爬梯子 | 1 sentence + 3-row table (stage 1 / 2 / 3 threshold: 3 consec-fails promote, 3 consec-successes demote, ≥50% fail-rate kills search path). Cross-ref to anti-bot spec. | 12 |
| 10 | 辅助脚本 | Three one-liners: `build_personas_from_xlsx.py` (xlsx → profile), `harvest_cookies.py` (cookie 采集), `run_pipeline.py` (单用户烟测). | 15 |
| 11 | 输出结构 | One tree: `output/users/{user_id}/{YYYY-MM-DD}/run_{timestamp}/{report.md, focused.json, raw/, articles/}`. | 12 |
| 12 | 测试 | One command + 1 line 解释 (`PYTHONPATH=src uv run pytest -q` covers the whole suite). | 5 |

**No other sections.**

## Section-by-Section Content Skeleton

### §1 项目是什么

```markdown
HeatedTopics V3 的 toutiao 分支：为内容选题场景提供按用户画像驱动的头条热点采集、原文抓取和报告生成。

本分支只维护 Toutiao v2 流程；其他平台（Juejin / Weibo / Zhihu）继续在 main 分支。

非 LLM 跑得动（用 `core_keywords` + 启发式 persona 拆词），可选用 MiniMax LLM 做关键词提炼 / 摘要 / 重排。
```

### §2 数据流

Single ASCII mirroring the existing pipeline diagram but trimming Path A/B/C enumeration. Keep stage arrows; drop sub-bullets (those move to §3).

### §3 四路径筛选策略

This is the only section allowed to be detailed. Reuse the structure from the section I just added (gates, threshold table, why `min_hot_board_before_search = 5`). This is the section the user wants maintained in full.

### §4 CLI

Two commands + parameter table. The `参数表` covers the parameters a maintainer will actually touch: `--profile-v2` / `--top-n` / `--no-llm` / `--llm-keywords` / `--llm-summary` / `--llm-rerank` / `--force-hot-board-refresh` / `--offline` / `--cache-root` / `--output-root`. Rarely-touched params (e.g., `--fetched-at`) may stay in the help output but are not in the parameter table.

### §5 Profile schema

`zhao_001.json` 完整示例（4 行）; `personal` 四字段说明; `core_keywords` 用途简介; 末尾一行 cross-ref to §6:

```markdown
> 修改 `personal` 任意字段会让 `persona_signature` 漂移, 见 §6.
```

### §6 persona_signature 失效机制

One paragraph; cite `compute_persona_signature(level1, level2, personal)` → 6-field canonical JSON → sha256 前 16 位; point to `cache/core_keywords/{user_id}.json` as the eviction target.

### §7 正文获取优先级

4-row table is non-negotiable here — Path A 顶 N 兜底 is a behavior contract, not a footnote.

### §8 缓存目录

Tree + 1-line rule of thumb:

```markdown
cache/
├── hot_board/{YYYY-MM-DD}.json      # 今日优先; 缺则 yesterday 兜底
├── core_keywords/{user_id}.json     # 7 天 TTL, persona_signature 触发失效
└── llm/{prompt_hash}.json           # 按 sha256(model+system+prompt)[:24]
```

### §9 反爬梯子

1 sentence + 3-row table. Cross-ref `docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md`.

### §10 辅助脚本

Three one-liners, listed without per-script parameter tables. The existing dense table in the current README is reference noise.

### §11 输出结构

Single tree; copy verbatim from the current README's "输出结构" section.

### §12 测试

One line: `PYTHONPATH=src uv run pytest -q` covers the suite (`tests/` ~3100 行). No per-file decomposition.

## Style Constraints

- **Tone**: terse, declarative. No "this is great", no "should be obvious".
- **Code in Chinese, comments in Chinese** (matches CLAUDE.md: 默认中文).
- **Citations**: include `path:line` for every code-level claim (e.g., `toutiao_paths.py:59` for the 5-threshold).
- **Markdown features allowed**: tables, code fences, single-emoji-free bullet lists, single ASCII diagram per section max.
- **Outlawed**: "TODO", "TBD", "see also" without an actual link.

## Acceptance Criteria

1. Line count of the new README is between 200 and 250 lines inclusive.
2. A first-time reader can run a `--no-llm` pipeline for `zhao_001.json` end-to-end without leaving the README.
3. Every field of the `PathFilters` dataclass (`hot_board_min` / `article_heat_min` / `is_toutiao_hot_*` / `include_is_toutiao_hot_fallback` / `search_pages` / `per_page` / `min_hot_board_before_search`) appears in §3's threshold table.
4. The body-fetch priority list appears as a table (not narrative) and includes the Path A 顶 N 兜底 row.
5. The persona_signature invalidation contract is stated and cross-referenced from §5.
6. No dedicated section covering `juejin` / `weibo` / `zhihu` / `pipeline_v1` / `V3 baseline`. A one-line scope clarification (e.g., "其他平台 maintained on main 分支") is allowed in §1 but no further mention.
7. No 21-row persona table.
8. The anti-bot section cites the dedicated spec rather than duplicating its diagnosis.
9. Every code-level claim carries a `path:line` citation.
10. The new README replaces the old `README.md` file (no `README_v3.md` or similar fallback file in the repo).

## Risk / Trade-off

The single risk is **information loss**: a maintainer who needs the V3-cross-section narrative or the anti-bot diagnosis inline will now have to follow a cross-reference. This is by design — the cost is one extra click; the gain is a README that someone will actually read top-to-bottom. If a maintainer reports a specific gap, the fix is to inline the missing 10 lines, not to revert to the longer form.

## Open Questions

None at design-approval time. The 12-section outline is the contract.

## Files

### Modified

- `README.md` — replaced in place.

### Untouched

- All code under `src/heated_topics_v3/`.
- All test files.
- All other branch docs (`docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md` and friends).
