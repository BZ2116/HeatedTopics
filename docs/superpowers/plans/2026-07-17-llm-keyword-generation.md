# LLM Keyword Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLM 基于用户画像进行有边界的语义扩展，返回 3–10 个优先短小且按热榜优先规则分档的检索关键词。

**Architecture:** 保持 `PersonaKeywordExtraction` 和缓存 JSON 契约不变，把数量、去重、截断与分档收敛到 `llm_keywords.py` 的确定性规范化逻辑中。提示词负责相关性、热度和长度偏好；代码只执行结构校验。少于 3 个有效结果时携带反馈重试，失败降级继续使用去重后的 `core_keywords`。

**Tech Stack:** Python 3.10+、pytest 8、标准库 `json` / `pathlib`、项目现有 LLM caller 与文件缓存。

## Global Constraints

- 去重后返回 3–10 个；少于 3 个才重试，最多保留 10 个。
- 相关性是硬约束，热度只用于相关候选之间的选择和排序。
- 中文概念优先为 2–3 个字符，但 `OpenAI`、`DeepSeek` 等不可合理缩写的专有实体必须保留。
- 分档按总数执行热榜优先：前 5 个热榜，第 6–9 个长尾，仅第 10 个兜底。
- 不检查关键词是否为原始字段的连续子串；允许直接相关的语义扩展。
- 不改变输出字段、缓存结构、搜索和排序流程。
- `src/heated_topics_v3/llm_keywords.py` 已有用户未提交改动。实施时先检查并保留；未经额外授权，不创建包含这些既有改动的代码提交。

---

## File Structure

- Modify: `src/heated_topics_v3/llm_keywords.py` — 提示词、解析规范化、数量门槛、重试、core 降级和缓存兼容。
- Modify: `tests/test_llm_keywords.py` — 单元与回归测试。
- Modify: `README.md` — 将旧数量和分档说明同步为新契约。

### Task 1: 锁定提示词、数量和重试契约

**Files:**
- Modify: `tests/test_llm_keywords.py`
- Modify: `src/heated_topics_v3/llm_keywords.py`

**Interfaces:**
- Consumes: `extract_persona_keywords(profile, *, cache_dir, ttl_days, use_cache, llm, allow_llm)`
- Produces: `MIN_KEYWORDS = 3`、`MAX_KEYWORDS = 10`；少于 3 个有效结果时最多调用 LLM 三次，并把不足数量写入后续 prompt。

- [ ] **Step 1: 记录重叠改动并写失败测试**

Run:

```bash
git diff -- src/heated_topics_v3/llm_keywords.py tests/test_llm_keywords.py
```

Expected: 显示当前关键词长度过滤、固定 10 个和重试相关的未提交改动。

在测试 import 中加入 `KEYWORD_EXTRACTION_SYSTEM`、`_build_prompt`，新增：

```python
def test_keyword_prompt_prioritizes_relevance_then_heat():
    prompt = _build_prompt(_profile())
    assert "3-10" in prompt
    assert "相关性是硬约束" in KEYWORD_EXTRACTION_SYSTEM
    assert "热度" in KEYWORD_EXTRACTION_SYSTEM
    assert "不要求原样出现" in KEYWORD_EXTRACTION_SYSTEM
    assert "优先 2-3 个字符" in KEYWORD_EXTRACTION_SYSTEM
    assert "专有实体" in KEYWORD_EXTRACTION_SYSTEM


def test_three_valid_keywords_do_not_retry(tmp_path: Path):
    calls = []

    def fake_llm(prompt: str, **_kwargs):
        calls.append(prompt)
        return json.dumps([
            {"keyword": "大模型", "match_expectation": "热榜"},
            {"keyword": "OpenAI", "match_expectation": "热榜"},
            {"keyword": "智能体", "match_expectation": "热榜"},
        ], ensure_ascii=False)

    result = extract_persona_keywords(
        _profile(), cache_dir=tmp_path / "kw", use_cache=False, llm=fake_llm,
    )
    assert len(calls) == 1
    assert MIN_KEYWORDS == 3
    assert [item.keyword for item in result.keywords] == ["大模型", "OpenAI", "智能体"]


def test_two_valid_keywords_retry_with_feedback(tmp_path: Path):
    calls = []
    responses = iter([
        [
            {"keyword": "大模型", "match_expectation": "热榜"},
            {"keyword": "智能体", "match_expectation": "热榜"},
        ],
        [
            {"keyword": "大模型", "match_expectation": "热榜"},
            {"keyword": "智能体", "match_expectation": "热榜"},
            {"keyword": "OpenAI", "match_expectation": "热榜"},
        ],
    ])

    def fake_llm(prompt: str, **_kwargs):
        calls.append(prompt)
        return json.dumps(next(responses), ensure_ascii=False)

    result = extract_persona_keywords(
        _profile(), cache_dir=tmp_path / "kw", use_cache=False, llm=fake_llm,
    )
    assert len(calls) == 2
    assert "上一次仅得到 2 个有效关键词" in calls[1]
    assert len(result.keywords) == 3
```

