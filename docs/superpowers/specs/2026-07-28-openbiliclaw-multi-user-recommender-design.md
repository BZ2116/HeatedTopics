# OpenBiliClaw 多用户热点推荐设计

## 目标

构建一个本地运行的**多用户个性化热点文章推荐器**：

- **输入**：多份用户个人信息（JSON 表格形式），每份含兴趣方向、关注话题、阅读风格、关注作者、平台偏好等
- **输出**：每个用户一份 top-N 热点文章推荐（每条带热度、正文预览、推荐理由、置信度、主题标签）
- **核心要求**：
  1. 候选必须带**热度信息**（view / like / comment / 平台排名）
  2. 候选必须带**正文**（前 800 字预览 + 全文长度）
  3. **多用户**画像输入并行或串行处理
  4. **不依赖**浏览器扩展登录

调用 OpenBiliClaw 已实现的推荐引擎（curator / MMR / 表达生成 / Embedding / 反馈）作为个性化层，V3 providers 作为内容来源。

## 范围与非目标

### 范围内

- 接入 OpenBiliClaw 的推荐引擎（`RecommendationEngine`）作为离线调用
- 接入 V3 providers（juejin / baidu_hot / zhihu_hot / zhihu_daily / toutiao）抓取热点文章
- 在 OpenBiliClaw 上加 1 处补丁（`serve_external_candidates`），让其接受外部候选
- 新增集成层包 `heated_topics_v3.openbiliclaw_integration`（CLI + 推荐编排 + JSON IO）
- 写测试覆盖集成层 + 端到端 + 真实 MiniMax / Ollama 验收

### 不在范围内

- 浏览器扩展开发或修改
- OpenBiliClaw GitHub fork 与远端 PR
- 小红书 / 抖音 / X / Reddit 内容源（OpenBiliClaw 这些源要求登录或浏览器；V3 也没现成 provider）
- YouTube（OpenBiliClaw 可 headless 抓，但 V3 没 provider；本期统一只用 V3 已有 provider）
- 多用户 SaaS 化（本期是单进程多用户，不考虑多进程隔离、权限、用户管理）
- 长期线上 CTR 评估
- 反馈闭环（OpenBiliClaw 有反馈机制，但本期不接入；只跑一次性推荐）

## 集成路线（决策记录）

经过源码摸底（`E:\.code\My\openbiliclaw-sandbox` v0.3.185），确定以下事实影响集成形态：

| 事实 | 影响 |
|---|---|
| `RecommendationEngine.generate_recommendations()` 的 `discovered` 参数被显式忽略 | 需要新增 `serve_external_candidates()` 方法 |
| V3 providers 已有 juejin / baidu_hot / zhihu_hot / zhihu_daily / toutiao | 内容来源直接用 V3 |
| 小红书等需登录的平台 OpenBiliClaw 也做不了 | 排除 xiaohongshu / douyin / x / reddit / youtube |
| LLM Provider 全部 OpenAI-兼容；MiniMax 走 `openai_compatible` + `https://api.minimaxi.com/v1` + `MiniMax-M2.7` 即可 | 零代码改动 |
| Embedding 走 Ollama `bge-m3` | 零代码改动 |
| `MemoryManager(data_dir)` / `Database(path)` / `RecommendationEngine(llm, database)` 都接受路径参数 | 多用户隔离靠 per-user data_dir 实现，**无需**对 `memory/manager.py` 打补丁 |
| `OnionProfile.from_dict()` 已支持从 JSON 加载完整 5 层洋葱 | 用户画像直接 JSON → OnionProfile，**无需**补丁 |

## 架构总览

