# 核心平台热点详情采集方案设计稿

**日期**：2026/06/14
**汇报对象**：项目组

---

## 1. 调研结果

### 1.1 热榜发现层 vs 详情证据层

热榜平台分为两层：

| 层级 | 说明 | 平台代表 |
|------|------|---------|
| **发现层** | 提供热点标题和摘要，**不需要登录** | 百度实时热点、知乎、36氪、IT之家、GitHub 趋势等 |
| **详情层** | 提供正文内容、评论、互动数据，**必须登录** | 微博、小红书 |

**关键发现**：能发现热点的平台不等于能获取详情。微博和小红书的内容访问全部需要登录态，公开接口不存在绕过方案。

### 1.2 各平台登录要求调研

| 平台 | 搜索/详情是否需要登录 | 备选方案 |
|------|----------------------|---------|
| 微博 | **必须登录**（搜索结果页、评论区均拦截未登录请求） | 无公开接口，需模拟浏览器 |
| 小红书 | **必须登录**（笔记详情、评论均需要登录态） | 无公开接口，需模拟浏览器 |
| 百度 | 搜索结果公开可访问 | 可直接请求 |

**结论**：微博和小红书没有替代的公开数据源。实现详情采集的唯一路径是**模拟登录态浏览器**。

### 1.3 现有工具能力边界

**现有热榜采集 Skills 或 Agent**（如 Jina 等详情采集工具）只能完成基础信息收集：

- 能做到：抓取公开页面的标题、摘要、链接等表层信息
- 做不到：获取微博/小红书这类平台的**正文内容、评论、互动数据**

原因在于微博和小红书没有公开的 HTML 可读页面，所有内容访问均被登录态拦截。即使使用 Jina 这类通用抓取工具，遇到微博/小红书也会直接遇到验证码页面或 403，自动化采集失效。

**结论**：在详情采集环节，自动化工具无法替代人工。微博和小红书的详情必须通过真实登录态浏览器获取，这一限制是当前技术条件下的硬性约束，无法绕过。

### 1.4 技术栈调研结论

- DailyHotApi 作为发现层：HTTP 接口，无需登录，响应快
- 微博/小红书详情：必须使用已登录的浏览器会话（Playwright + 保存的 cookies）
- 百度搜索：直接 HTTP 请求即可
- 辅助平台（GitHub、36氪、IT之家等）：HTTP 接口，无需登录，补充上下文
- 存储：JSON 文件（data/raw/、data/evidence/、data/processed/）
- 输出：Markdown 报告

---

## 2. 为什么要选择这个技术栈

### 2.1 架构原则

**把 DailyHotApi 当作召回层，不当作详情层。**

每个话题必须同时具备三个核心详情来源（weibo、xiaohongshu、baidu），才算完整。DailyHotApi 记录仅作为发现线索和辅助证据，单独存在时话题永远不完整。

### 2.2 技术选型理由

| 技术选型 | 理由 |
|---------|------|
| **Python 3.10+ 标准库 + unittest** | 项目已在使用，直接复用，无新依赖 |
| **JSON 文件** | 第一版文件模式，便于人工检查 trace，可快速迭代 |
| **Playwright + 浏览器登录态** | 微博和小红书没有其他获取方式，必须如此 |
| **不引入 LangChain 等框架** | 第一版用确定性 fallback，LLM client 后续按需接入 |

### 2.3 登录优先的设计动机

- 微博和小红书的反爬机制：未登录请求会收到验证码拦截（captcha）或直接返回空内容
- 登录态检查作为 pipeline 第一关：session 不存在则直接标记 `login_required`，不继续空跑
- 私有 browser_state 文件不进入 Git（.gitignore 隔离），保证 cookie 安全

---

## 3. 核心方案说明

### 3.1 数据模型

```
HotRecord          # 来自 DailyHotApi 的发现记录
DetailEvidence    # 详情证据（来自微博/小红书/百度）
RequiredDetailStatus  # 评估每个话题的 required 来源完整性
TopicCluster      # 同一话题的 records + evidence 聚合
TopicBrief        # 最终输出：摘要、关键事实、平台观察
```

### 3.2 Pipeline 流程