- [ ] **Step 2: 运行测试并确认因旧契约失败**

Run:

```bash
uv run pytest tests/test_llm_keywords.py::test_keyword_prompt_prioritizes_relevance_then_heat tests/test_llm_keywords.py::test_three_valid_keywords_do_not_retry tests/test_llm_keywords.py::test_two_valid_keywords_retry_with_feedback -q
```

Expected: FAIL；旧提示词仍固定 10 个/硬限制长度，3 个结果仍会补齐或重试。

- [ ] **Step 3: 最小实现提示词、常量和反馈重试**

设置：

```python
MIN_KEYWORDS = 3
MAX_KEYWORDS = 10
HOT_TARGET = 5
LONG_TAIL_TARGET = 4
FALLBACK_TARGET = 1
```

系统提示词必须完整表达：

```python
KEYWORD_EXTRACTION_SYSTEM = """你是中文搜索引擎关键词策划助手。请根据用户提供的 persona 生成检索关键词。

【决策顺序】
1. 相关性是硬约束：每个词必须能从一级赛道、二级赛道、角色、主题、场景、价值主张或核心词种子解释出直接联系。
2. 关键词不要求在原始字段中原样出现；允许生成直接相关的上位词、下位词、人物、品牌、产品和常见热点表达。
3. 在满足相关性的候选中，优先选择更可能召回热搜、热榜或高讨论度内容的词，不能为了热度引入无关词。

【数量和分档】
- 去重后生成 3-10 个；有 3 个高质量词即可，不得为了凑满 10 个加入弱相关词。
- 3-5 个：全部标记为「热榜」。
- 6-9 个：前 5 个标记为「热榜」，其余标记为「长尾」。
- 10 个：前 5 个「热榜」，接下来 4 个「长尾」，最后 1 个「兜底」。

【词形要求】
- 中文概念优先 2-3 个字符，使用核心名词或实体词，不写句子、问题或堆叠修饰语。
- OpenAI、DeepSeek 等不可合理缩写的专有实体可以超过 3 个字符并保留原名。
- 禁止「新闻」「热点」「今日」「最新」等没有独立主题含义的泛词。

【输出格式】
严格输出 JSON 数组，不要代码块或额外解释：
[{"keyword": "...", "match_expectation": "热榜|长尾|兜底"}, ...]
"""
```

`_build_prompt()` 使用“生成 3-10 个；相关性优先，在相关候选中优先热门”。`_extract_via_llm()` 使用最佳结果与反馈：

```python
def _extract_via_llm(profile, *, llm):
    base_prompt = _build_prompt(profile)
    prompt = base_prompt
    caller = llm or call_llm
    best = []
    for attempt in range(3):
        raw = caller(prompt, system=KEYWORD_EXTRACTION_SYSTEM,
                     max_tokens=1024, temperature=0.3)
        keywords = _parse_keywords(raw)
        if len(keywords) > len(best):
            best = keywords
        if len(keywords) >= MIN_KEYWORDS:
            return keywords
        if attempt < 2:
            prompt = (
                base_prompt
                + f"\n\n上一次仅得到 {len(keywords)} 个有效关键词，少于最低要求 3 个。"
                "请补充直接相关的候选，并严格输出 JSON 数组。"
            )
    return best
```

