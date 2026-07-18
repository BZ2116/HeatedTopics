# Toutiao 分支使用手册

## §0 新机器首次设置

在另一台机器上从零拉取并运行，**必须**按顺序做这三步（任一漏掉都会在第一次跑时挂掉）：

### 1. 装依赖

```bash
# 需先装 uv（见 https://docs.astral.sh/uv/）
git clone <repo-url> && cd <repo>
uv sync
```

`uv sync` 会自动 editable 安装 `heatedtopics` 包，装完后 `heated_topics_v3` 在任何位置都能 import，无需 `PYTHONPATH=src` 前缀。

### 2. 装 Chromium（反爬梯子阶段 2/3 必需）

```bash
uv run playwright install chromium
# DrissionPage 会按需自动下载它自己的 Chromium；首次若想预热：
uv run python -c "from DrissionPage import Chromium; Chromium().quit()"
```

阶段 1（urllib）走默认不需要 Chromium；只有阶段 1 连续失败时才会升到阶段 2/3，那时才需要上面这步。`fetcher_factory.py:50-55` 的 `DEMOTE_AFTER_FAILS=3` 是触发阈值。

### 3. Harvest 头条 cookie

```bash
uv run python scripts/harvest_cookies.py
```

会生成 `scripts/.toutiao_cookie`（`.gitignore` 已排除）。**没 cookie 的话阶段 1 必然失败**，会一路升到阶段 2/3，增加被风控的概率。

### 验证

跑这条命令应该看到 CLI help（说明包已正确安装）：

```bash
uv run python -m heated_topics_v3.cli toutiao --help
```

跑这条应该看到 `162 passed`（说明环境就绪）：

```bash
uv run pytest -q
```

---

## §1 项目是什么

HeatedTopics V3 的 toutiao 分支：为内容选题场景提供按用户画像驱动的头条热点采集、原文抓取和报告生成。

本分支只维护 Toutiao v2 流程；其他平台（Juejin / Weibo / Zhihu）继续在 main 分支。

非 LLM 跑得动（用 `core_keywords` + 启发式 persona 拆词），可选用 MiniMax LLM 做关键词提炼 / 摘要 / 重排。

## §2 数据流

```
profile (zhao_001.json)
       │
       ▼
关键词提炼 (从 profile.core_keywords 获取)
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

`min_hot_board_before_search` 是 skip-search 的总闸门：`src/heated_topics_v3/toutiao_paths.py:119` 判断热榜候选数；满足阈值直接返回 Path A，不再触发搜索抓取（`src/heated_topics_v3/toutiao_paths.py:120`）。

| `PathFilters` 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `hot_board_min` | `1_000_000` | Path A 入场最低热度 |
| `article_heat_min` | `500` | Path B 入场最低热度 |
| `is_toutiao_hot_min_article_heat` | `0` | `is_toutiao_hot` 标记生效的最低热度 |
| `is_toutiao_hot_max_article_heat` | `500` | `is_toutiao_hot` 标记生效的最高热度 |
| `include_is_toutiao_hot_fallback` | `True` | 是否启用 Path C 兜底 |
| `search_pages` | `1` | 每个 keyword 搜索的翻页数 |
| `per_page` | `10` | 每页结果数 |
| `min_hot_board_before_search` | `5` | skip-search 阈值；达到此数 Path A 独占（`src/heated_topics_v3/toutiao_paths.py:59`） |

**兜底机制**：当 Path A/B/C 过滤后候选数不足 `top_n` 时，自动用所有搜索结果按 `article_heat` 降序补足，确保最终输出至少有一篇。

## §4 CLI

使用流程分两步：**初始化时用 LLM 生成关键词**，之后运行时不再调用 LLM。

### 环境变量（初始化前配置）

```bash
export MINIMAX_API_KEY=你的API密钥
export MINIMAX_BASE_URL=https://api.minimax.io/anthropic
export MINIMAX_MODEL=MiniMax-M2.7
```

### 步骤 1：初始化（一次性）

```bash
# 验证 LLM 连接
uv run python -m heated_topics_v3.cli check-llm

# 生成关键词并回写到 profile
uv run python -m heated_topics_v3.cli refresh-keywords \
    --profile config/profiles/qiongyou_001.json --write
