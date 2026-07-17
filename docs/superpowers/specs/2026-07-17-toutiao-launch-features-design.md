# Toutiao Launch Features Design — 每日配额 + 自定义关键词

## Purpose

项目上线前需要两个面向"用法"的能力，都不涉及新算法：

1. **每日配额（quota）**：每个用户每天最多获取 N 次（默认 3）与其相关的热榜结果。第 N+1 次请求时后端直接报错 `今日额度已用完`，不再走流程。
2. **自定义关键词（custom keywords）**：本次调用临时传入一组检索关键词，**完全替换**该次运行的自动抽取关键词，按用户输入顺序检索匹配。

两者都是"一次热榜获取流程"的入口参数，不改变现有四路召回（Path A/B/C/D）与打分逻辑。

## Scope / Non-Goals

**做**：
- 后端提供默认配额上限，超限报错。
- CLI 支持自定义关键词（可重复传参），本次替换自动抽取。
- 配额状态按天持久化，跨天自动重置。

**不做（YAGNI）**：
- 不做配额并发锁（单用户单进程、前端串行调用）。
- 不做配额历史审计（只存当天 count）。
- 不做 custom keywords 持久化（每次临时传，不写 profile JSON）。
- 不做前端计数逻辑——前端可自管计数并用 `--skip-quota` 跳过后端配额。

## Architecture

```
src/heated_topics_v3/
├── quota.py            ← 新增：按天计数的 JSON 状态
├── cli.py              ← 改：解析新 flag，编排 check/commit
├── pipeline.py         ← 改：custom_keywords 参数 + on_search_committed 回调
└── llm_keywords.py     ← 复用 PersonaKeywordExtraction（custom 模式合成，不改文件）
```

**职责边界**：配额编排全部放 CLI 层。`pipeline` 不认识"配额"概念，只在"发起了搜索且流程走完"时回调一次 `on_search_committed()`。这样 pipeline 保持纯粹、可测。

### 计数语义（核心判据）

```
not skip_search               # 发起了搜索分支（哪怕搜索全失败）
  AND 流程跑到 write_toutiao_run 成功
→ on_search_committed()  → commit_quota +1
```

- "发起就计数"：只要触发搜索分支就算一次，不要求搜索返回非空。
- `skip_search=True`（hot_board 命中足够、Path A 直出）→ **不计数**（压根没发起搜索）。
- `skip_search` 是 pipeline 现有变量，判据即"它取反 + 流程走完"，无额外状态。

## Modules & Signatures

### `quota.py`（新增）

```python
class QuotaExceededError(Exception):
    """第 N+1 次调用时抛出，CLI 捕获后打印'今日额度已用完'并 exit(2)。"""

@dataclass(frozen=True)
class QuotaState:
    date: str
    count: int

def load_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """读取；文件不存在或 date≠today 都视为全新一天 count=0。"""

def check_quota(state: QuotaState, max_per_day: int) -> None:
    """count >= max_per_day 抛 QuotaExceededError；否则放行。不写盘。"""

def commit_quota(state_root: Path, user_id: str, today: str) -> QuotaState:
    """流程成功走完后 +1 并写盘，返回新状态。跨天从 1 开始。"""
```

**check/commit 分离**：进流程前 `check`（第 4 次直接拦，不浪费搜索）；搜索成功走完后才 `commit`。

### `pipeline.py`（改）

```python
def run_toutiao_pipeline_v2(
    ...,
    custom_keywords: tuple[str, ...] = (),                    # 非空则替换自动抽取
    on_search_committed: Callable[[], None] | None = None,    # 搜索成功回调
) -> ToutiaoV2Result:
```

custom 模式分支（**合成 extraction，不置空**，避免下游 `render_toutiao_report_v2` / `ToutiaoV2Result.keyword_source` 崩溃）：

```python
if custom_keywords:
    extraction = PersonaKeywordExtraction(
        user_id=profile.user_id,
        persona_signature=profile.persona_signature,
        generated_at=<utc8 now>,
        keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in custom_keywords),
        source="custom",
    )
    keyword_phrases = custom_keywords
    persona_keywords = custom_keywords        # 不拼 profile.core_keywords
else:
    extraction = extract_persona_keywords(...)
    keyword_phrases = tuple(k.keyword for k in extraction.keywords)
    persona_keywords = profile.core_keywords + keyword_phrases
```

- custom 词全标 `热榜` 档 → 走 Path B 搜索、优先召回。
- `tuple` 保序 + Path B 的 `for keyword in keyword_phrases` 循环 → 按用户输入顺序检索。
- 搜索分支跑完（`not skip_search` 且到 `write_toutiao_run`）后调 `on_search_committed()`。