- [ ] **Step 4: 运行定向测试**

Run: 上一步的三项 pytest 命令。

Expected: `3 passed`。

### Task 2: 去重、截断、热榜优先分档和 core 降级

**Files:**
- Modify: `tests/test_llm_keywords.py`
- Modify: `src/heated_topics_v3/llm_keywords.py`

**Interfaces:**
- Produces: `_normalize_keywords(keywords: list[str]) -> list[ExtractedKeyword]`；`_parse_keywords(raw_text: str) -> list[ExtractedKeyword]`。

- [ ] **Step 1: 写规范化失败测试**

新增参数化分档测试：

```python
@pytest.mark.parametrize(("count", "expected"), [
    (3, (3, 0, 0)), (4, (4, 0, 0)), (5, (5, 0, 0)),
    (6, (5, 1, 0)), (7, (5, 2, 0)), (8, (5, 3, 0)),
    (9, (5, 4, 0)), (10, (5, 4, 1)),
])
def test_parse_keywords_uses_hot_first_tiers(count, expected):
    raw = json.dumps([
        {"keyword": f"词{i}", "match_expectation": "热榜"}
        for i in range(count)
    ], ensure_ascii=False)
    result = _parse_keywords(raw)
    by_tier = _by_tier(result)
    assert tuple(len(by_tier[t]) for t in ("热榜", "长尾", "兜底")) == expected


def test_parse_keywords_keeps_semantic_expansions_and_long_entities():
    raw = json.dumps([
        {"keyword": "大模型", "match_expectation": "热榜"},
        {"keyword": "OpenAI", "match_expectation": "热榜"},
        {"keyword": "DeepSeek", "match_expectation": "热榜"},
    ], ensure_ascii=False)
    assert [item.keyword for item in _parse_keywords(raw)] == [
        "大模型", "OpenAI", "DeepSeek",
    ]


def test_parse_keywords_deduplicates_and_caps_at_ten():
    words = ["大模型", "大模型"] + [f"词{i}" for i in range(12)]
    raw = json.dumps([
        {"keyword": word, "match_expectation": "热榜"} for word in words
    ], ensure_ascii=False)
    result = _parse_keywords(raw)
    assert len(result) == 10
    assert [item.keyword for item in result].count("大模型") == 1
```

- [ ] **Step 2: 运行测试确认旧解析失败**

Run:

```bash
uv run pytest tests/test_llm_keywords.py::test_parse_keywords_uses_hot_first_tiers tests/test_llm_keywords.py::test_parse_keywords_keeps_semantic_expansions_and_long_entities tests/test_llm_keywords.py::test_parse_keywords_deduplicates_and_caps_at_ten -q
```

Expected: FAIL；旧解析删除长实体、补齐到固定 10 个且依赖 LLM 分档。

- [ ] **Step 3: 实现统一规范化**

```python
def _normalize_keywords(keywords: list[str]) -> list[ExtractedKeyword]:
    unique = []
    seen = set()
    for keyword in keywords:
        normalized = keyword.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) == MAX_KEYWORDS:
            break

    result = []
    for index, keyword in enumerate(unique):
        if index < HOT_TARGET:
            tier = "热榜"
        elif index < HOT_TARGET + LONG_TAIL_TARGET:
            tier = "长尾"
        else:
            tier = "兜底"
        result.append(ExtractedKeyword(keyword, tier))
    return result
```

将 `_parse_keywords(raw_text)` 简化为：严格解析 JSON 数组；保留非空 `keyword` 且要求 `match_expectation` 属于合法值；随后调用 `_normalize_keywords()`。JSON 失败返回空列表，不再从任意文本正则猜词。

删除强制 2–3 字过滤、固定 10 个补齐、`fresh_padded` 分支、`_parse_fallback()` 与 `_pad_from_core()`。core 降级改为：