```
第一步：检查登录态 (check-sessions)
    ↓
    ├─ data/browser_state/weibo.json        有 cookie → ok
    └─ data/browser_state/xiaohongshu.json   有 cookie → ok
    （无 cookie → 标记 login_required，pipeline 继续但不采集）

第二步：采集热榜 (collect-dailyhot)
    ├─ 从 DailyHotApi 拉取各路由数据
    └─ 存入 data/raw/dailyhot_records.json

第三步：采集核心详情 (collect-core-details)
    ├─ 微博：读取 browser_state → 打开搜索页 → 提取正文
    ├─ 小红书：读取 browser_state → 打开搜索页 → 提取笔记
    └─ 百度：直接 HTTP 搜索 → 提取结果摘要

第四步：采集辅助证据 (collect-aux-evidence)
    └─ 将 DailyHotApi 各路由 desc 转成 auxiliary evidence

第五步：聚类 + 生成简报 (cluster-topics + generate-briefs)
    ├─ 按标题去重合并 records + evidence
    └─ 输出 TopicBrief（确定性 fallback，不依赖 LLM）

第六步：渲染报告 (render-report)
    └─ 生成 reports/core_platform_topic_digest.md
```

### 3.3 完整性评估规则

话题完整度有四种状态：

| 状态 | 条件 |
|------|------|
| `complete` | weibo、xiaohongshu、baidu 三个 required 来源全部 `ok` |
| `core_incomplete` | 至少一个 required 来源缺失/失败/登录拦截 |
| `auxiliary_only` | 所有 required 来源都失败，但存在 auxiliary 证据 |
| `failed` | 没有任何可用证据 |

报告必须清晰展示每个话题缺失了哪个 required 来源，以便人工介入。

### 3.4 登录态管理

```
data/browser_state/weibo.json        # 微博 cookies（不进 Git）
data/browser_state/xiaohongshu.json # 小红书 cookies（不进 Git）
```

首次使用需要手动执行 `make login-weibo` 和 `make login-xiaohongshu`（打开浏览器交互式登录），之后保存在本地。后续运行 pipeline 时直接读取。

### 3.5 为什么不能绕过登录

微博和小红书是**唯一的事实来源**，不存在任何公开接口：

- 微博搜索页未登录返回验证码页面，无法提取内容
- 小红书笔记详情未登录返回 403，无法提取正文
- 百度搜索结果公开可访问，作为 required 来源之一

**没有替代方案。** 强行绕过会触发反爬，IP 被封禁，数据不可用。唯一可行的路径就是模拟浏览器 + 真实登录。

---

## 4. 文件结构

```
src/core_pipeline/
├── __init__.py
├── source_registry.py      # 路由分组、required/auxiliary 定义
├── types.py               # HotRecord、DetailEvidence 等 dataclass
├── json_store.py          # JSON 读写
├── dailyhot_client.py     # DailyHotApi 采集
├── session_gate.py        # 登录态检查
├── completeness.py        # 完整性评估
├── topic_clusterer.py     # 话题聚类
├── brief_generator.py     # 简报生成
├── report_renderer.py     # Markdown 输出
├── run.py                 # CLI 编排
└── providers/
    ├── baidu.py           # 百度详情
    ├── weibo.py           # 微博详情（browser session）
    ├── xiaohongshu.py     # 小红书详情（browser session）
    └── auxiliary.py       # 辅助证据
```

---

## 5. 运行方式

### 首次运行（需要手动登录）

```bash
make check-sessions          # 检查登录态
make login-weibo             # 打开浏览器，交互式登录微博
make login-xiaohongshu       # 打开浏览器，交互式登录小红书
make check-sessions          # 确认登录成功
make run-core-pipeline       # 执行完整 pipeline
```

### 后续运行

```bash
make run-core-pipeline
```

---

## 6. Demo 版 vs 长期版

| 阶段 | 内容 |
|------|------|
| **Demo 版（本次实现）** | 文件模式，手动触发，确定性 fallback 简报，浏览器采集用 Playwright |
| **长期稳定版（后续扩展）** | 定时任务调度、LTM client 接入、公开 API 替代方案探索（若微博/小红书开放） |