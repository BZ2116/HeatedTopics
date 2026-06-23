# heatedTopics

`heatedTopics` 是一个热点话题详情采集项目。它的目标不是只保存热榜标题，而是把当日或近 7 天出现的热点话题收集出来，去重后为每个话题生成可追溯的详情证据，并输出 JSON 数据和 Markdown 报告。

当前版本聚焦第一阶段能力：

- 获取近期热点话题。
- 对热点标题做基础去重。
- 为每个热点生成详情采集记录。
- 将详情结果、失败状态和来源信息保存为结构化数据。
- 生成便于人工阅读的热点详情报告。

后续版本再扩展复杂检索词拆解、多来源事实核验、可信度评分、时间线分析和 skill/agent 封装。

## 技术栈

- **语言**：Python 3.10+
- **测试框架**：Python 标准库 `unittest`
- **数据格式**：JSON、Markdown
- **热榜入口**：DailyHotApi HTTP JSON
- **浏览器登录态**：本地浏览器 session 文件，供微博和小红书详情采集使用
- **依赖策略**：当前核心管道尽量使用 Python 标准库，避免引入额外运行依赖
- **命令入口**：`python -m src.core_pipeline.run`

## 项目流程

核心流程如下：

```text
DailyHotApi 热榜采集
  -> HotRecord 标准化
  -> today / last_7_days 窗口处理
  -> 热点标题基础去重
  -> 详情证据采集
     -> baidu 搜索详情接口
     -> source_url 原始页面详情兜底
     -> bilibili 视频元信息兜底
     -> weibo 登录态详情接口
     -> xiaohongshu 登录态详情接口
  -> DetailEvidence JSON / JSONL 落盘
  -> Markdown 报告渲染
```

### 1. 热榜采集

`src/core_pipeline/dailyhot_client.py` 负责从 DailyHotApi 路由获取热榜数据，并归一化为 `HotRecord`。

默认采集路由优先聚焦核心平台：

- `weibo`
- `xiaohongshu`
- `baidu`

其中 `baidu` 会优先尝试 DailyHotApi；如果接口返回空列表、异常或 `undefined` 这类不可用记录，会自动兜底读取 `https://top.baidu.com/board?tab=realtime`，解析标题、摘要、链接、热搜指数，并把原始 HTML 片段保存在 `HotRecord.raw_payload`。

其他平台仍可通过代码调用 `run_recent_detail_collection(..., routes=(...))` 显式传入。

`HotRecord` 只表示“这个话题在某个平台热榜上出现过”，包含：

- 平台和路由
- 标题
- 排名
- 热度值
- 原始 URL
- 采集时间
- 原始载荷
- 采集状态

注意：`HotRecord` 不是详情内容，不能单独作为完整话题详情。

### 2. 近期窗口与去重

`src/core_pipeline/recent_topics.py` 负责：

- 支持 `today` 和 `last_7_days` 两种窗口。
- 去除标题里的基础热榜装饰词，例如 `热`、`爆`、`新`、`荐`。
- 对同一规范化标题进行合并。
- 保留同一话题对应的多个平台来源和 `hot_record_ids`。

### 3. 详情证据采集

`src/core_pipeline/detail_collector.py` 负责把去重后的话题转换为详情采集任务，并输出 `DetailEvidence`。

当前详情来源包括：

- `baidu`：通过搜索结果接口生成详情证据。
- `source_url`：当搜索结果为空时，直接读取热榜记录自带的原始 URL，并从页面中提取文本作为详情兜底。
- `bilibili`：视频类内容不再抓整页噪声文本，改为保存视频标题、简介和链接。
- `weibo`：通过登录态接口记录微博详情状态。
- `xiaohongshu`：通过登录态接口记录小红书详情状态。

每条 `DetailEvidence` 会记录：

- 话题 key
- 关联热榜记录 ID
- 平台
- 来源方式
- 查询词
- 标题
- 正文或摘要内容
- 结果 URL
- 采集时间
- `fetch_status`
- `error_type`
- 原始载荷和原始页面文本

当前命令行默认的搜索 provider 是空实现，因此百度搜索详情可能显示为 `empty_content`。不过主流程会继续尝试读取热榜记录自带的原始 URL，并以 `source_method = source_url` 保存页面文本。真实搜索结果接入点仍然预留在 `run_recent_detail_collection(..., search_provider=...)`，后续可以接入百度搜索 API、网页搜索服务或自建搜索 provider。

Bilibili 视频页会使用 `source_method = video_metadata` 保存标题、简介和链接，避免整页抓取时出现乱码或大量脚本噪声。

### 4. 报告输出

`src/core_pipeline/report_renderer.py` 负责生成 Markdown 报告。报告会展示：

- 采集窗口
- 去重后话题数量
- 有详情话题数量
- 缺失详情话题数量
- 每个话题的热榜来源
- 每个话题的详情内容摘要
- 各平台详情采集状态

## 目录结构

