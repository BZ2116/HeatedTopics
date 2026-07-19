# Baidu Hot-Word Source Design

- Status: Draft
- Owner: 本地单人
- Source ID: `baidu`
- Hot-board matrix position: 与 `docs/specs/platform-hot-list-matrix.md` 中已计划的 `baidu` 行同位

## Goal

为 `heated-topics-v3` 增加**百度热搜**作为第二条数据源，与现有的头条（`toutiao`）/ 掘金（`juejin`）形成可对比的「百度搜索意图侧」。本期只交付「单源可跑通」、不涉及跨源汇总。

## Out Of Scope（明确不做）

- 跨源 `TopicCluster`、`ReportBundle` 合并
- 跨源去重
- 历史数据回填 / 时间窗聚合
- 关键词检索通道（百度热搜是平台级信号，本身不接受查询参数）
- `top.baidu.com` HTML 兜底（已有干净 JSON）
- `m.baijiahao.baidu.com` SPA 入口（探针已验证不可达）
- Cookie 采集与反爬 ladder（探针已验证本路径无需）

## Source Identity

| 字段 | 值 | 说明 |
|---|---|---|
| `source_id` | `baidu` | 与 `platform-hot-list-matrix.md` 一致 |
| `HotItem.platform` | `baidu` | |
| `HotItem.item_type`（热词层）| `hotword` | 与头条 / 掘金的 `article` 区分 |
| `HotItem.item_type`（文章层）| `article` | 命中词搜索结果里的百家号条目 |
| `ItemDetail.platform` | `baidu` | |
| `ItemDetail.extraction_method` | `baijiahao_article_page` | 正文抓自 `baijiahao.baidu.com/s?id=...` HTML |
| `report.title` | `Baidu 热搜日报` | 与现有 `Juejin` / `Toutiao` 报告对齐 |
| `outputs/<profile>/baidu/run_<ts>/...` | 同现有约定 | |

`profile.preferred_platforms` 包含 `"baidu"` 时 `matching.match_hot_item_to_queries` 会自然过滤；现有 `config/profiles/tech_ai_creator.json` 已声明 `"baidu"`，无需改动。

## Three-Stage Fetch

数据从「热搜词」到「正文」共三段，每段产物可独立缓存，并接受 `fetcher: Callable[[str, int], str]` 注入以便测试。

### Stage 1 — 热词列表

- URL：`https://top.baidu.com/api/board?platform=wise&page=realtime`
- Headers：`User-Agent`（移动端）、`Accept: application/json`、`Referer: https://top.baidu.com/`
- 响应：`{"success": true, "data": {"cards": [{"component": "tabTextList", "content": [...]}]}}`
- 解析：从 `cards[0].content[0].content[]` 抽出 `{word, url, index, hotTag}`
- 缓存：`cache/baidu/board/<UTC+8 date>.json`，按日复用一个快照
- 失败：返回 `[]` + `fetcher.log` 写 warning，pipeline 进入「空报告」分支

### Stage 2 — 热词 → 文章链接

- 输入：`stage1` 产出的热词（保留 top-N，N 默认取 30，可由 CLI 覆盖）
- URL：`https://m.baidu.com/s?word=<urlencoded>`
- Headers：`User-Agent`（移动端）、`Accept-Language: zh-CN,zh;q=0.9`、`Referer: https://m.baidu.com/`
- 解析：`re.findall(r'baijiahao\.baidu\.com/s\?id=([A-Za-z0-9_\-]+)', html)` 收集去重后的 article ID；附近 `<h3>` 文本作为召回文章标题
- 节流：5–10s jitter，每 5 次休 60s（参照 `fetcher_factory` 同节奏）
- 兜底：单日 `cache/baidu/search/<word_sha1>.json`；命中即跳过 fetcher；命中失败 / 验证码则跳过该热词
- 失败：验证码 / 频控 / 解析失败，单词级降级，不打断其他词

### Stage 3 — 文章正文

- URL：`https://baijiahao.baidu.com/s?id=<id>`
- Headers：移动端 UA、`Referer: https://m.baidu.com/s`
- 解析：复用 `juejin.py` 的 `_ArticleTextParser` 思路，写一个针对百家号 HTML 的 `<article>` / 内容容器的纯 Python HTML parser（仅依赖 stdlib）
- 缓存：`cache/baidu/articles/<article_id>.json`，日级复用
- 失败：`fetch_status = "empty"`，保存 `raw_payload = {"html_length": ...}`，文章 txt 仍写出但标注「无正文」

## Caching

照搬 `toutiao_search_cache.py` 的模式，单飞 + 锁文件 + atomic write，共四个缓存文件：

| 缓存路径 | Key | 范围 |
|---|---|---|
| `cache/baidu/board/<date>.json` | `date` | 全天一份热搜快照 |
| `cache/baidu/search/<sha1(word)>.json` | sha1(原文) | 同日跨 run 复用 |
| `cache/baidu/articles/<article_id>.json` | article id | 同日跨 run 复用 |
| `cache/baidu/board_index/<date>.json` | `date` | 「热词 → 召回文章列表」中间产物，可选 |

缓存 schema 一律带 `schema_version`，版本号独立递增（与 toutiao_search_cache 不耦合）。失败写入容忍：磁盘满 / 解码异常一律跳过，不阻塞主路径。

## Pipeline Integration

