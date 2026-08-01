# Last30Days × HeatedTopics 集成说明（v2.1）

> 在多用户推荐 CLI 旁路引入 last30days 的 8 平台采集能力，扩大跨平台覆盖面。

## 1. 三种 `--source` 模式对比

| 模式 | 候选采集 | 适用场景 |
|---|---|---|
| `v3-hotlist`（默认） | 8 个 V3 provider：juejin/头条/百度热榜/知乎热榜/知乎日报/新浪/澎湃/网易 | 已有行为；技术/开发者向热榜 |
| `last30days` | 8 个中文平台（见 §2） | 中文社交/资讯为主 |
| `both`（**v2 默认**） | V3 + last30days，按 URL dedup（v3 赢冲突） | 跨平台最大覆盖，需要更长 LLM 推理时间 |

## 2. last30days 平台可用性矩阵

`last30days --fetch-bodies` 抓正文时各平台支持度：

| 平台 | 热榜 | 正文可抓 | 备注 |
|---|---|---|---|
| weibo 微博 | ✅ | ✅ | 完整体验 |
| xiaohongshu 小红书 | ✅ | ⚠️ 需登录 | 通常仅笔记标题 + 描述 |
| bilibili B 站 | ✅ | ✅ | 视频标题 + 描述 |
| zhihu 知乎 | ✅ | ✅ | 标题 + 摘录 |
| douyin 抖音 | ✅ | ⚠️ 需登录 | 通常仅文字 + 标签 |
| wechat 公众号 | ✅ | ⚠️ 部分 | 仅搜索结果 |
| baidu 百度 | ✅ | ⚠️ 摘要 | 仅 abstract |
| toutiao 头条 | ✅ | ⚠️ 摘要 | 仅 abstract |

**正文缺失是 last30days 的预期行为，不会报错**。adapter 会把 body 为空的 item 标记为 `content_status="title_only"`，OpenBiliClaw 引擎会据此降级可信度。

## 3. v2 CLI flag 速查

| flag | 默认 | 说明 |
|---|---|---|
| `--source {v3-hotlist,last30days,both}` | both | 候选源选择 |
| `--last30days-cli-path PATH` | — | last30days `scripts/last30days.py` 路径（source 含 last30days 时必填） |
| `--last30days-days N` | 30 | 回溯天数 |
| `--last30days-fetch-bodies` | on | 启用 `--fetch-bodies` |
| `--no-last30days-fetch-bodies` | — | 关闭 `--fetch-bodies` |
| `--last30days-timeout SEC` | 120 | per-user last30days 子进程超时 |

**v2 已移除**（v1 暴露但 v2 不再用）：

- `--last30days-query`：v2 起自动取用户 `track_1` 作 query（v2.1 起取 LLM 抽出的关键词的第一个），每用户不同
- `--last30days-no-fetch-bodies`：用 `--no-last30days-fetch-bodies` 替代
- `--users / --output`：改用 `--users-excel / --output-dir`
- `--body-preview-chars`：v2 写完整正文（≤`--body-max-chars`），不再截预览

## 4. 命令示例

### 仅走 last30days

```bash
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users-excel data/users.xlsx \
  --output-dir data/recs_l30/ \
  --source last30days \
  --last30days-cli-path /path/to/last30days-skill-cn/scripts/last30days.py \
  --last30days-days 30 \
  --max-parallel 5 \
  --per-user-timeout 300
```

### 合并 V3 + last30days（v2 默认）

```bash
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users-excel data/users.xlsx \
  --output-dir data/recs_both/ \
  --source both \
  --last30days-cli-path /path/to/last30days-skill-cn/scripts/last30days.py
```

### 每用户 query 自动来自 LLM 关键词（v2.1）或 track_1（v2）

v2.1 起不需要 `--last30days-query`：CLI 内部对每个用户调用 last30days 时，query 来源优先级：

1. **v2.1 默认**：LLM 抽出的 3 个关键词的**第一个**（`extract_or_load` 产出，缓存于 `_keyword_cache/<user_id>/`）
2. v2 / `--no-keyword-extraction`：回退 `track_1`，再回退 `track_2`
3. 都空则跳过该用户（不会 crash，会写 `error: "no_candidates"` 到对应文件）