```

`--write` 把生成的关键词回写到 profile JSON 的 `core_keywords` 字段。

### 步骤 2：日常运行（不再调用 LLM）

```bash
uv run python -m heated_topics_v3.cli toutiao \
    --profile-v2 config/profiles/qiongyou_001.json --top-n 10
```

### 完整参数一览

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `--profile-v2 PATH` | 指向 v2 profile JSON（必填） | - |
| `--top-n INT` | 最终保留的候选条数 | `10` |
| `--output-root PATH` | 输出根目录 | `outputs` |
| `--cache-root PATH` | 缓存根目录 | `cache` |
| `--force-hot-board-refresh` | 忽略热榜缓存重新抓取 | False |
| `--offline` | 热榜只读缓存；搜索、热度补充和正文仍可能请求网络 | False |
| `--custom-keyword WORD` | 自定义关键词（可重复，替换 profile 里的） | [] |
| `--state-root PATH` | 配额状态目录 | `state` |
| `--max-quota-per-day INT` | 每日搜索配额上限 | `3` |
| `--skip-quota` | 跳过每日配额检查（集成方使用） | False |

完整参数见 `uv run python -m heated_topics_v3.cli toutiao --help`。

候选文章按 heat 降序排列：Path A 使用头条热榜 `HotValue`，Path B/C 使用 `article_heat`。同 heat 时，`is_toutiao_hot=true` 优先；仍相同时按热榜原始排名升序。

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

> 修改画像后应重新运行 `refresh-keywords --write`，让 `core_keywords` 与新画像保持一致。

## §6 persona_signature

`compute_persona_signature(level1, level2, personal)`（`src/heated_topics_v3/profile_loader.py`）对画像核心字段生成稳定摘要，用于识别画像版本。热点运行阶段直接读取 profile 中已经持久化的 `core_keywords`，不会因为签名变化自动调用 LLM；画像修改后需要显式执行 `refresh-keywords --write`。

## §7 正文获取优先级

正文链路由 **Path 级预填充** + **单条 detail 兜底** 两层组成。优先级核心结论：**mobile API 的 `article_info.content_html` 永远优先于桌面页解析**。

**Path 级预填充**（在 `fetch_toutiao_item_details` 之前给所有候选填好正文，避免下游空 body）：

| 阶段 | 来源 | 说明 |
| --- | --- | --- |
| Path B/C 搜索循环 | mobile `article_info.content_html` | 搜索结果回流时调用 `attach_article_heat_fields`，把 `content_html` 写入 `raw_payload`（`src/heated_topics_v3/pipeline.py:380`） |
| Path A 顶 N enrichment | 同上, 补拉 | Path A 候选未进搜索循环，ranking 后用 `_enrich_top_path_a_candidates` 补拉一次 `article_info`（`src/heated_topics_v3/pipeline.py:421` 调用，`src/heated_topics_v3/pipeline.py:487` 定义） |

**单条 detail 兜底**（`fetch_toutiao_item_details` 内, `src/heated_topics_v3/providers/toutiao.py`）：

| 优先级 | 来源 | 触发场景 | 失败兜底 |
| --- | --- | --- | --- |
| 1 | mobile `article_info.content_html` | `raw_payload.content_html` 已存在且非空（搜索或 Path A enrichment 已写入） | 跳到优先级 2 |
| 2 | 桌面页 `<article>` 解析（`parse_toutiao_article_page`） | article_info 缺失或 desktop HTML 未被 JS 渲染时 | 跳到优先级 3 |
| 3 | metadata（`item.summary` / `item.title`） | 上述全部失败时仅落标题（`_partial_detail`, `src/heated_topics_v3/providers/toutiao.py:378`） | 输出文件只剩标题 |

`article_info` 对部分聚合型（aggregator）热搜主题会返回空 `content`，桌面页又 JS 渲染时落盘文件只包含标题，正文留空。

## §8 缓存目录

```
cache/
├── hot_board/{YYYY-MM-DD}.json      # 今日优先; 缺则 yesterday 兜底
├── core_keywords/{user_id}.json     # refresh-keywords 的生成记录
├── toutiao_search/{date}/{key}.json # UTC+8 当日共享的有效搜索结果
├── toutiao_search/{date}/{key}.lock # 同 key 跨线程/进程 single-flight
└── llm/{prompt_hash}.json           # sha256(model+system+prompt)[:24]
```

缓存与兜底规则：

- 热榜今日缺则回退昨日快照（`src/heated_topics_v3/hot_board_cache.py:126-130`）。
- `refresh-keywords` 会写生成记录到 `cache/core_keywords/{user_id}.json`；热点运行以 profile 的 `core_keywords` 为准，不读取该缓存决定搜索词。
- 头条搜索缓存按 UTC+8 自然日、规范化 keyword、`search_pages`、`per_page` 和 schema version 隔离；同一天不同用户可共享相同搜索结果。
- 只有解析出真实文章的非空搜索结果才写缓存；异常、空结果、关键词占位项和反爬假响应不会复用。`article_info` 与文章详情不进入该缓存，仍按每次运行实时请求。
- 同一缓存 key 并发 miss 时使用文件锁合并请求；等待最多 2 秒，超时后跳过该关键词，不重复调用 Search API。锁文件会保留，由操作系统在进程退出时释放锁状态。
- 关键词搜索阶段默认共享 20 秒总预算；预算耗尽后停止后续关键词并保留已完成结果。该预算不包含热榜、`article_info`、正文、报告和落盘，因此不等于整个 pipeline 的 20 秒 SLA。

`--force-hot-board-refresh` 跳过热榜缓存，`--offline` 仅在热榜环节生效 — 把 `fetcher=None` 传给 `get_or_fetch_hot_board`，等于禁用当日热榜抓取、回退到 `cache/hot_board/{date}.json` 命中或 yesterday 兜底；搜索阶段优先读取当日共享缓存，未命中时与 `article_info`、桌面页解析一样仍会发请求。

## §9 反爬梯子

抓取侧采用三阶段 fetcher 梯子（`src/heated_topics_v3/fetcher_factory.py:1`），按运行期失败率自动升降级。

CLI 在线搜索以 `paced=False` 创建 fetcher，不执行原有的 4–8 秒请求间隔和 60 秒批次暂停，三级 fallback 共用单次调用的剩余 timeout。缓存与 single-flight 负责抑制并发放大；诊断脚本默认仍保留 pacing。

| 阶段 | 实现 | 触发 |
| --- | --- | --- |
| 1 | `urllib + cookies`（`src/heated_topics_v3/fetcher_factory.py:232` 的 `_fetch_urllib`） | 默认 |
| 2 | Playwright live Chromium | 阶段 1 连续失败 ≥ `DEMOTE_AFTER_FAILS=3`（`src/heated_topics_v3/fetcher_factory.py:57`） |
| 3 | DrissionPage live Chromium | 阶段 2 也连续失败 ≥ 3 次 |

阶段升级 / 降级 / 整段禁用规则与诊断细节见 [`docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md`](docs/superpowers/specs/2026-07-14-toutiao-search-anti-bot-design.md)。该 spec 覆盖了热榜、搜索回包、桌面 `/article` 解析三阶段的失败模式诊断（不仅是搜索），是反爬梯子的完整因果说明书。

## §10 辅助脚本

| 脚本 | 一句话 |
| --- | --- |
| `scripts/build_personas_from_xlsx.py` | 把人设 xlsx 批量转成 `config/profiles/{user_id}.json`（`--regenerate`）。 |
| `scripts/harvest_cookies.py` | Playwright + DrissionPage 取 `toutiao.com` 首页 cookie 并 merge 到 `scripts/.toutiao_cookie`。 |
| `scripts/run_pipeline.py` | 单用户烟测（yingjie_001），打印 `kept_total` / `paths` / `fetcher.stage` 关键指标；输出 / 缓存 / cookie 都在 `scripts/` 下。 |

`tmp_3users_test/` 是 gitignored 的临时目录（cookie、fetcher 日志、原始 API dump、烟测 profile 副本），不属于分支。新 clone 不会带它，但运行期需要时可以临时建。

## §11 输出结构

```
outputs/users/{user_id}/{YYYY-MM-DD}/run_{YYYYMMDD_HHMMSS}/
├── report.md
├── focused.json
├── raw/
│   ├── hot_board.json          # 软链 → cache/hot_board/{date}.json
│   ├── search_{slug}.json      # 每个 keyword 一份
│   └── article_info.json       # {canonical_url: {impression_count, ...}}
└── articles/
    ├── 01_{slug}.txt
    ├── ...