```text
┌──────────────────────────────────────┐
│  users.json  (多用户画像输入)         │
│  - user_id, interests, recent_focus, │
│    disliked_topics, style, context,  │
│    core_traits, deep_needs, values,  │
│    recent_awareness, active_insights│
└────────────┬─────────────────────────┘
             │ for each user
             ▼
┌──────────────────────────────────────┐
│  OpenBiliClaw 推荐引擎（patch 后）    │
│  - 新方法: serve_external_candidates│
│  - 复用: curator / MMR / reason     │
│  - 复用: Ollama bge-m3 (embedding)  │
│  - 复用: MiniMax-M2.7 (LLM)         │
│  - 复用: OnionProfile 5 层洋葱      │
└────────────▲─────────────────────────┘
             │ Recommendation[]
             │
┌────────────┴─────────────────────────┐
│  本分支新增：集成层 (新包)            │
│  - user_profile      OnionProfile   │
│  - candidate_adapter V3→Discovered  │
│  - recommender       编排           │
│  - output            JSON 序列化    │
│  - cli               入口           │
└────────────▲─────────────────────────┘
             │ Article[]
┌────────────┴─────────────────────────┐
│  V3 providers (HeatedTopics V3)      │
│  - juejin  (article: title+body+hot) │
│  - baidu_hot                          │
│  - zhihu_hot / zhihu_daily            │
│  - toutiao                            │
└──────────────────────────────────────┘
```

## 模块与文件布局

### 新分支信息

- 名称：`feature/openbiliclaw-multi-user-recommender`
- Worktree：`E:\.code\My\heatedTopics\heatedTopics\.worktrees\openbiliclaw-multi-user-recommender\`
- 基础：`feature/baidu-zhihu-daily-mvp`（commit `3cb4896`）

### OpenBiliClaw 端（外部仓库）

- 位置：`E:\.code\My\openbiliclaw-sandbox\`（本地 clone，独立 git 仓库）
- 改动：1 个新方法，~80–120 行
- 版本号：`pyproject.toml` 从 `0.3.185` 改为 `0.3.186-mur.1`

### 本分支新增文件

```
src/heated_topics_v3/openbiliclaw_integration/
├── __init__.py
├── user_profile.py          # users.json → OnionProfile
├── candidate_adapter.py     # V3 Article → DiscoveredContent
├── recommender.py           # per-user 编排（调用 OpenBiliClaw 引擎）
├── output.py                # Recommendation → JSON 序列化
└── cli.py                   # 入口

tests/openbiliclaw_integration/
├── __init__.py
├── conftest.py
├── test_user_profile.py
├── test_candidate_adapter.py
├── test_output.py
├── test_cli.py
├── test_concurrency.py
├── test_serve_external_patch.py
├── test_end_to_end_one_user.py
├── test_end_to_end_multi_user.py
├── test_acceptance_juejin.py
├── test_acceptance_multi_user.py
└── test_acceptance_degraded.py

tests/openbiliclaw_integration/fixtures/
├── users_valid_3users.json
├── users_invalid_missing_user_id.json
├── users_invalid_empty_interests.json
├── articles_juejin_5.json
├── articles_zhihu_3.json
├── expected_output_1user.json
├── mock_soul_5layer.json
└── mock_llm_responses.json

config/
└── openbiliclaw.toml.example

docs/
└── README-openbiliclaw-integration.md
```

### V3 端只读依赖

- `src/heated_topics_v3/providers/juejin.py` — 主源
- `src/heated_topics_v3/providers/baidu_hot.py` — 主源
- `src/heated_topics_v3/providers/zhihu_hot.py` — 主源
- `src/heated_topics_v3/providers/zhihu_daily.py` — 主源
- `src/heated_topics_v3/providers/toutiao.py` — 主源
- `src/heated_topics_v3/contracts.py` — Article / Heat schema
- 不修改任何 V3 provider 文件

## OpenBiliClaw 补丁细节

### 唯一补丁：`serve_external_candidates()`

**位置**：`src/openbiliclaw/recommendation/engine.py`，紧跟 `serve_with_result()` 之后。

**目的**：新增入口直接接受 `list[DiscoveredContent]`，绕过 SQLite `content_cache` 池读。

**形状**（非完整代码）：

```python
async def serve_external_candidates(
    self,
    profile: SoulProfile,
    candidates: list[DiscoveredContent],
    *,
    limit: int = 5,
    excluded_bvids: frozenset[str] = frozenset(),
    expression_mode: Literal["realtime", "precomputed"] = "realtime",
) -> list[Recommendation]:
    """Serve recommendations from an externally provided candidate list.

    Bypasses the SQLite pool read. Used by the heatedTopics integration
    layer, where V3 providers fetch candidates and we hand them directly
    to the engine. Filtering / curator / MMR / expression flow mirrors
    serve_with_result's post-snapshot path.
    """
    if not candidates:
        return []
    async with self._serve_lock:
        if excluded_bvids:
            candidates = [c for c in candidates if c.bvid not in excluded_bvids]
        candidates = self._exclude_disliked_topic_candidates(candidates, profile)
        # curator 评分（若注入了 curator）
        # _select_diversified_batch_async 做 MMR
        # _generate_expression_for 生成理由
        # 返回 list[Recommendation]
        ...
