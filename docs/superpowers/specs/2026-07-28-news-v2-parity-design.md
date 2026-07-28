# Sina / NetEase News 与 Toutiao v2 对齐 Design

- Status: Draft
- Owner: 本地单人
- Source ID: `sina_news`、`netease_news`、`toutiao`（仅 keyword_cap 一处收紧）
- 关联：在已落地的 sina-news / netease-news v2 基础上，对齐 Toutiao v2 的三处能力 —— `custom_keywords`、配额 hook、`hot_board_source` 标签

## Goal

让 `sina-news` / `netease-news` 在 CLI 表面与运行结果上，与 `toutiao --profile-v2` 行为完全一致；同时把 Toutiao 的 `custom_keywords` 收紧到与新闻类相同的 5 上限。

具体三件事：

1. `custom_keywords`：sina-news / netease-news 接受 `--custom-keyword`，自定义关键词来源走 `source="custom"`；与 Toutiao 同款
2. 配额 hook：sina-news / netease-news 接入 `state/quota/{user_id}.json`，每日 3 次上限；与 Toutiao 同款语义
3. `hot_board_source` 字段：`SinaNewsV2Result` / `NeteaseNewsV2Result` 增加 `hot_board_source: str` 字段并在 CLI 打印

附带：

4. Toutiao v2 的 `custom_keywords` 走 `keyword_cap=5`（与新闻类的 `[:5]` 一致），超出截断
5. 所有三处 `extraction.source` 取值与 `keyword_count` 保持一致：custom → `keyword_count = min(实际传入, 5)`；core_keywords → `keyword_count = min(profile.core_keywords 长度, 5)`

## Out Of Scope（明确不做）

- 改动 fetcher、cache、article_info 等下层模块
- 改 PathFilters 默认值（`hot_board_min=1000` 等保持平台现状）
- 改动 `baidu` / `bilibili` / `juejin` 流水线
- 跨源 TopicCluster / ReportBundle 合并
- 任何远端 / 后端改动（仅本地 CLI + 流水线签名 + dataclass）
- v1（非 v2）流水线接口对齐

## 设计决策记录（brainstorm 已确认）

| 决策点 | 结论 |
|---|---|
| custom_keyword 上限 | 三个流水线（toutiao / sina-news / netease-news）统一 `[:5]`，cap 在流水线内部强制（防御性） |
| 配额 hook 触发点 | 1 次成功的 search 会话 = 1 个 tick；在 `run_*_news_pipeline` 返回前 `if any search done: on_search_committed()`。**不**逐 keyword 计 |
| `hot_board_source` 来源 | 复用 `_news_cache_get` 已返回的 `src`（来自 `news_cache._single_flight`，实际 label 集 = `cache` / `cache_after_wait` / `fresh` / `deadline_exceeded` / `lock_timeout`），不引入新字符串 |
| CLI 默认配额 | `max-quota-per-day = 3`（与 Toutiao 默认一致），`state-root = Path("state")` |
| user_id 字段 | sina-news / netease-news 用 `profile.profile_id`（与头条用 `.user_id` 不同源，但各自 loader 决定，不在本次统一） |
| skip_quota 行为 | 与头条同款：跳过 `check_quota` 预检，`on_search_committed=None`，不写入 quota 状态 |

## 设计细节

### 1. Pipeline 签名变更

#### `run_toutiao_pipeline_v2`（`src/heated_topics_v3/pipeline.py` L929）

新增 `keyword_cap: int = 5` 参数。在 line 970-986 的 `custom_keywords` 分支里，把 `extraction.keywords` 改为：

```python
if custom_keywords:
    capped = tuple(k.strip() for k in custom_keywords if k.strip())[:keyword_cap]
    extraction = PersonaKeywordExtraction(
        user_id=profile.user_id,
        persona_signature=profile.persona_signature,
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in capped),
        source="custom",
    )
else:
    capped = tuple(profile.core_keywords)[:keyword_cap]
    extraction = PersonaKeywordExtraction(
        user_id=profile.user_id,
        persona_signature=profile.persona_signature,
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(kw, "热榜") for kw in capped),
        source="core_keywords",
    )
```

`keyword_phrases = tuple(k.keyword for k in extraction.keywords)`（line 1015）保持原状，下游搜索循环自动消费 cap 后的列表。

#### `run_sina_news_pipeline`（L1413） / `run_netease_news_pipeline`（L1650）

新增两个参数：

```python
custom_keywords: tuple[str, ...] = (),
on_search_committed: Callable[[], None] | None = None,
```

keywords 构造（sina line 1488-1497、netease line 1713-1721）替换为：

```python
if custom_keywords:
    keywords = tuple(k.strip() for k in custom_keywords if k.strip())[:5]
    extraction = PersonaKeywordExtraction(
        user_id=profile.profile_id,
        persona_signature="",
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
        source="custom",
    )
else:
    keywords = [w for w in profile.core_keywords[:5] if w.strip()]
    extraction = PersonaKeywordExtraction(
        user_id=profile.profile_id,
        persona_signature="",
        generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        keywords=tuple(ExtractedKeyword(k, "热榜") for k in keywords),
        source="core_keywords",
    )
persona_keywords = tuple(keywords)
```

配额 hook 触发点：函数返回前（与头条 line 1150-1151 同款位置）：

```python
if on_search_committed is not None and keywords:
    on_search_committed()
```

「search 至少跑过一次」用 `keywords` 非空判定 —— 这是「本 run 是否触发配额」的最小可靠信号（cap 后非空即说明走到了 search 阶段）。

### 2. Dataclass 字段新增

#### `SinaNewsV2Result`（L1289） / `NeteaseNewsV2Result`（L1622）

加一个字段，位置插在 `paths` 之后：