新增 `pipeline.run_baidu_pipeline(...)`，与 `run_juejin_pipeline` 同样的入参形态，复用 `_run_platform_pipeline(source_id="baidu", ...)`。

注：因 `baidu` 源两段（热词 → 文章）天然耦合，整段作为一个「hot items fetcher」返回 `HotItem` 列表（每条同时带 `raw_payload.source_kind = "baidu_search_word"` 之类标记），再循环抓详情。详情抓取与 `fetch_baidu_item_detail(item)` 之间共享 `cache/baidu/articles/`。

`raw_payload.source_kind` 字段由 `_build_hot_item_rows` 透传到 `report.md` 的「Source」行，便于日后区分「热词召回 vs 同一热词下多文章」。

## CLI

新增子命令 `baidu`，与 `juejin` / `toutiao` 并列：

```powershell
cd E:\.code\My\heatedTopics-V3
$env:PYTHONPATH='src'
uv run python -m heated_topics_v3.cli baidu `
  --profile config\profiles\tech_ai_creator.json `
  --output-root outputs `
  --cache-root cache `
  --top-n 30
```

参数：

- `--profile`（必）：`UserProfile` JSON
- `--output-root` / `--output-dir`：`outputs/`
- `--cache-root`：`cache/`
- `--top-n`：进入 stage 2 的热词数量上限（默认 30）
- `--fetched-at`：可选覆盖
- `--offline`：只读缓存，不发起任何外网请求
- `--force-board-refresh`：忽略 board 缓存，跑一遍新鲜数据
- `--max-quota-per-day`、`--state-root`、`--skip-quota`：与头条 v2 同样的当日配额

输出：`outputs/<profile_id>/baidu/run_<ts>/hot_items.json | article_texts/ | report.md`，与现有模式对齐。

## Reporting

`reporting.py` 新增 `render_baidu_report(profile, matches, fetched_at, item_details)`：复用 `_render_platform_report("Baidu 热搜日报", profile, matches, fetched_at, item_details)`。**不做与头条 / 掘金的合并报告**。

## Failure Semantics

| 失败点 | 行为 |
|---|---|
| Stage 1 失败 | `report.md` 写「今日未拿到百度热搜数据」+ warning 日志；其他平台继续 |
| Stage 1 返回 `success:false` | 同上 |
| Stage 2 命中验证码 | 单词级跳过，warning 记入 fetcher log |
| Stage 2 命中缓存但内容陈旧 | 仍用缓存，再 warning |
| Stage 2 频控被踢 | 该 batch 早退；下次启动重新尝试 |
| Stage 3 文章正文拿不到 | `fetch_status="empty"`，txt 文件照写「无正文」 |
| 全空 | `report.md` 顶部 `<h3>本次未抓到任何条目</h3>` |

任何失败**不抛 exception**，pipeline 必须输出完整 `hot_items.json`（即便为空）+ `report.md`。

## Testing Strategy

| 测试文件 | 关注点 |
|---|---|
| `tests/providers/test_baidu_parsing.py` | 解析固定 JSON / HTML 样本：board response、search page HTML（截图自侦察样本 `tmp/baijiahao_probe/search_samples/`）、article body HTML |
| `tests/test_baidu_pipeline.py` | 仿 `test_juejin_pipeline.py`：伪造三个 fetcher，断言 `outputs/<profile>/baidu/run_<ts>/` 完整 + `report.md` 含 `Baidu 热搜日报` |
| `tests/test_baidu_throttling.py` | 仿 `tests/test_toutiao_search_cache.py`：验证 cache 命中、lock 超时、schema mismatch 升级 |
| `tests/test_baidu_offline.py` | `--offline` 行为：缓存空时返回空报告，不发起任何网络请求（用 monkeypatch 阻止 urllib.request） |

不做端到端 live test（探针已经覆盖过的部分不重复）；CI 通过上述单测即可。

## Documentation Updates

- 本设计稿：`docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-19-baidu-hotword-source.md`
- `docs/specs/platform-hot-list-matrix.md`：`baidu` 行从「首批未实现」改为「首批已实现」，并指向本设计稿
- `README.md`：补一段「Baidu 热搜」命令示例，与现有头条 / 掘金并列

## Cleanup Of Reconnaissance Probes

侦察期在 `scripts/` 下写了 5 个一次性探针文件。本期实现完成后合并为：

- 保留：`scripts/probe_baidu_board.py`（一次跑过的 API + URL 历史 + 验证细节，作为后续 debug 参考）
- 删除：`probe_baijiahao.py`、`probe_baijiahao_m.py`、`probe_baijiahao_api.py`、`probe_baijiahao_api_v2.py`、`probe_baijiahao_search.py`

`tmp/baijiahao_probe/` 的产物不清理（属于 `tmp/` 运行时产物目录，不进源码）。

## Implementation Order（粗排，便于 plan 阶段细化）

1. 实现并测试 `providers/baidu.py` 三个解析函数
2. 实现并测试 `baidu_cache.py`
3. 实现 `pipeline.run_baidu_pipeline`
4. 实现 `reporting.render_baidu_report`
5. 实现 CLI 子命令 `baidu`
6. 三类集成测试 + `--offline` 测试
7. 更新 `platform-hot-list-matrix.md` + `README.md`
8. 清理探针脚本
9. 跑 `uv run pytest -q` 全量，确认无回归