```

## §12 测试

```bash
uv run pytest -q
```

测试覆盖 toutiao v2 端到端、四路径、每日搜索缓存、single-flight、20 秒搜索预算、jump URL 解包和 anti-bot 降级。

## 每日配额与自定义关键词（上线用法）

### 每日配额

每个用户每天最多获取热榜 `--max-quota-per-day` 次（默认 3）。第 N+1 次调用时，
后端在进入流程前拦截，向 stderr 打印 `今日额度已用完` 并以 exit code `2` 退出，
不产出任何结果目录。

- 配额状态存于 `state/quota/{user_id}.json`，格式 `{"date": "YYYY-MM-DD", "count": N}`。
- 跨天自动重置：读取时若 `date` 不是当天，`count` 视为 0。
- **计数语义**：只有「发起了搜索分支且流程完整走完」才 +1。若热榜命中已足够、
  直接走 Path A 直出（`skip_search`），不发起搜索，则不消耗配额。

### `--skip-quota`（前端集成必读）

本项目会被另一个项目集成。若由前端自行管理调用次数，请在每次调用时传
`--skip-quota`，后端将完全跳过配额检查与计数（不读写 `state/quota/`）。
不传该 flag 时，后端用自己的默认配额状态兜底，CLI 手动跑也会受同一份状态限制。

### 自定义关键词

传入 `--custom-keyword`（可重复）即用这些关键词**替换本次运行**的自动抽取关键词，
按输入顺序检索匹配；空白值会被过滤。`config/profiles/{user}.json` 里的
`core_keywords` 不受影响（仍是持久 persona，只是本次不参与）。本次运行的
`keyword_source` 会标记为 `custom`。

示例：

    python -m heated_topics_v3.cli toutiao --profile-v2 config/profiles/licai_001.json \
        --custom-keyword 比特币 --custom-keyword 美联储 --top-n 10

### 关键词生成机制（初始化时调用 LLM）

关键词在**初始化阶段**通过 LLM 生成，并回写到 profile JSON 的 `core_keywords` 字段。之后运行热点生成时直接使用，不再调用 LLM。

**生成规则：**
- 数量：去重后 3-10 个
- 词形：2-3 个汉字的简短名词或实体词，不可合理缩写的专有实体可保留原名
- 来源：必须从 level1、level2 提取核心词（如"旅行攻略"→"旅行"+"攻略"），再从其他字段补充

**关键词来源优先级：**
1. 从 level1、level2 拆解 2-3 字核心词（最高优先级）
2. 从 role、subject、scenarios、core_keywords_seed 中提取相关词
3. 允许生成直接相关的上位词、下位词、品牌、产品词

**生成并写入 profile：**

```bash
uv run python -m heated_topics_v3.cli refresh-keywords \
    --profile config/profiles/qiongyou_001.json --write
```

**检测 LLM 配置是否正确：**

```bash
uv run python -m heated_topics_v3.cli check-llm
```

## 用户注册接口（集成方 import 用）

集成方要新增一个用户时，调用 `register_persona`——一次调用走完「原始人设文本 →
LLM 结构化 → 派生 core_keywords → 分配 user_id → 落库 JSON」。

```python
from heated_topics_v3.persona_intake import register_persona

result = register_persona(
    level1="财经",
    level2="普通人理财",
    persona_text="普通人理财博主，分享基金、存款、记账，帮小白避坑",
    # 以下均可选，默认写 config/profiles/
    # profiles_dir=...,
)
result.user_id       # "licai_001"（同 level2 再注册得 licai_002，始终新建）
result.profile_path  # config/profiles/licai_001.json
result.profile       # 已过 v2 validator 的 PersonaProfile
```

要点：

- **user_id** 按 `level2 → slug` 映射（`src/heated_topics_v3/persona_slugs.py` 的
  `LEVEL2_SLUG`）+ 递增序号分配；同 level2 的新用户始终拿下一个空位，不覆盖旧文件。
- **结构化**用 LLM（`structure_persona`）。
- 写完 JSON 立刻 `load_persona_profile` 读回校验，schema 不合法当场抛错。