修改用户的 `track_1 / track_2 / persona` → `spec_hash` 变化 → 下次跑自动重抽关键词 → last30days query 跟着变。

## 5. 已知限制

- **`--fetch-bodies` 对小红书 / 抖音基本无效**：未登录抓不到正文。adapter 会把所有正文缺失的 item 标为 `title_only`；OpenBiliClaw 引擎据此降级置信度。
- **subprocess timeout 是 per-user 不是全局**：`--max-parallel 5` 会并发 5 个 last30days 子进程；机器内存 / 网络吃紧时把 `max-parallel` 降到 1-2。
- **缓存/重跑**：每次跑都会重新 subprocess，不会复用上次输出。需要"读本地 last30days 报告再做推荐"的功能，等 v2 引入 MCP。
- **每用户都重新跑一次 last30days 子进程**：100 个用户 → 100 次抓取；如需共享请在 Excel 之外的批处理层做。

## 6. 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| `Last30DaysSourceError: exited 1` | last30days 子进程崩溃 | 加 `--last30days-timeout 300`，看 stdout/stderr 真实报错 |
| `Last30DaysParseError` | 报告 JSON 损坏 | 重跑，去掉 `--fetch-bodies` 看是否是网络问题 |
| recommendations 全 0 | 用户 track 和 last30days 抓到的平台关键词不匹配 | 调整 `track_1` 或加更宽的 `track_2` |
| 进程 hang | 多用户 last30days 并发拉得太狠 | `--max-parallel 1` + `--last30days-timeout 60` |
| `--source both 退出码 2` | 缺 `--last30days-cli-path` | 必填 flag |

## 7. 内部架构

```
[CLI] --source={v3-hotlist,last30days,both}
   ↓
[recommender._run_one_user_async]
   ├─ v2.1 第一步: keyword_extractor.extract_or_load(spec, llm, cache_dir)
   │               ├─ spec_hash = sha256(track_1|track_2|persona)
   │               ├─ cache hit → 直接返回缓存的 3 关键词
   │               └─ cache miss → LLM 抽词 → 写缓存
   ↓
[recommender._fetch_candidates_for_user()]
   ├─ v3-hotlist / both 分支: fetch_candidates() → V3 providers
   │   └─ queries = 关键词[0..2]（v2.1） 或 track_1/track_2（v2）
   ├─ last30days / both 分支: _fetch_last30days_candidates()
   │                          ├─ query = 关键词[0]（v2.1） 或 spec.track_1（v2 兜底）
   │                          ├─ last30days_source.run() [subprocess]
   │                          ├─ last30days_source.parse_report() [JSON]
   │                          └─ last30days_adapter.to_hot_items() [字段映射]
   └─ both 分支：URL dedup（v3 优先）
   ↓
[复用] candidate_adapter.to_discovered() → DiscoveredContent
   ↓
[复用] RecommendationEngine.serve_external_candidates(
           expression_mode="precomputed")   ← v2 跳过 LLM 写 reason
   ↓
[复用] output.format_user_file() → JSON 单用户文件
   ↓
[CLI] 写到 {output_dir}/{user_id}/{today}/recommendations.json
```

## 8. 测试覆盖

- `test_last30days_source.py` — subprocess 行为 / 错误路径
- `test_last30days_adapter.py` — 8 平台 × 3 类样本（含 missing body）
- `test_source_dispatch.py` — `_fetch_candidates_for_user` 分发 + URL dedup（7 测试）
- `test_end_to_end_last30days.py` — CLI → dispatcher → engine 全链路
- `test_keyword_extractor.py` — LLM 抽词 + JSON 解析 + 缓存读写（11 测试，v2.1 新增）
- `test_recommender.py::test_run_one_user_extracts_keywords_*` — 关键词流入 V3 search + last30days query（v2.1 新增）
- `test_end_to_end_one_user.py::test_end_to_end_*_keyword_cache` — CLI → cache 文件落盘（v2.1 新增）

跑：`uv run pytest tests/openbiliclaw_integration -q -m "not requires_llm and not requires_ollama"`