### `cli.py`（改）

新 flag：

| flag | 默认 | 说明 |
|---|---|---|
| `--custom-keyword`（可重复） | 无 | `--custom-keyword 比特币 --custom-keyword 美联储` |
| `--state-root` | `state` | 配额文件根目录 |
| `--max-quota-per-day` | `3` | 每日上限 |
| `--skip-quota` | `False` | 前端集成时传，跳过后端配额 |

CLI 编排流程：
```
custom = tuple(k.strip() for k in args.custom_keyword if k.strip())
if not skip_quota:
    state = load_quota(state_root, user_id, today)
    check_quota(state, max_quota_per_day)     # 满则抛 → 打印 + exit(2)
run_toutiao_pipeline_v2(
    ...,
    custom_keywords=custom,
    on_search_committed=(None if skip_quota
                         else lambda: commit_quota(state_root, user_id, today)),
)
```

## Data Contracts

### 配额文件 `state/quota/{user_id}.json`

```json
{ "date": "2026-07-17", "count": 2 }
```

- 读时 `date≠today` → 视为 `count=0`（跨天自动重置）。
- `commit` 写回当天日期与新 count。

### custom 模式可见字段

- `focused.json` / `report.md` 的 `keyword_source` 值域新增 `"custom"`，本次跑是否为自定义一眼可辨。
- `keyword_count` = len(custom_keywords)。

### 配额耗尽输出

- **不产出任何 run 目录**。
- CLI stderr 打印 `今日额度已用完`，exit code `2`。

## Failure Modes

| # | 场景 | 行为 | 计数 | exit |
|---|---|---|---|---|
| 1 | 配额已满（第 4 次） | `check_quota` 抛错，打印 `今日额度已用完`，不进流程 | 否 | 2 |
| 2 | hot_board 今日失败 → 昨日兜底 | 正常出结果（现有逻辑） | 看是否发起搜索 | 0 |
| 3 | hot_board 今昨全失败 + Path A 直出（skip_search） | 仍产出，无搜索 → 不 commit | 否 | 0 |
| 4 | 搜索中途单个 keyword 异常 | 现有 try/except 吞掉该词，其余继续 | 是（发起了） | 0 |
| 5 | 全部搜索都失败/空结果 | 仍产出（可能只有 Path A） | 是（发起就计数） | 0 |
| 6 | `--custom-keyword` 全为空串 | strip 过滤后为空 → 回退自动抽取 | 同自动模式 | 0 |
| 7 | `commit_quota` 写盘失败（磁盘/权限） | 记 warning，不阻断已产出结果 | 尽力 | 0 |

## Testing

### `tests/test_quota.py`（新增）

```
test_load_quota_missing_file_returns_zero          # 文件不存在 → count=0
test_load_quota_stale_date_resets                  # date≠today → count=0
test_load_quota_same_day_reads_count               # 同天 → 读出 count
test_check_quota_under_limit_passes                # count<max 放行
test_check_quota_at_limit_raises                   # count>=max 抛 QuotaExceededError
test_commit_quota_increments_and_persists          # +1 且写盘可复读
test_commit_quota_stale_date_starts_from_zero      # 跨天 commit 从 1 开始
```

### `tests/test_pipeline_custom_keywords.py`（新增，fake fetcher）

```
test_custom_keywords_replace_extraction            # keyword_phrases==custom
test_custom_keywords_skip_core_keywords            # persona_keywords 不含 core
test_custom_keywords_synthesize_extraction         # source=="custom"，不为 None
test_custom_keywords_preserve_order                # 搜索顺序==输入顺序
test_empty_custom_keywords_fallback_to_auto        # 空串过滤后走自动
test_search_triggered_calls_commit_callback        # not skip_search → 回调被调
test_skip_search_does_not_call_commit_callback     # Path A 直出 → 回调不调
```

### `tests/test_cli_quota.py`（新增）

```
test_cli_quota_exceeded_prints_message_exit_2      # 第4次 → "今日额度已用完" + exit 2
test_cli_skip_quota_bypasses_check                 # --skip-quota → 不受配额限制
```

## Configuration

- **新目录** `state/quota/`（运行时生成，与 `cache/`、`outputs/` 同级）。
- **`.gitignore`**：加 `state/`。
- **README**：新增章节说明
  - `--skip-quota` 前端集成用法（前端自管计数时必传，因为本项目要被另一个项目集成）。
  - `state/quota/{user_id}.json` 结构。
  - 配额语义：发起搜索即计数、`skip_search` 直出不计数、跨天重置。