```python
def _fallback_from_core(profile: PersonaProfile) -> list[ExtractedKeyword]:
    return _normalize_keywords(list(profile.core_keywords))
```

- [ ] **Step 4: 更新冲突旧测试**

- 将固定补齐测试重命名为 `test_extract_persona_keywords_does_not_pad_valid_llm_output`，fake LLM 返回 3 个，断言恰好返回这 3 个且均为热榜。
- code fence 测试断言返回 fake 响应中的 5 个去重词。
- LLM unavailable 测试断言 core 结果按热榜优先分档，而非全部兜底。
- 长实体调用测试断言只调用一次并保留 `OpenAI` 等实体。
- 保留无效结构、签名失效与 `allow_llm=False` 回归。

- [ ] **Step 5: 运行关键词模块测试**

Run:

```bash
uv run pytest tests/test_llm_keywords.py -q
```

Expected: 全部 PASS，无 traceback。

### Task 3: 缓存兼容、文档与全量验证

**Files:**
- Modify: `tests/test_llm_keywords.py`
- Modify: `src/heated_topics_v3/llm_keywords.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `_read_cache()` 接受 1–10 个非空、结构合法的长实体缓存项。

- [ ] **Step 1: 写缓存失败测试**

```python
def test_cache_accepts_long_named_entities(tmp_path: Path):
    profile = _profile()
    cache_path = tmp_path / "kw" / f"{profile.user_id}.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({
        "user_id": profile.user_id,
        "persona_signature": profile.persona_signature,
        "generated_at": "2026-07-17T10:00:00+08:00",
        "keywords": [
            ["OpenAI", "热榜"], ["DeepSeek", "热榜"], ["大模型", "热榜"],
        ],
        "source": "fresh",
    }, ensure_ascii=False), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise AssertionError("valid cache should prevent an LLM call")

    result = extract_persona_keywords(profile, cache_dir=tmp_path / "kw", llm=boom)
    assert result.source == "cache"
    assert [item.keyword for item in result.keywords] == [
        "OpenAI", "DeepSeek", "大模型",
    ]
```

- [ ] **Step 2: 运行并确认旧缓存长度过滤失败**

Run:

```bash
uv run pytest tests/test_llm_keywords.py::test_cache_accepts_long_named_entities -q
```

Expected: FAIL，旧 `_read_cache()` 拒绝长实体并调用 `boom`。

- [ ] **Step 3: 放宽缓存读取**

单条只校验非空字符串和合法 tier：

```python
if not isinstance(kw, str) or not kw.strip():
    return None
if expectation not in VALID_EXPECTATIONS:
    return None
normalized.append((kw.strip(), expectation))
```

完整列表超过 `MAX_KEYWORDS` 时返回 `None`；允许少于 3 个，以兼容历史或降级缓存。

- [ ] **Step 4: 同步 README 与模块说明**

- 把 README 流程中的“5–10 个 ExtractedKeyword”改为“3–10 个”。
- 补充：相关性是硬约束；允许直接相关语义扩展；中文优先 2–3 字但保留必要实体；前 5 个热榜、第 6–9 个长尾、第 10 个兜底。
- 把 `llm_keywords.py` 顶部 docstring 的旧数量改成 `3-10`。

- [ ] **Step 5: 执行最终验证**

Run:

```bash
git diff --check -- src/heated_topics_v3/llm_keywords.py tests/test_llm_keywords.py README.md
uv run pytest tests/test_llm_keywords.py -q
uv run pytest -q
```

Expected: diff check 无输出；定向测试与全量测试全部 PASS。

- [ ] **Step 6: 审查改动范围**

Run:

```bash
git diff -- src/heated_topics_v3/llm_keywords.py tests/test_llm_keywords.py README.md
git status --short
```

Expected: 关键词相关 diff 与本计划一致；其他既有修改未被改写。不要自动提交 `llm_keywords.py`，因为其中包含实施前已有的重叠改动；若需要提交，先取得用户授权。