```

**不破坏上游的理由**：

- 仅新增方法，原 `serve` / `serve_with_result` / `generate_recommendations` 签名和行为零变更
- 共用内部 helper（`_select_diversified_batch_async` / `_exclude_disliked_topic_candidates` / `_generate_expression_for`）
- 上游升级兼容：新方法作为额外 method 加在类里

**提交**：

- 分支：`openbiliclaw-sandbox` 的 `main`（本地仓库）
- commit message：`feat(recommendation): add serve_external_candidates for external pool bypass (heatedTopics integration)`

### 不需要补丁的部分

- `memory/manager.py`：现有 `MemoryManager(data_dir)` 已接受自定义 data_dir；per-user 隔离靠 `data/users/{user_id}/` 子目录实现
- `llm/registry.py`：MiniMax 通过 `provider_type="openai_compatible"` + base_url 走 OpenAI 协议，零代码改动
- `discovery/engine.py` / `sources/`：本期不调用 discovery 引擎，候选从 V3 外部注入
- `storage/database.py`：`Database(path)` 接受路径，每个用户独立 db 文件

## 数据流

```text
users.json
   │
   ▼
recommender.run()
   │
   ├── load users.json → list[UserSpec]
   │
   └── for each user:                  # asyncio.Semaphore(max_parallel)
         ├── user_profile.build_onion(spec)
         │     └── 写 data/users/{user_id}/memory/soul.json
         ├── providers.fetch_all(enabled_providers)
         │     └── returns list[Article]
         ├── candidate_adapter.to_discovered(articles)
         │     └── returns list[DiscoveredContent]
         ├── engine.serve_external_candidates(
         │       profile, candidates, limit=N)
         │     └── returns list[Recommendation]
         └── output.format(recommendations)
   │
   ▼
