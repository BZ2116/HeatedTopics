# Persona-文章关联度改进 — Handoff 文档

> 状态:Brainstorming 中途中断。已选定方案 C、已讲完设计第一段(召回/排序/LLM/可视化),还有 4 段设计未讲完,**未生成最终 design 文档、未进入 writing-plans 阶段**。
> 接续时:从此文档继续 brainstorm,先把 4 段剩余设计走完 → 写 `2026-07-16-persona-relevance-design.md` → 进 writing-plans。

---

## 1. 用户原始诉求

> "接下来的任务是怎么把检索出来的热度文章与用户的关联度提高。"

关系:v2 的 `run_toutiao_pipeline_v2` 链路(`src/heated_topics_v3/toutiao_paths.py`、`hybrid_score_v2`、`extract_persona_keywords`)。

## 2. 已确认的约束(用户回答)

| 维度 | 已定结论 |
|------|----------|
| 优化对象 | v2 persona-driven(toutiao_paths 主流链路)。v1 的 `matching.py` 暂时不动 |
| 主要痛点(全选) | 假阳(关键词命中但语义不相关)、假阴(语义相关但无关键词命中)、排序错(被高热度不相关冲走)、关键词质量差 |
| LLM 预算 | 单次 pipeline 只能**额外多跑 1 次 LLM**。原 `extract_persona_keywords` 调用视作已存在,可保留 |
| 评估方式 | **人眼看几个例子**——需要每条候选都给出"为什么入选"的解释字段,方便快速判断 |
| 选定方案 | **方案 C** — 双层召回 + LLM 0-3 语义打分 |

## 3. 当前项目关键代码位置(已经摸清)

- `src/heated_topics_v3/llm_keywords.py` — 10 个关键词(5 热榜/4 长尾/1 兜底),`ExtractedKeyword(keyword, match_expectation)`,7 天缓存
- `src/heated_topics_v3/toutiao_scoring.py` — `hybrid_score_v2` 给 `persona_matched` 加 `+0.3` boost,纯子串包含判断
- `src/heated_topics_v3/toutiao_paths.py` — Path A 热搜 / Path B 关键词搜 / Path C is_toutiao_hot 兜底 / Path D `apply_llm_rerank`(存在,默认关闭)。`Candidate` dataclass 是核心数据
- `src/heated_topics_v3/pipeline.py` — `run_toutiao_pipeline_v2` 是主入口,大致步骤:load profile → extract keywords → 取/存 hot board → 关键词搜 → article_info 补字段 → 构 candidate → 选 → 可选 rerank → 排序 → top_n → fetch detail → render → write
- `src/heated_topics_v3/toutiao_output.py` — `write_toutiao_run` 写 `focused.json` 和 `articles/{idx}_{slug}.txt`(是显示载体)
- `src/heated_topics_v3/reporting.py` — `render_toutiao_report_v2` 渲染 markdown 报告

## 4. 已讲完的设计(段一)— 等用户确认

### 4.1 召回层(无 LLM 改动)
- `ExtractedKeyword` dataclass 增字段 `core_axis: "primary" | "secondary"`,primary = level1/level2/直接场景词,secondary = 兜底/扩词
- 新增 `expand_search_phrases(extraction, persona)`,从已有 10 个关键词查 jieba 同义词 + 与 `personal.scenarios` 取交集/并集启发式生成,目标每词扩 2-4 个,总数上限 ~40
- 搜索阶段多一轮 expanded_phrases 召回,产物走 Path B 同一条 pipeline(独立 `raw_search_by_keyword`)

### 4.2 排序层(无 LLM 改公式,只接 LLM 输出)
- `hybrid_score_v2` 公式不改,但**新增 `persona_match_strength: float` 替代布尔 `persona_matched`**——由命中关键词数量、核心轴命中加权成 0.0~2.0
- heat 仍 log10 + 偏移;不动这部分公式,以兼容历史 cache
- `Candidate` 增字段 `relevance_score: float | None` 与 `relevance_reason: str | None`

### 4.3 单 LLM 调用 `apply_persona_relevance_score`
- 输入: top ~20 候选(按 hybrid 排序前 20),每条 title + summary + 前 200 字正文(若已 enriched) + persona 摘要
- 输出: JSON `[{index, score ∈ {0,1,2,3}, reason}]`
- 映射:`score=0 → -2.0`、`1 → -0.5`、`2 → 0.0`、`3 → +1.0`,作为 final rank 的相对调整
- 兜底:`LLMUnavailable` 或 JSON 不可解 → 全部置 0、保留原排序、记日志
- 替换 Path D 的原 rerank;原 `apply_llm_rerank` 保留作 fallback,通过 `--llm-rerank` flag 走旧路径

