# Toutiao README Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `README.md` with a lean, toutiao-branch-only version that lets a handoff maintainer (a) run a `--no-llm` pipeline for `zhao_001.json` end-to-end, (b) understand the four-path selection logic and the `PathFilters` knobs, (c) modify a profile JSON or threshold and have it take effect — without leaving the README except to read the anti-bot spec already referenced inside.

**Architecture:** Single-file markdown rewrite. The 10 acceptance criteria from `docs/superpowers/specs/2026-07-15-toutiao-readme-rewrite-design.md` (committed as `21e5f90`) are the contract; they map to a fixed set of `grep`/`wc` checks executed at the end of the rewrite. Two-staged: first draft into `README.md.new` (a scratch file at repo root) so reviewers can `cat` the whole new file in one place; second swap `mv README.md.new README.md` and commit. No code or test changes — `pytest` is not invoked.

**Tech Stack:** Markdown, `wc` and `grep` for verification, git.

---

## Pre-work

- [ ] **Step 1: Read the design spec**

Open `docs/superpowers/specs/2026-07-15-toutiao-readme-rewrite-design.md`. Internalize the 12-section outline (§1-§12), the content skeleton for each section, and the 10 acceptance criteria. Do not re-derive anything from the spec — the plan already references it.

- [ ] **Step 2: Establish baseline**

Run from repo root:
```bash
wc -l README.md
git status --short README.md
```
Expected: line count ~385 (current README plus the 4-path section added in the prior turn); `README.md` should be listed as `M` because earlier inserts left it modified. Note the baseline for diff comparison.

- [ ] **Step 3: Confirm target module line numbers are still valid**

The plan's `path:line` citations reference code lines that must match current code. Spot-check 3 anchors:

```bash
grep -n "min_hot_board_before_search" src/heated_topics_v3/toutiao_paths.py
grep -n "def compute_persona_signature" src/heated_topics_v3/profile_loader.py
grep -n "build_hot_board_candidates" src/heated_topics_v3/toutiao_paths.py
```
Expected: each `grep` returns one line, and that line matches the citation that will appear in the new README. If the code has drifted, fix the citation now (not after drafting the README) so the criterion #9 check stays meaningful.

---

### Task 1: Draft the new README in scratch

**Files:**
- Create: `README.md.new` (working file at repo root, NOT committed separately — replaced in Task 3)
- Reference: `docs/superpowers/specs/2026-07-15-toutiao-readme-rewrite-design.md`

**Style rules** (also in spec §"Style Constraints"):
- Terse, declarative. No praise / no padding.
- Chinese narrative, English code/identifiers.
- Every code-level claim uses `path:line` citation (no naked `Foo` references without a `src/.../*.py:NN` pointer).
- One ASCII diagram per section, max. Tables for thresholds and priorities.
- No emoji. No `TODO`/`TBD`.

- [ ] **Step 1: Write §1 项目是什么 (5 lines)**

Per spec §1:
```
HeatedTopics V3 的 toutiao 分支：为内容选题场景提供按用户画像驱动的头条热点采集、原文抓取和报告生成。

本分支只维护 Toutiao v2 流程；其他平台（Juejin / Weibo / Zhihu）继续在 main 分支。

非 LLM 跑得动（用 `core_keywords` + 启发式 persona 拆词），可选用 MiniMax LLM 做关键词提炼 / 摘要 / 重排。
```

- [ ] **Step 2: Write §2 数据流 (one ASCII, ~22 lines)**

Single ASCII diagram mirroring the high-level stages from the current README §"Toutiao v2 一图概览", but trimmed: drop the per-path enumeration (that lives in §3) and the multi-line per-call comments. Keep: profile → 关键词提炼 → 日级热榜 → search → 候选构造 → 报告 → 归档.

- [ ] **Step 3: Write §3 四路径筛选策略 (~35 lines)**

Two parts:
- Decision ASCII showing the path-A-only gate (`count >= min_hot_board_before_search → return Path A; else Path B → C → D`).
- Threshold table with **all 8 `PathFilters` fields**: `hot_board_min`, `article_heat_min`, `is_toutiao_hot_min_article_heat`, `is_toutiao_hot_max_article_heat`, `include_is_toutiao_hot_fallback`, `search_pages`, `per_page`, `min_hot_board_before_search`. Plus 1 line stating which field controls the skip-search gate, citing `src/heated_topics_v3/toutiao_paths.py:59`.