```python
@dataclass(frozen=True)
class SinaNewsV2Result:
    user_id: str
    date: str
    run_dir: Path
    top_n: int
    candidates_total: int
    kept_total: int
    paths: dict[str, int]
    hot_board_source: str          # ← 新增
    keyword_source: str
    keyword_count: int
    report_path: Path
    focused_path: Path
```

构造函数传 `hot_board_source=src`（来自 `_news_cache_get` 的第二返回值；line 1467 / 1696 已记录在 `stats`，本次只在构造 result 时多取一份）。

### 3. CLI 表面变更

#### sina-news / netease-news `_add_news_args`（L285）

增加 4 个 flag：

```python
parser.add_argument("--custom-keyword", dest="custom_keyword", action="append", default=[])
parser.add_argument("--state-root", default=Path("state"), type=Path)
parser.add_argument("--max-quota-per-day", dest="max_quota_per_day", default=3, type=int)
parser.add_argument("--skip-quota", dest="skip_quota", action="store_true")
```

#### `_handle_sina_news`（L362） / `_handle_netease_news`（L392）

在 `fetcher` 构造之前插入配额预检（同 Toutiao L94-105）：

```python
custom_keywords = tuple(k.strip() for k in args.custom_keyword if k.strip())
today = utc8_today()
on_search_committed = None
if not args.skip_quota:
    user_id = load_user_profile(args.profile).profile_id
    state = load_quota(args.state_root, user_id, today)
    try:
        check_quota(state, args.max_quota_per_day)
    except QuotaExceededError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    on_search_committed = lambda: commit_quota(args.state_root, user_id, today)
```

把 `custom_keywords` / `on_search_committed` 透传给 `run_*_news_pipeline`。

print 块加一行（位置同 Toutiao L132）：

```python
print(f"hot_board_source: {result.hot_board_source}")
```

#### Toutiao `_handle_*`（L91）

不动 —— 已经全部支持。

### 4. 端到端数据流（custom_keyword 场景）

```
CLI  --custom-keyword=AI --custom-keyword=芯片 ...
  ↓ tuple(...)
CLI handler
  ↓ on_search_committed = lambda (or None)
run_sina_news_pipeline(custom_keywords=(...), on_search_committed=...)
  ↓ keywords = (...,)[:5]  # cap
PersonaKeywordExtraction(source="custom", keywords=tuple(ExtractedKeyword))
  ↓
per-keyword search loop (capped ≤ 5)
  ↓
build_news_candidates → write_news_run → focused.json
  ↓
return SinaNewsV2Result(hot_board_source=src, keyword_source="custom", ...)
  ↓ if on_search_committed and keywords: on_search_committed()
CLI print
  hot_board_source: cache
  keyword_source: custom
  keyword_count: 5
```

## 测试计划

新增到 `tests/providers/test_sina_news.py` 和 `tests/providers/test_netease_news.py`：

1. **`test_custom_keywords_path`** —— 传 8 个 custom keyword，断言 `extraction.source == "custom"`、`extraction.keywords 长度 == 5`、`keyword_count == 5`、`search loop 最多 5 次`
2. **`test_custom_keywords_trump_core`** —— 同时设 `profile.core_keywords = ["A","B","C","D","E","F"]` 且传 `--custom-keyword X --custom-keyword Y`，断言结果里搜的是 X、Y（不是 core_keywords）
3. **`test_hot_board_source_in_result`** —— 跑一次，断言 `result.hot_board_source` 是非空字符串，且值在 `{cache, cache_after_wait, fresh, deadline_exceeded, lock_timeout}` 集合里
4. **`test_quota_committed_after_search`** —— 设 `state_root` 到临时目录，跑一次，断言 `state/quota/{user_id}.json` 存在且 `count == 1`；再跑一次，断言 `count == 2`；第三次跑 `--skip-quota`，断言文件不变
5. **`test_quota_exceeded_blocks_run`** —— 预先写好 quota 文件 `count=3`，跑一次，断言 `SystemExit(2)` 抛出且不产生新 run 目录

新增到 `tests/test_toutiao_pipeline.py`（如不存在则用 `tests/test_toutiao.py`）：

6. **`test_toutiao_custom_keywords_cap_at_5`** —— 传 8 个 custom，断言 `extraction.keywords 长度 == 5`

（视需要可加 `test_toutiao_quota_committed_after_search` 镜像，但头条已有等价测试则跳过；如缺则补。）

## 风险与回滚

- 风险点 1：sina/netease 的 `profile.profile_id` 在某些 profile 上可能为空字符串（v1 profile 没有这个字段）。CLI 预检若取不到 user_id 会 KeyError。**对策**：CLI 端加 `if not user_id: raise SystemExit("profile 缺少 profile_id，无法应用配额；请用 --skip-quota")`。
- 风险点 2：`SinaNewsV2Result` / `NeteaseNewsV2Result` 是 `@dataclass(frozen=True)`，所有现有构造点（pipeline.py 内部 + 可能的测试）必须同步加 `hot_board_source=...`。**对策**：grep 全仓库 `SinaNewsV2Result(` / `NeteaseNewsV2Result(` 确认所有构造点，统一修改。
- 风险点 3：头条 `keyword_cap` 默认 5 是新行为，理论上若有人通过 `run_toutiao_pipeline_v2(custom_keywords=(8 个))` 调用，超过 5 个的 keyword 会静默丢弃（之前不丢）。**对策**：记入 changelog；这是设计意图而非 bug。
- 回滚：所有改动独立可逆（参数默认值保 backward-compat：`custom_keywords=()` 时行为与现在一致；`on_search_committed=None` 时配额被跳过；`hot_board_source` 是纯加字段）。单个 commit revert 即可回滚全部。