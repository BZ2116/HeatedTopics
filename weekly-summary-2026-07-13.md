# Toutiao 分支 — 本周工作总结（2026-07-13 ~ 07-15）

> 时间：周一 ~ 周三，3 天
> 分支：`toutiao`（ahead of `main`：6 commits）
> 用途：明日口头汇报

---

## 一、本周做了什么（一句话版）

把"按 persona 拉头条热点"这件事从零搭起来，并把它修到了**真的能跑**的状态——profile → 关键词 → 热榜 → 4 路径筛选 → 原文抓取 → 报告全链路打通，附带修了一个把不同文章折叠成同一份正文的隐蔽 bug，并把对接维护者的 README 重写到了 230 行。

---

## 二、提交历史（6 commits，ahead of `main`）

| Commit | 日期 | 类型 | 做了什么 | 量级 |
|---|---|---|---|---|
| `f201679` | 7/13 20:30 | feat | **profile-driven 头条采集器**：CLI、contracts、热榜缓存、LLM 关键词、profile loader、4 路径、provider、报告渲染全套 + 22 个测试 | 28 文件 +6331/-31 |
| `5a56592` | 7/15 10:53 | fix | **正文格式保真 + Path A content_html 兜底**：`<p>/<div>` 不再被压成单空格；Path A 候选补拉 article_info 防 JS 渲染页正文空白 | 4 文件 +390/-50 |
| `21e5f90` | 7/15 17:26 | docs | README 重写设计 spec（12 节结构、10 条验收） | 1 文件 +151 |
| `f9b39f6` | 7/15 17:48 | docs | README 实际重写：380+ 行 → 230 行 toutiao-only 版 | 1 文件 -109/+144 |
| `ef86309` | 7/15 17:57 | docs | 代码评审抓住 5 处事实错误，全部修正（优先级顺序写反、互斥文案错位、跨平台越界等） | 1 文件 +22/-12 |
| `262126e` | 7/15 18:12 | docs | 头脑风暴 handoff：persona-文章关联度改进，选定方案 C，已讲完设计段一 | 1 文件 +96 |

**亮点**：从零到能跑只用了 3 天；review-after-commit 立刻抓出 5 处事实错误并修了（说明 review 在工作）。

---

## 三、未提交但已落地的工作（明天汇报可主动提）

这一波是"代码评审驱动的开发"——handoff 后接着把上周发现的问题从设计落到实现：

### 1. 修掉 `/search/jump` 把不同文章折叠成同一个正文的隐蔽 bug（**最关键**）

**症状**：Path B 搜索返回的 URL 是 `/search/jump?aid=...&url=...&h5_url=...%252Fgroup%252F{id}%252F`，整个 article_id 被埋在两层 URL 编码的 `h5_url` 里。原来用"去 query"做 dedup key，结果 3 篇不同文章都被压成 `/search/jump`，最后只剩 1 份正文写到 articles 目录里。

**三处统一修复**：
- `toutiao_output._canonical_url`：先调 `resolve_toutiao_content_url` 解开 shim 再去 query
- `toutiao_paths._dedup_key_for`：新方法，用 `extract_toutiao_article_id` 抽 article_id，dedup key 改成 `aid:{id}`
- `pipeline.run_toutiao_pipeline_v2`：调用 article_info 前先把 jump URL 解析成真实 article_id

**回归测试** 3 个：dedup 不塌、跨 keyword 同文章合并、article_info 被正确调用。

> 这条 bug 是上周跑端到端时发现的，没 commit 是因为等顺手把 5/4/1 关键词档位一起做。

### 2. 关键词档位 5/4/1 拆开（5 热榜 + 4 长尾 + 1 兜底）

源自头脑风暴方案 C 的"召回层"段一设计。

- `llm_keywords.py`：MIN_KEYWORDS 5→10；新增 `HOT_TARGET=5 / LONG_TAIL_TARGET=4 / FALLBACK_TARGET=1`；`_parse_keywords` 按 tier 分桶重平衡，缺位用 `core_keywords` 顶上
- prompt 改写：明确告诉 LLM "5+4+1=10 严格按此数量"
- 5 个测试用例覆盖：parse 桶化、core 兜底、code-fence 剥除、MIN_KEYWORDS 严格化

### 3. Path A search gate（`min_hot_board_before_search=5`）

热榜已经够 5 条候选时直接跳搜索，省一次抓取 + 抗反爬。

- `toutiao_paths.build_hot_board_candidates`（Path A only）从 `build_candidates` 拆出来
- orchestrator `build_candidates` 在 Path A ≥ 5 时直接 return
- `PathFilters` 新增 `search_pages=1` / `per_page=10` / `min_hot_board_before_search=5`
- 4 个测试覆盖：gate 命中跳过搜索、gate 不命中照常搜、hot_board 候选保留、空输入