### 4.4 可视化输出
- `focused.json` 每条 row 加 `relevance_score`(0-3)与 `relevance_reason`
- `articles/{idx}_{slug}.txt` 头部加 `Persona relevance: {score} - {reason}`
- `report.md` top N 表格加「与你相关」列(0-3 + 一句话理由)

## 5. 还没讲的 4 段(明天继续)

按 brainstorming skill 流程,设计文档一般分这几块。**前 1 段已讲,剩 4 段:**

- **段二**:函数签名 / 数据契约 / 输入输出格式(`apply_persona_relevance_score` 的 prompt schema、PersonaContext 在 LLM 入参里的呈现方式)
- **段三**:失败模式 / 错误处理(`LLMUnavailable` / JSON 失败 / cache 污染 / `extract_persona_keywords` 加 `core_axis` 字段后旧 cache 兼容性)
- **段四**:测试策略(单元 + 集成,fake LLM 的 fixture、`hybrid_score_v2` 改 strength 后回归旧 case)
- **段五**:配置与默认值(PathFilters 默认值是否动、CLI flag 是否调整、`expansion` 是否单独有开关)

## 6. 未决问题(明天继续 brainstorm 时要先问用户或自己决定)

下列问题目前没明确结论,接续时建议你直接先解决再讲段二:

1. **同义词表来源**:jieba 自带 / 哈工大同义词林(需要额外下载) / 纯启发式(从 persona.scenarios 抽取)? 推荐 jieba 自带 + 启发式,不引入额外数据文件
2. **expanded_phrases 上限**:30? 40? 50? 该值会影响 Path B 搜索次数与抗反爬压力
3. **top_k for LLM scoring**:默认 20,够不够? top 20 包含的 token 量级 ~200-300 中文字,加上 persona prompt 一次 LLM 调用约 2-3k tokens,安全
4. **score→boost 映射**:上面给的 `-2/-0.5/0/+1` 是否合理? 取决于项目偏"严打不相关"还是"宁错杀"——待与用户对齐
5. **老 Path D rerank 留不留**:建议保留作为 `--llm-rerank` 的 flag 选项,但默认走新打分
6. **缓存策略**:`extract_persona_keywords` 加 `core_axis` 字段后,**旧 cache 文件需要 invalidate**——可考虑加版本号或 `cache_version` 字段触发 cache busting
7. **`extract_persona_keywords` 数量 5/4/1 是否调**:最好不要动,扩词交给 `expand_search_phrases` 做,避免 LLM prompt 变化引起 cache 抖动
8. **failing 模式**:`LLMUnavailable` 时是直接跑(走原排序)还是报错停? 倾向继续跑并打 warning,与现有 fallback 一致
9. **评估脚本**:要不要加一个 `scripts/show_focused.py` 之类的工具,把 `focused.json` 渲染成可读视图方便"人眼看几个例子"? 评估方式选定后必要

## 7. 复盘建议(可选,明天继续前可参考)

- **本次 brainstorm 的盲点**:我没问你"现有 top N 中,假阳 vs 假阴的比例哪个更高"。如果假阳多,排序和可视化更重要;如果假阴多,扩展召回和 LLM 打分更重要。这影响段二设计的重心
- **没问的资源问题**:`extract_persona_keywords` 已经把"一次 LLM 抽词"用完了——那么新加的 `apply_persona_relevance_score` 是**唯一**允许的额外 LLM 调用。要确认你对这个约束的解读符合我猜的"原关键词抽取不计"
- **schema 兼容性**:`Candidate` 加 `relevance_score`/`relevance_reason` 是新字段,旧 raw_search JSON 与 focused.json 不向下兼容——已写明的 outputs 不需要回填,但需要明确写进 spec

## 8. 明日接续 checklist

```
[ ] 先回应上面 6.1 / 6.4 / 6.6 / 6.9 这几个最值得先定的问题
[ ] 接着 brainstorm 讲设计段二(函数/契约)
[ ] 段三(失败模式),重点 6.3、6.6、6.8
[ ] 段四(测试)— 现有测试在 tests/ 目录里,先看一眼现状再设计
[ ] 段五(配置/CLI)
[ ] 全部讲完后,把整篇设计写到 2026-07-16-persona-relevance-design.md
[ ] Spec 自审 → 让用户审 → 切 writing-plans
```