recommendations.json
```

### users.json 输入 schema

```json
{
  "users": [
    {
      "user_id": "u1",
      "display_name": "赵sir-网安",

      "interests": [
        {"name": "Rust 异步运行时", "category": "Rust", "weight": 0.9}
      ],
      "disliked_topics": ["娱乐八卦"],

      "style":   {"reading_depth": "deep", "tone_preference": "technical"},
      "context": {"primary_scene": "research", "device": "desktop"},
      "exploration_openness": 0.6,
      "favorite_up_users": [],
      "source_platform_mix": {"juejin": 0.5, "zhihu": 0.3, "toutiao": 0.2},

      "core_traits": ["好奇心强"],
      "deep_needs":  ["理解底层原理"],
      "values":      ["严谨", "开放"],
      "life_stage":  "本科大四",
      "current_phase": "准备研究生方向",
      "cognitive_style": ["由表及里"],

      "recent_awareness": [
        {"date": "2026-07-20", "observation": "在看 RAG 注入攻防",
         "trend": "关注 LLM 安全", "emotion_guess": "兴奋"}
      ],
      "active_insights": [
        {"hypothesis": "用户偏好能拆到代码层的文章",
         "evidence": ["多次点赞带源码的文章"], "confidence": 0.7}
      ]
    }
  ]
}
```

**字段映射**（users.json → `OnionProfile`）：

| users.json | OnionProfile 字段 | 调用方式 |
|---|---|---|
| `interests` / `disliked_topics` / `style` / `context` / `exploration_openness` / `favorite_up_users` / `source_platform_mix` | `PreferenceLayer` | `populate_from_flat_preference()` |
| `core_traits` / `deep_needs` | `core`（`CoreLayer`） | 直接赋值 |
| `values` | `values_layer.values` | 直接赋值 |
| `life_stage` / `current_phase` | `role.life_stage` / `role.current_phase` | 直接赋值 |
| `cognitive_style` | `surface.cognitive_style` | 直接赋值 |
| `recent_awareness` | `recent_awareness: list[AwarenessNote]` | `OnionProfile.from_dict()` |
| `active_insights` | `active_insights: list[InsightHypothesis]` | `OnionProfile.from_dict()` |

**必填**：`user_id` + `interests`（至少 1 个）。其余不填用默认值。

### recommendations.json 输出 schema

```json
{
  "generated_at": "2026-07-28T12:34:56Z",
  "config_version": "0.3.186-mur.1",
  "llm_model": "MiniMax-M2.7",
  "embedding_model": "bge-m3",
  "users": [
    {
      "user_id": "u1",
      "display_name": "赵sir-网安",
      "input_profile_summary": {"interests_count": 1, "disliked_count": 1},
      "pipeline": {
        "candidates_fetched": 152,
        "candidates_after_filter": 87,
        "candidates_considered_by_engine": 87,
        "embedding_degraded": false
      },
      "recommendations": [
        {
          "rank": 1,
          "title": "用 Tokio 实现零信任网关：源码级拆解",
          "url": "https://juejin.cn/post/xxx",
          "source_platform": "juejin",
          "heat": {"view": 12345, "like": 234, "comment": 56, "rank": 3},
          "body_text_preview": "前 800 字……",
          "body_text_length": 2340,
          "topic_label": "Rust 异步运行时 / 网安网关",
          "reason": "你关注『Rust』和『零信任』……",
          "confidence": 0.78,
          "published_at": "2026-07-25T10:00:00Z"
        }
      ]
    }
  ]
}
```

`body_text_preview` 截断长度 = 800 字（`--body-preview-chars` 可调）。`body_text_length` 给出原文长度。`pipeline.embedding_degraded = true` 时表示 embedding 不可用，走了降级路径。

## CLI 接口

```text
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users users.json \            # 必填
  --output recs.json \            # 必填
  --limit 10 \                    # 每用户 top-N，默认 10
  --max-parallel 5 \              # 最多同时跑 N 个用户，默认 5；N=1 = 串行
  --providers juejin,baidu_hot,zhihu_hot,zhihu_daily,toutiao \  # 逗号分隔；不传 = 全部
  --body-preview-chars 800 \      # body_text_preview 截断长度，默认 800
  --config config/openbiliclaw.toml  # 不传用默认