### 4. `select_search_candidates_by_heat`：搜索结果自适应 top-N

新加的 `HeatSelection`（`high_threshold=10_000` / `min_high_count=5` / `fallback_top_n=15`）：
- ≥ 5 条搜索结果 article_heat ≥ 10k：只留这些（砍尾巴噪音）
- 否则：按 article_heat 降序保留 top 15

### 5. 新模块（两个文件，未 commit）

| 模块 | 作用 | 行数 |
|---|---|---|
| `src/heated_topics_v3/persona_structurer.py` | LLM 把 `level1/level2/persona_text` 整理成 `PersonaPersonal(role/subject/scenarios/value)`；附启发式 fallback 与 `extract_short_keywords` 短词抽取 | 349 |
| `src/heated_topics_v3/fetcher_factory.py` | 3 阶段反爬 fetcher：urllib+cookies → Playwright live → DrissionPage live；含 stage ladder 自动升降、4–8s jitter、5 次/60s 批休、≥50% 失败率自动 disable | 421 |

`tmp_3users_test/` 整套脚手架（cookie harvest、smoke test、profile 转换）都已落地。
测试：`tests/test_persona_structurer.py` 16 个用例（LLM 路径 6 + 启发式 5 + edge cases）。

### 6. 20 个新 persona profile（v2 schema）

`config/profiles/{caifu,chanyelian,feiyi,gongsi,gudian,gushi,hongguan,liangxing,licai,manbu,nanshigaizao,qiongyou,qiuxing,tongshi,xiaofei,xuesheng,yingjie,yiren,zhanlue,zijiu}_001.json`

加上原本的 `zhao_001` 一共 21 个 v2 格式 persona。命名规约 `xxx_001.json`，字段对齐 `user_id / level1 / level2 / personal{role,subject,scenarios,value} / core_keywords`，下游可以无脑轮询。

### 7. 工程基础改动

- `pyproject.toml`：`+ drissionpage>=4.0`（fetcher 第 3 阶段依赖）
- `.gitignore`：`+ tmp_3users_test/`（cookie 文件、fetcher_log.json 自动忽略）

---

## 四、文档成果

| 文档 | 路径 | 作用 |
|---|---|---|
| README（重写后） | `README.md` | 12 节 / 230 行 / toutiao-only；接手的同学能在 10 分钟内跑通 `--no-llm` |
| Anti-bot 设计 spec | `docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md` | 3 阶段 fetcher 的来龙去脉 + 失败检测 + 验收标准 |
| README 重写设计 spec | `docs/superpowers/specs/2026-07-15-toutiao-readme-rewrite-design.md` | 12 节大纲 + 10 条验收 |
| README 重写实施 plan | `docs/superpowers/plans/2026-07-15-toutiao-readme-rewrite.md` | 3 task / 27 step |
| **Persona-relevance brainstorm handoff** | `docs/superpowers/specs/2026-07-15-persona-relevance-handoff.md` | **明天接着干的入口** |

---

## 五、还差什么 / 下周计划

### 短期（明天就能接上的）

1. **persona-文章关联度改进**：brainstorm handoff 留了 4 段设计没讲完，明天接着走 → 写 `2026-07-16-persona-relevance-design.md` → 进 writing-plans → 落地 `apply_persona_relevance_score`（单次 LLM 0–3 打分）
2. 现有未提交的工作（§三 全部）跑一遍 pytest 整理成 commit

### 中期

3. 真实跑通 anti-bot fetcher（urllib + cookies 先试试 5 个关键词能否 ≥3 个召回）
4. 把 `apply_persona_relevance_score` 接入 `run_toutiao_pipeline_v2`，替换默认的 Path D rerank

---

## 六、汇报时可强调的几个点

1. **bug 修复那条最值得讲**——`/search/jump` 的三层嵌套 URL 把不同文章折叠成同一份正文，是端到端跑起来才暴露出来的。"去 query"做 dedup key 这种看上去无害的写法，碰上反爬 shim 就翻车。
2. **5/4/1 档位拆分的来源**——不是临时拍脑袋，是从"召回扩词"段一设计里推出来的；每档职责明确（热榜=流量、长尾=场景、兜底=保险），对应"先热榜不够再长尾还不够再兜底"的搜索策略。
3. **代码评审在工作**——README 提交后第二天就抓出 5 处事实错误并修了，主要是优先级顺序、CLI 互斥文案、跨平台越界这几类。"commit 后立刻 review"形成闭环。
4. **handoff 文档的价值**——明天接着干时不需要重新理解上下文，4 段设计 + 9 个未决问题清单已经写好。