Reuse the structure from the section that was added to the OLD README at lines 80-130 (it has the correct gates), but adapt the surrounding context — the new section stands on its own.

- [ ] **Step 4: Write §4 CLI (~25 lines)**

Two complete commands:
1. `--no-llm` mode: `PYTHONPATH=src uv run python -m heated_topics_v3.cli toutiao --profile-v2 config/profiles/zhao_001.json --no-llm --top-n 10`.
2. Full LLM mode with 3 flags toggled on, preceded by env-var setup (`MINIMAX_API_KEY`, `MINIMAX_BASE_URL`, `MINIMAX_MODEL`).

Then a parameter table with columns `参数 / 作用 / 是否必填`. Rows for the 10 fields listed in spec §4. End with one line: `完整参数见 --help`.

- [ ] **Step 5: Write §5 Profile schema (~25 lines)**

Open with `config/profiles/zhao_001.json` example (~6 lines of JSON, indented). Then describe `personal` 四字段 (role / subject / scenarios / value) — 1 sentence each. Then 1 line on `core_keywords`. End with the trigger:
```
> 修改 `personal.*` 任一字段都会让 `persona_signature` 漂移, 失效机制见 §6.
```

- [ ] **Step 6: Write §6 persona_signature 失效机制 (~12 lines)**

One paragraph naming:
- `compute_persona_signature(level1, level2, personal)` (`src/heated_topics_v3/profile_loader.py`).
- The 6 fields canonical-JSON-encoded with `ensure_ascii=False` + `sort_keys` → `sha256[:16]`.
- The eviction target: `cache/core_keywords/{user_id}.json` gets invalidated on mismatch.
- Cite the pytest tests (`tests/test_llm_keywords.py` / `tests/test_toutiao_pipeline_v2.py`) that pin the contract.

- [ ] **Step 7: Write §7 正文获取优先级 (~15 lines)**

4-row table with columns `优先级 | 来源 | 触发场景 | 失败兜底`:
1. 桌面页 `/article`
2. mobile `article_info` content_html
3. Path A 顶 N 补拉 article_info
4. metadata (item.summary / item.title)

One caveat paragraph: `article_info` returns empty `content` for some聚合型 (aggregator) 热搜 topics, in which case files contain title only.

- [ ] **Step 8: Write §8 缓存目录 (~10 lines)**

Tree:
```
cache/
├── hot_board/{YYYY-MM-DD}.json      # 今日优先; 缺则 yesterday 兜底
├── core_keywords/{user_id}.json     # 7 天 TTL, persona_signature 触发失效
└── llm/{prompt_hash}.json           # sha256(model+system+prompt)[:24]
```

Plus 3 lines of fail-over rules (one per directory). Cite `src/heated_topics_v3/hot_board_cache.py` and the `--force-hot-board-refresh` / `--offline` CLI flags.

- [ ] **Step 9: Write §9 反爬梯子 (~12 lines)**

1 sentence introducing the 3-stage ladder. 3-row table with columns `阶段 | 实现 | 触发`. End with one cross-ref link to `docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md` (full URL, not just name). Do NOT paste the ladder diagnosis here (out of scope per spec).

- [ ] **Step 10: Write §10 辅助脚本 (~15 lines)**

Three one-liners:

| 脚本 | 一句话 |
| --- | --- |
| `tmp_3users_test/build_personas_from_xlsx.py` | 把人设 xlsx 批量转成 `config/profiles/{user_id}.json`（`--no-llm`/`--use-llm`, `--regenerate`）。 |
| `tmp_3users_test/harvest_cookies.py` | Playwright + DrissionPage 取 `toutiao.com` 首页 cookie 并 merge 到 `.toutiao_cookie`。 |
| `tmp_3users_test/run_pipeline.py` | 单用户烟测, 打印 `kept_total` / `paths` / `fetcher.stage` 关键指标。 |