```

并发语义：

- 10 用户 + `--max-parallel 1` → 串行 10 次
- 10 用户 + `--max-parallel 4` → 4 并发 + 4 + 2 队列
- 3 用户 + `--max-parallel 8` → 全并行（被信号量节流到实际 3）

实现：`asyncio.Semaphore(max_parallel)` + 独立 try/except per user。

## 错误处理

### A. 启动期错误（fail fast）

| 失败 | 退出码 |
|---|---|
| `users.json` 不存在 / JSON 解析错 / 顶层缺 `users` | 2 |
| `config/openbiliclaw.toml` 缺失或不可解析 | 2 |
| `OPENBILICLAW_LLM_API_KEY` 未设 | 2 |
| Ollama 不可达 / `bge-m3` 未拉 | 2 |
| OpenBiliClaw patch 缺失（`serve_external_candidates` 不存在） | 3 |
| `openbiliclaw-sandbox` 路径不存在 | 3 |
| `recommendations.json` 父目录不可写 | 2 |

### B. Per-user 错误（一个失败不影响其他）

| 失败 | 动作 |
|---|---|
| `interests` 为空 / 缺 `user_id` | 跳过该 user，记入输出，退出码 +1 |
| V3 providers 全挂 | 该 user 标 `error: "no_candidates"`，跳过 |
| V3 providers 部分挂 | 用剩下的，记 warning |
| 单条 candidate 字段缺失 | drop，记 warning |
| LLM 超时（> 30s） | 1 次重试（2s 退避），再失败 → `error: "llm_timeout"` |
| LLM JSON 不可解析 | 1 次重试（不同 prompt），再失败 → `error: "llm_parse"` |
| Per-user 总耗时 > 60s | `asyncio.timeout` 强制取消，`error: "timeout"` |

### C. 输出 JSON 中"失败用户"的形状

```json
{
  "user_id": "u2",
  "error": "no_candidates",
  "error_detail": "All 5 providers failed: juejin 403, baidu 500, zhihu timeout, ..."
}
```

### D. 退出码总览

| 退出码 | 含义 |
|---|---|
| 0 | 所有用户成功 |
| 1 | 部分用户失败（成功用户的推荐已写出） |
| 2 | 启动期配置错误（无输出） |
| 3 | OpenBiliClaw 环境错误 |
| 4 | 写入推荐结果失败 |
| 130 | 用户中断（部分输出） |

### E. 降级路径

- Embedding 不可用：`pipeline.embedding_degraded: true`，MMR 退化为非 embedding 多样性（按 `source_platform` 打散 + 热度排序），跑出可用结果
- LLM 不可用：不可降级（生成理由必须靠 LLM），user.error = `llm_unavailable`
- 单 provider 不可用：warning + 其他 provider 补

## 测试与验收

### 单元测试

| 文件 | 覆盖 |
|---|---|
| `test_user_profile.py` | users.json schema、5 层洋葱字段映射、awareness/insight 透传、字段缺省、weight ∈ [0,1] |
| `test_candidate_adapter.py` | V3 Article → DiscoveredContent 字段对应、`content_type=note`、多平台 ID 命名空间 |
| `test_output.py` | 800 字截断（边界 799/800/801/1500）、可选字段缺省、JSON 可读回 |
| `test_cli.py` | 必填/可选参数、未知 provider 名拒绝、`--max-parallel` 边界、退出码 |
| `test_concurrency.py` | N=1/5/10 各种并发下的行为 |

### 集成测试（mock LLM/embedding）

| 文件 | 覆盖 |
|---|---|
| `test_serve_external_patch.py` | 导入 `serve_external_candidates` 不抛；5 条 mock 候选调用返回 `list[Recommendation]` |
| `test_end_to_end_one_user.py` | mock V3 provider → mock LLM → 输出 JSON 含 heat + body_text_preview + reason + topic_label |
| `test_end_to_end_multi_user.py` | 3 user interests 互不相交 → 3 份推荐无重叠 |

### 验收测试（需要真实 MiniMax + Ollama）

| 文件 | 标记 | 覆盖 |
|---|---|---|
| `test_acceptance_juejin.py` | `@pytest.mark.requires_llm` + `requires_ollama` | 真实 juejin top 20 → top 5，每条 view > 0 + body 非空 + reason 含兴趣关键词 |
| `test_acceptance_multi_user.py` | 同上 | 3 user (网安/Rust/设计)，每 user top 5 至少 2 条与 interests 词面匹配 |
| `test_acceptance_degraded.py` | 同上 + 启动前 stop Ollama | `embedding_degraded: true` 出现 + 推荐仍能产出 |

### Mocking 策略

| 依赖 | 方式 |
|---|---|
| V3 providers | `unittest.mock.patch` `heated_topics_v3.providers.<name>.fetch` |
| OpenBiliClaw LLM | `AsyncMock` 替换 `_llm`，按 prompt 关键词返回 fixture |
| OpenBiliClaw embedding | 同上 |
| OpenBiliClaw DB | 真实 `Database(tmp_path / "obc.db")`，per-test 独立 tmp_dir |
| Ollama / MiniMax | 验收测试用 pytest mark，CI 默认 skip |

### 验收门槛（合 main 前必须满足）

- 所有单元测试通过
- 所有 mock 集成测试通过
- 端到端跑 1 个真实用户 + juejin 真实数据 + 真实 MiniMax + 真实 Ollama，输出符合 schema
- `pytest --cov=heated_topics_v3.openbiliclaw_integration` 行覆盖率 ≥ 80%
- `ruff check` + `ruff format` 通过
- `python -m heated_topics_v3.openbiliclaw_integration.cli --help` 正常输出
- 失败注入测试：删 `OPENBILICLAW_LLM_API_KEY` 确认退出码 2

## 部署与运行

### 安装

```bash
# 0. 假设 openbiliclaw-sandbox 已 clone 并打补丁
cd E:\.code\My\openbiliclaw-sandbox
git log --oneline | head -3
# 期望看到: feat(recommendation): add serve_external_candidates ...

