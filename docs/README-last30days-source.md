# Last30Days × HeatedTopics 集成说明

> 在多用户推荐 CLI 旁路引入 last30days 的 8 平台采集能力，扩大跨平台覆盖面。

## 1. 三种 `--source` 模式对比

| 模式 | 候选采集 | 推荐栈 | 适用场景 |
|---|---|---|---|
| `v3-hotlist`（默认） | 8 个 V3 provider：juejin/头条/百度热榜/知乎热榜/知乎日报/新浪/澎湃/网易 | OpenBiliClaw | 已有行为；技术/开发者向热榜 |
| `last30days` | 8 个中文平台（见 §2） | OpenBiliClaw | 中文社交/资讯为主 |
| `both` | V3 + last30days，按 URL dedup（v3 赢冲突） | OpenBiliClaw | 跨平台最大覆盖，需要更长 LLM 推理时间 |

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

## 3. 命令示例

### 仅走 last30days

```bash
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users data/users.json \
  --output data/recs_l30.json \
  --source last30days \
  --last30days-cli-path /path/to/last30days-skill-cn/scripts/last30days.py \
  --last30days-query "AI 大模型" \
  --last30days-days 30 \
  --max-parallel 5 \
  --per-user-timeout 300
```

### 合并 V3 + last30days

```bash
python -m heated_topics_v3.openbiliclaw_integration.cli \
  --users data/users.json \
  --output data/recs_both.json \
  --source both \
  --last30days-cli-path /path/to/last30days-skill-cn/scripts/last30days.py \
  --last30days-query "AI 大模型" \
  --last30days-days 30
```

## 4. 配置示例

参考 `config/last30days.toml.example`：

```toml
[last30days]
cli_path = "E:/.code/My/last30days-skill-cn/scripts/last30days.py"
days = 30
fetch_bodies = true
timeout = 120.0
save_dir = "data/last30days"
```

（CLI 优于配置：所有 last30days-* flag 可直接覆盖配置文件。）

## 5. 已知限制

- **`--fetch-bodies` 对小红书 / 抖音基本无效**：未登录抓不到正文。adapter 会把所有正文缺失的 item 标为 `title_only`；OpenBiliClaw 引擎据此降级置信度。
- **`--last30days-query` 默认取用户第一个兴趣词**：跨用户都搜同一个词。如需每用户独立 query，写一个小循环跑 CLI，或在 `users.json` 字段加自定义 query（v2 计划）。
- **subprocess timeout 是 per-user 不是全局**：`--max-parallel 5` 会并发 5 个 last30days 子进程；机器内存 / 网络吃紧时把 `max-parallel` 降到 1-2。
- **缓存/重跑**：每次跑都会重新 subprocess，不会复用上次输出。需要"读本地 last30days 报告再做推荐"的功能，等 v2 引入 MCP。

## 6. 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| `Last30DaysSourceError: exited 1` | last30days 子进程崩溃 | 加 `--last30days-timeout 300`，看 stdout/stderr 真实报错 |
| `Last30DaysParseError` | 报告 JSON 损坏 | 重跑，去掉 `--fetch-bodies` 看是否是网络问题 |
| recommendations 全 0 | 用户兴趣和 last30days 抓到的平台关键词不匹配 | 改 `--last30days-query` 或在 `users.json` 调整 interests |
| 进程 hang | 多用户 last30days 并发拉得太狠 | `--max-parallel 1` + `--last30days-timeout 60` |

## 7. 内部架构

```
[CLI] --source={v3-hotlist,last30days,both}
   ↓
[recommender._fetch_candidates_for_user()]
   ├─ v3-hotlist / both 分支: fetch_candidates() → V3 providers
   ├─ last30days / both 分支: _fetch_last30days_candidates()
   │                          ├─ last30days_source.run() [subprocess]
   │                          ├─ last30days_source.parse_report() [JSON]
   │                          └─ last30days_adapter.to_hot_items() [字段映射]
   └─ both 分支：URL dedup（v3 优先）
   ↓
[复用] candidate_adapter.to_discovered() → DiscoveredContent
   ↓
[复用] RecommendationEngine.serve_external_candidates() [OpenBiliClaw]
   ↓
[复用] output.build_envelope() → JSON envelope
```

## 8. 测试覆盖

- `test_last30days_source.py` — subprocess 行为 / 错误路径（11 测试）
- `test_last30days_adapter.py` — 8 平台 × 3 类样本（含 missing body）（11 测试）
- `test_source_dispatch.py` — `_fetch_candidates_for_user` 分发 + URL dedup（5 测试）
- `test_end_to_end_last30days.py` — CLI → dispatcher → engine 全链路（2 测试）

跑：`uv run pytest tests/openbiliclaw_integration -q -m "not requires_llm and not requires_ollama"`