```text
heatedTopics/
  README.md
  src/
    core_pipeline/
      run.py                 # 核心 CLI 入口
      dailyhot_client.py     # DailyHotApi 热榜采集与标准化
      recent_topics.py       # 窗口处理与基础去重
      detail_collector.py    # 话题详情证据采集编排
      json_store.py          # JSON 读写工具
      report_renderer.py     # Markdown 报告渲染
      types.py               # HotRecord / DetailEvidence 等数据结构
      source_registry.py     # 热榜路由分组
      session_gate.py        # 微博 / 小红书登录态检查
      providers/
        baidu.py
        weibo.py
        xiaohongshu.py
        auxiliary.py
    browser/
      session_manager.py
      page_guards.py
  tests/
    core_pipeline/
  data/
    raw/
    processed/
    evidence/
  reports/
  docs/
    superpowers/
      specs/
      plans/
```

## 快速开始

在项目根目录运行测试：

```bash
cd heatedTopics
python -m unittest discover -s tests -v
```

采集今日热点详情：

```bash
python -m src.core_pipeline.run collect-recent-details --window today
```

采集近 7 天窗口：

```bash
python -m src.core_pipeline.run collect-recent-details --window last_7_days
```

查看生成报告：

```bash
cat reports/recent_hot_topics_digest.md
```

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 运行全部测试 |
| `python -m src.core_pipeline.run collect-recent-details --window today` | 采集今日热点详情 |
| `python -m src.core_pipeline.run collect-recent-details --window last_7_days` | 采集近 7 天热点详情 |
| `python -m src.core_pipeline.run paths` | 写出核心输出路径 |
| `python -m src.core_pipeline.run render-report` | 渲染旧版核心平台报告 |
| `python -m src.browser.session_manager check` | 检查浏览器登录状态 |
| `python -m src.browser.session_manager login weibo` | 初始化微博登录态 |
| `python -m src.browser.session_manager login xiaohongshu` | 初始化小红书登录态 |

## 输出文件

| 文件 | 说明 |
| --- | --- |
| `data/raw/dailyhot_records.json` | DailyHotApi 热榜记录，保存标准化后的 `HotRecord` |
| `data/processed/topic_clusters.json` | 基础去重后的话题列表 |
| `data/evidence/detail_evidence.json` | 各平台详情证据，保存 `DetailEvidence` |
| `data/evidence/detail_evidence_raw.jsonl` | 每行一条详情证据，保留 raw payload 和原始页面文本，方便后续流式筛选 |
| `data/processed/topic_briefs.json` | 旧版摘要流程使用的话题摘要文件 |
| `reports/recent_hot_topics_digest.md` | 当前第一版的近期热点详情报告 |
| `reports/core_platform_topic_digest.md` | 旧版核心平台报告渲染输出 |

## 数据状态说明

详情证据使用 `fetch_status` 表示采集状态：

| 状态 | 含义 |
| --- | --- |
| `ok` | 采集成功，且通常应有非空 `content` |
| `empty_content` | 请求或流程执行了，但没有拿到可用详情正文 |
| `login_required` | 该平台需要登录态 |
| `captcha_required` | 遇到验证码或安全验证 |
| `rate_limited` | 遇到限流或风控 |
| `failed` | 采集失败 |

第一版判断详情是否可用的核心标准是：`DetailEvidence.content` 非空。只有热榜标题、排名和热度不算有效详情。

## 登录态与风控

微博和小红书属于登录态平台。使用前可以运行：

```bash
python -m src.browser.session_manager check
```

如果提示缺少登录态，再运行：

```bash
python -m src.browser.session_manager login weibo
python -m src.browser.session_manager login xiaohongshu
```

登录态文件属于本地私有运行产物，不应提交到仓库。遇到验证码、滑块、登录失效或风控页时，采集逻辑应记录状态并停止对应平台，不做绕过。

## 当前限制

- 默认 CLI 已串起近期热点收集、去重、详情证据写入和报告输出；搜索 provider 仍需接入，但原始 URL 页面读取已经作为详情兜底。
- 默认热点路由聚焦 `weibo`、`xiaohongshu`、`baidu`；其中百度带有官方热榜页兜底采集，微博和小红书如果 DailyHotApi 当前不支持，会在热榜记录中保留失败状态。
- Bilibili 详情使用视频元信息，不抓整页 HTML 内容。
- `today` 和 `last_7_days` 当前共享同一套执行流程；近 7 天窗口需要结合已有缓存或后续的历史采集任务才能体现完整历史聚合。
- 微博和小红书详情采集依赖本地登录态，且不绕过平台风控。
- 当前版本不做事实核查、可信度评分、时间线生成或观点分析。

## 开发与验证

运行全部测试：

```bash
python -m unittest discover -s tests -v
```

运行核心管道测试：

```bash
python -m unittest discover -s tests/core_pipeline -v
```

验证近期热点详情流程的关键测试包括：

- `tests/core_pipeline/test_recent_topics.py`
- `tests/core_pipeline/test_dailyhot_client.py`
- `tests/core_pipeline/test_detail_collector.py`
- `tests/core_pipeline/test_run.py`
- `tests/core_pipeline/test_report_renderer.py`

## 设计文档

本阶段设计和执行计划保存在：

- `docs/superpowers/specs/2026-06-22-hot-topic-detail-collection-design.md`
- `docs/superpowers/plans/2026-06-22-hot-topic-detail-collection.md`