# 1. 启动 Ollama + bge-m3
ollama serve &
ollama pull bge-m3

# 2. 配 MiniMax Key
export OPENBILICLAW_LLM_API_KEY=...

# 3. 进新 worktree 安装依赖
cd E:\.code\My\heatedTopics\heatedTopics\.worktrees\openbiliclaw-multi-user-recommender
# 在 pyproject.toml 的 [project.dependencies] 末尾加：
#   openbiliclaw = { path = "../../openbiliclaw-sandbox" }
uv sync

# 4. 写 users.json
cp config/openbiliclaw.toml.example config/openbiliclaw.toml
# 编辑 config/openbiliclaw.toml 确认 LLM base_url / embedding base_url

# 5. 跑
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users users.json --output recs.json
```

### 已知风险

- OpenBiliClaw patch 跟随本地 clone，clone 丢失 → patch 丢失。建议定期 `git bundle` 备份。
- MiniMax 输出格式可能与 OpenBiliClaw 解析器不完全兼容（已有 plan 验证过兼容性；本分支假定验证通过）。
- V3 providers 与 OpenBiliClaw 的 schema 命名空间不同（`source_platform` 取值集合有差异），candidate_adapter 需保证映射无遗漏。

## 后续与未决项

- 多用户反馈闭环（`like` / `dislike` 写回 `data/users/{user_id}/feedback_state.json`）
- 长期效果评估（点击率、覆盖率）
- 添加更多源（如果 OpenBiliClaw 上游有 headless 友好的新平台）
- Web UI（基于 OpenBiliClaw 已有 web/ SPA 改造）
- 多进程隔离（不同用户的 OpenBiliClaw runtime 完全独立进程）

## 决策日志

| 决策 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 主源 | V3 providers / OpenBiliClaw 自带 | V3 providers | V3 满足"热度 + 正文"，OpenBiliClaw headless 源无正文 |
| OpenBiliClaw 形态 | 库引用 / 外部进程 / fork / 先扒源码 | 库引用（path 依赖）+ 本地补丁 | 不建 GitHub fork；补丁 commit 在本地 clone；改造面最小 |
| xiaohongshu | 接 / 不接 | 不接 | OpenBiliClaw 抓不了，V3 排除 |
| 分支基础 | V3+合并 / baidu-zhihu / V3+合并两支 | `baidu-zhihu-daily-mvp` | 已有全部 V3 providers + 收集管线，最完整 |
| OpenBiliClaw 补丁位置 | fork/vendor/subtree/不动 | 本地 clone 上 commit | 不建 GitHub fork；保持上游 sync 灵活 |
| 集成入口 | 修改 serve() / 新方法 | 新方法 `serve_external_candidates` | 不改原方法签名；上游升级兼容 |
| 多用户并发 | 默认顺序 / 默认并行 / 限上限 | 限上限，默认 5 | 默认不会高并发跑；MiniMax 限流 |
| body_text 预览 | 500 / 800 / 全文 | 800 | 用户选 800；正文完整版按 URL 自取 |
| Per-user 隔离 | 单实例 / 每用户独立 data_dir | 每用户独立 data_dir | 并发安全；OpenBiliClaw 已支持 |

## 引用

- OpenBiliClaw 仓库：`https://github.com/whiteguo233/OpenBiliClaw.git`
- OpenBiliClaw 本地 clone：`E:\.code\My\openbiliclaw-sandbox`（commit `de11ea42`）
- V3 providers 在 `feature/baidu-zhihu-daily-mvp`（`3cb4896`）
- 现有 OpenBiliClaw 评估 spec：`docs/superpowers/specs/2026-07-26-openbiliclaw-minimal-evaluation-design.md`
- 现有 OpenBiliClaw 评估 plan：`docs/superpowers/plans/2026-07-26-openbiliclaw-minimal-evaluation.md`
- OnionProfile 实现：`src/openbiliclaw/soul/profile.py:612-779`
- RecommendationEngine 实现：`src/openbiliclaw/recommendation/engine.py:296-2280`
- DiscoveredContent 实现：`src/openbiliclaw/discovery/engine.py:468-557`