End with: `tmp_3users_test/` 已 .gitignore, cookie 与 fetcher_log 不进仓库。

- [ ] **Step 11: Write §11 输出结构 (~12 lines)**

Tree:
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

- [ ] **Step 12: Write §12 测试 (~5 lines)**

```
```bash
PYTHONPATH=src uv run pytest -q
```
整套 ~3100 行, 包含 toutiao v2 端到端、四路径、persona 失效契约、jump URL 解包、anti-bot 降级等。
```

- [ ] **Step 13: Quick line-count sanity**

```bash
wc -l README.md.new
```
Expected: roughly 230. Out-of-range here is OK; the formal check is in Task 2 Step 1. If wildly off (>300 or <150), audit the per-step line budgets above.

---

### Task 2: Acceptance verification (10 criteria from the spec)

All commands run from repo root. If any step FAILS, fix `README.md.new` (don't fix the check) and re-run.

- [ ] **Step 1: Criterion #1 — line count 200..250**

```bash
lc=$(wc -l < README.md.new)
if [ "$lc" -ge 200 ] && [ "$lc" -le 250 ]; then echo "OK ($lc)"; else echo "FAIL ($lc)"; fi
```
If fail:
- `lc < 200`: pad §3's threshold table with one extra column or row; alternatively add 1 sentence to §6 explaining how the `sha256` length was chosen.
- `lc > 250`: trim §10 (collapse script table to a bullet list) first, then §11 (drop the `summary.md` conditional note).

- [ ] **Step 2: Criterion #2 — first-time reader can run a `--no-llm` pipeline**

Manual check: read §4 from top to bottom and verify the `--no-llm` block is runnable end-to-end against `zhao_001.json`:
- Profile path is in the command.
- `--no-llm` is on.
- Output/cache roots are explicit (defaults allowed if named in §4 prose).
- No instruction to set API keys in the `--no-llm` block.

- [ ] **Step 3: Criterion #3 — every PathFilters field appears**

```bash
for f in hot_board_min article_heat_min is_toutiao_hot_min_article_heat is_toutiao_hot_max_article_heat include_is_toutiao_hot_fallback search_pages per_page min_hot_board_before_search; do
  c=$(grep -c "$f" README.md.new)
  echo "$f: $c"
  [ "$c" -ge 1 ] || echo "MISSING: $f"
done
```
Expected: each row prints a count ≥ 1 and zero `MISSING:` lines.

- [ ] **Step 4: Criterion #4 — body-fetch priority is a 4-row table**

Inspect §7 manually: confirm the section header is followed by a markdown table with 4 data rows covering desktop / mobile / Path A 兜底 / metadata.

Count check:
```bash
awk '/^## §7 /,/^## §8 /' README.md.new | grep -cE '^\| '
```
Expected: ≥ 6 (1 header + 1 separator + 4 data).

- [ ] **Step 5: Criterion #5 — persona_signature 失效契约**

```bash
grep -n "persona_signature" README.md.new
```
Expected: ≥ 2 hits. The first is in §5 (forward cross-ref) and the second is in §6 (mechanism paragraph). Manually verify §6 names all 6 fields (level1 / level2 / role / subject / scenarios / value) and the sha256 truncation.

- [ ] **Step 6: Criterion #6 — no dedicated other-platform coverage**

```bash
grep -nE "juejin|weibo|zhihu|pipeline_v1|V3 baseline" README.md.new
```
Expected: at most 1 hit, located inside §1's one-line scope clarification. All other hits = FAIL → remove them.

- [ ] **Step 7: Criterion #7 — no 21-row persona table**

```bash
grep -nE "^\| (yingjie_001|gongsi_001|gudian_001|feiyi_001|yiren_001|qiongyou_001|zhanlue_001) " README.md.new
```
Expected: 0 hits (the table removed; the directory listing replaces it).

- [ ] **Step 8: Criterion #8 — anti-bot section cross-references the spec**

```bash
grep -F "2026-07-14-toutiao-search-anti-bot-design.md" README.md.new
```
Expected: ≥ 1 hit, located inside §9. The link must be a relative path, not a bare filename.

- [ ] **Step 9: Criterion #9 — code-level claims carry `path:line` citations**

```bash
grep -oE '`[A-Za-z0-9_/.]+\.py:[0-9]+`' README.md.new | sort -u | wc -l
```
Expected: ≥ 8 distinct citations. Spot-validate 3 random samples:

```bash
grep -oE '`[A-Za-z0-9_/.]+\.py:[0-9]+`' README.md.new | sort -u | shuf -n 3
for cite in $(grep -oE '`[A-Za-z0-9_/.]+\.py:[0-9]+`' README.md.new | sort -u | shuf -n 3 | tr -d '`'); do
  file="${cite%:*}"
  line="${cite##*:}"
  echo "=== $cite ==="
  sed -n "${line}p" "$file"
done
```
Expected: each cited line is on-topic for the surrounding README sentence.

> Note: the regex character class includes `0-9` so paths containing digits (e.g., `heated_topics_v3`) match. The original draft of this regex omitted digits and undercounted valid citations.

- [ ] **Step 10: Criterion #10 — single README, no fallback file**

```bash
ls README*.md
```
Expected: only `README.md` and (temporarily) `README.md.new`. No `README_v3.md` / `README_old.md` / similar.

---

### Task 3: Replace and commit

**Files:**
- Replace: `README.md` ← `README.md.new`
- Delete: `README.md.new`

- [ ] **Step 1: Move scratch into place**

```bash
mv README.md.new README.md
```

- [ ] **Step 2: Re-verify no regressions**

```bash
git diff --stat README.md
wc -l README.md
```

Expected: a single `README.md` modified, line count within 200..250. If out of bounds, return to Task 2 Step 1.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(toutiao): rewrite README to toutiao-branch-only

12-section lean structure (~230 lines) per
docs/superpowers/specs/2026-07-15-toutiao-readme-rewrite-design.md.

Drops:
- cross-platform section (juejin / weibo / zhihu / v1)
- "本分支相对 V3 的新增" cross-branch diff
- 21-row persona catalog
- module index table
- per-file test decomposition

Preserves the maintainer-relevant contract:
- PathFilters threshold table
- persona_signature invalidation mechanism
- body-fetch 4-tier priority
- anti-bot ladder (3 stages, cross-ref to dedicated spec)
- cache directory layout

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Final state check**

```bash
git log --oneline -2
git status
```

Expected: top commit is `docs(toutiao): rewrite README to toutiao-branch-only`; `git status` is clean.

---

## Self-Review Notes

After drafting this plan, the writer cross-referenced each spec section:

| Spec section | Plan task / step |
| --- | --- |
| §1 项目是什么 | Task 1 Step 1 |
| §2 数据流 | Task 1 Step 2 |
| §3 四路径筛选策略 | Task 1 Step 3 |
| §4 CLI | Task 1 Step 4 |
| §5 Profile schema | Task 1 Step 5 |
| §6 persona_signature 失效机制 | Task 1 Step 6 |
| §7 正文获取优先级 | Task 1 Step 7 |
| §8 缓存目录 | Task 1 Step 8 |
| §9 反爬梯子 | Task 1 Step 9 |
| §10 辅助脚本 | Task 1 Step 10 |
| §11 输出结构 | Task 1 Step 11 |
| §12 测试 | Task 1 Step 12 |
| AC #1 line count 200..250 | Task 2 Step 1 |
| AC #2 first-time reader runs `--no-llm` | Task 2 Step 2 |
| AC #3 every PathFilters field | Task 2 Step 3 |
| AC #4 body-fetch 4-row table | Task 2 Step 4 |
| AC #5 persona_signature contract | Task 2 Step 5 |
| AC #6 no dedicated other-platform section | Task 2 Step 6 |
| AC #7 no 21-row persona table | Task 2 Step 7 |
| AC #8 anti-bot cross-ref | Task 2 Step 8 |
| AC #9 code-level claims cited | Task 2 Step 9 |
| AC #10 single README file | Task 2 Step 10 |
| Files: replace `README.md` in place | Task 3 Steps 1-3 |

All 10 acceptance criteria mapped. No `TBD`/`TODO`/placeholder strings. No "fill in later" steps. Each task is runnable end-to-end and self-contained.
