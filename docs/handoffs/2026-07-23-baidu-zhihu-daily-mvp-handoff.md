# Baidu Hot Search and Zhihu Daily MVP Handoff

## 1. 当前状态

百度热搜和知乎日报的产品边界、技术设计及完整 TDD 实施计划已经完成并获用户批准。

目前尚未编写任何生产代码或测试代码。下一位 Agent 应从实施计划的 Task 1 开始，不要重新设计，也不要跳过 RED 测试。

当前状态：

```text
Design: completed and approved
Implementation plan: completed
Implementation: not started
Next task: Task 1 — Add Optional Provider Capabilities
Baseline tests: 277 passed
```

## 2. 仓库、分支和隔离工作树

主仓库：

```text
E:\.code\My\heatedTopics\heatedTopics
```

本任务唯一允许使用的隔离工作树：

```text
E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp
```

功能分支：

```text
feature/baidu-zhihu-daily-mvp
```

当前 HEAD：

```text
d570d31 docs: plan baidu and zhihu daily mvp
```

提交历史：

```text
d570d31 docs: plan baidu and zhihu daily mvp
9cb6086 docs: design baidu and zhihu daily mvp
2aeca86 feature/cached-news-providers base
```

不要在以下工作树中实现本任务：

```text
E:\.code\My\heatedTopics\heatedTopics
E:\.code\My\heatedTopics\heatedTopics\.worktrees\cached-news-providers
E:\.code\My\heatedTopics\heatedTopics\.worktrees\hot-topic-workflow
```

`cached-news-providers` 工作树存在其他未提交改动。本任务分支已经从其已提交的 `2aeca86` 建立，不应复制、覆盖或提交其他工作树中的未提交文件。

## 3. 必须完整阅读的文档

### 已批准设计

```text
docs/superpowers/specs/2026-07-23-baidu-zhihu-daily-mvp-design.md
```

设计提交：

```text
9cb6086
```

### 逐步实施计划

```text
docs/superpowers/plans/2026-07-23-baidu-zhihu-daily-mvp.md
```

计划提交：

```text
d570d31
```

实施时以完整计划为准。本 handoff 只负责说明上下文和恢复入口，不能代替计划中的文件清单、接口签名、RED/GREEN 命令、提交边界和验收规则。

## 4. 用户已经确认的产品决策

### 4.1 整体流程

两个平台都进入现有 cached-news 工作流：

```text
每日预采集官方榜单
→ 提前补齐并验证正文
→ 写入有效缓存
→ 用户请求读取缓存并匹配关键词
→ 匹配达到 5 条则停止
→ 少于 5 条才执行平台搜索或官方归档扫描
→ 最多检查 60 条搜索候选
→ 每个平台最多返回 20 条正式结果
```

统一常量：

```python
MIN_RESULTS = 5
MAX_RESULTS = 20
SEARCH_PAGE_SIZE = 15
MAX_SEARCH_CANDIDATES = 60
```

### 4.2 百度热搜

百度榜单项是“热点事件”，不是固定文章。

最终合格记录由两部分组成：

```text
百度热搜事件
├── 官方排名
├── hotScore
└── 百度事件 URL

支持文章
├── 实际文章标题和来源
├── 实际文章 URL
└── 完整正文
```

必须遵守：

- 百度排名和 `hotScore` 归属于热点事件。
- 支持文章正文必须单独标注真实来源。
- 不能把百度热度伪装成支持文章的阅读量。
- 普通百度搜索结果只有在能够关联到当日官方热搜事件时，才能进入正式结果。
- 用户请求不能重新请求百度官方热榜。
- 用户搜索只能使用已缓存的、合格的当日百度热点事件作为上下文。

### 4.3 知乎日报

用户明确选择的是“知乎日报”，不是“知乎热榜”。

使用：

```text
最新推荐：GET https://daily.zhihu.com/api/4/news/latest
正文详情：GET https://daily.zhihu.com/api/4/news/<story_id>
历史推荐：GET https://daily.zhihu.com/api/4/news/before/YYYYMMDD
```

必须遵守：

- 最新和历史列表属于知乎日报官方推荐。
- 使用推荐日期和当日顺序作为官方榜单证据。
- 不虚构阅读量、点赞量、评论量或综合热度。
- 没有原生关键词搜索 API，因此扫描最近 7 天官方推荐归档。
- 归档候选去重后最多检查 60 条，最终最多 20 条。

### 4.4 正文要求

没有完整正文不得降级。

正文门槛：

```text
平台结构化正文或明确正文容器：至少 80 个有效字符
GNE 通用兜底正文：至少 200 个有效字符
```

两种来源都必须另外满足：

```text
至少 2 个真实段落
或
至少 3 个完整句子
```

必须拒绝：

- 标题或标题拼接；
- 摘要或重复摘要；
- 登录提示；
- 验证码页面；
- 搜索结果页；
- 页面导航和页脚；
- 推荐列表和评论区；
- 视频、图集或只有外链的内容；
- 被截断或需要登录后才能继续阅读的内容。

### 4.5 访问限制

不允许：

- 长期 Cookie；
- 登录态；
- Authorization 或 API Key；
- Playwright；
- 验证码绕过；
- LLM 或向量模型事件关联；
- 用户请求阶段刷新官方热榜。

## 5. 已选技术方案

不调用 DailyHotApi 公共服务，也不部署第二个 DailyHotApi 服务。

需要把 DailyHotApi 的百度榜单解析思路移植到现有 Python Provider，直接访问原始公开端点。

两项新 Provider：

```text
src/heated_topics_v3/providers/baidu_hot.py
src/heated_topics_v3/providers/zhihu_daily.py
```

平台标识：

```text
baidu_hot
zhihu_daily
```

它们需要注册到现有：

```text
heated-topics collect-news
heated-topics generate-news
```

不要增加新的平台专属 CLI。

## 6. 计划中的七个任务

### Task 1：通用可选能力

增加以下可选 Provider hook：

```text
search_with_context
build_board_evidence
build_search_evidence
rank_articles
```

用途：

- 百度搜索文章继承缓存热点事件的官方证据。
- 知乎日报允许只有官方排名、没有互动量的数据通过。
- 知乎日报按推荐日期优先排序。

### Task 2：百度官方热榜

实现：

```text
GET https://top.baidu.com/board?tab=realtime
```

解析：

```html
<!--s-data:...-->
```

保存稳定事件 ID、官方排名、`hotScore`、描述、查询词、图片及原始 URL。

### Task 3：百度正文和上下文搜索

实现：

- 支持文章搜索；
- 百度跳转 URL 解析；
- 事件与文章的确定性相关性判断；
- JSON-LD、`<article>`、GNE 正文提取；
- `ItemDetail.source_url` 保存真实文章 URL；
- 搜索结果继承父热点事件排名和 `hotScore`。

### Task 4：知乎日报最新推荐和正文

实现：

- 最新列表；
- `type == 0` 过滤；
- 稳定 story ID；
- 详情 API 正文 HTML 清洗；
- 无互动量的官方排名证据。

### Task 5：知乎日报最近 7 天归档搜索

实现：

- 7 天归档一次性内存缓存；
- NFKC 标题和 hint 预过滤；
- story ID 去重；
- 60 候选和 20 结果边界；
- 推荐日期优先、当日排名其次的确定性排序。

### Task 6：接入 cached-news

扩展：

```text
NEWS_PLATFORMS
NEWS_DISPLAY_ORDER
cli._news_providers
providers/__init__.py
```

并将推荐结果的 `source_url` 改为：

```python
article.detail.source_url or article.hot_item.url
```

确保百度结果展示支持文章 URL，而不是只展示百度事件搜索 URL。

### Task 7：真实验证

完成：

- smoke validator 对官方 rank-only 证据的支持；
- provider、workflow、CLI 和完整测试；
- `compileall`；
- `git diff --check`；
- 匿名真实采集；
- 百度和知乎日报各一次搜索路径；
- 凭据扫描；
- 实施报告。

## 7. TDD 和提交要求

必须使用：

```text
superpowers:test-driven-development
```

每个新行为必须：

```text
写失败测试
→ 运行并确认因缺少功能而失败
→ 写最小生产代码
→ 运行并确认通过
→ 运行相关回归测试
→ 单独提交
```

不能先写生产代码再补测试。

计划定义的建议提交：

```text
feat: support contextual official discovery
feat: parse baidu official hot board
feat: resolve baidu hot event articles
feat: collect zhihu daily full stories
feat: search zhihu daily archives
feat: register baidu and zhihu daily providers
docs: verify baidu and zhihu daily mvp
```

每个任务结束后检查：

```powershell
git status --short
git diff --check
uv run pytest <focused tests> -q
```

Task 1、Task 3、Task 5、Task 6 和 Task 7 结束时应额外运行：

```powershell
uv run pytest -q
```

## 8. 当前已验证基线

在计划提交后重新执行：

```powershell
uv run pytest -q
```

结果：

```text
277 passed in 5.28s
```

同时验证：

```text
git diff --check: exit 0
git status --short: clean
plan placeholder scan: clean
```

## 9. 关键风险

### 百度搜索页面变化

百度搜索 HTML、跳转规则或验证页可能发生变化。实现必须：

- 保存 fixture 固定契约；
- HTTP 或 schema 异常失败关闭；
- 明确识别 CAPTCHA/验证页面；
- 限制请求数量；
- 不使用登录或浏览器绕过。

### 百度主题与文章的错误关联

不能只因为文章命中用户关键词，就继承百度热度。

文章必须同时：

- 命中用户关键词；
- 与父热点事件满足设计中规定的确定性标题/词项关系；
- 具有完整正文。

### 知乎日报没有数字热度

不得为了复用现有排序而伪造数值。只使用：

```text
官方推荐身份
推荐日期
当日排名
发布时间
稳定 story ID
```

### 现有 validator 假设 metrics 非空

知乎日报的合法官方排名证据允许 `metrics={}`。需要只对
`official_hot_board` 放宽这一点；`public_engagement` 仍必须具有正数公开指标。

### 真实正文版权

真实 smoke 数据必须放在工作树之外的临时目录。不要提交大量真实文章正文、搜索响应或用户生成内容。

## 10. 推荐的接手步骤

```powershell
Set-Location 'E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp'
git status --short --branch
git log -5 --oneline
Get-Content -Raw docs/superpowers/specs/2026-07-23-baidu-zhihu-daily-mvp-design.md
Get-Content -Raw docs/superpowers/plans/2026-07-23-baidu-zhihu-daily-mvp.md
uv sync
uv run pytest -q
```

预期：

```text
branch: feature/baidu-zhihu-daily-mvp
HEAD: handoff commit following d570d31
tests: 277 passed
working tree: clean
```

然后：

1. 使用 `superpowers:executing-plans` 或用户明确授权后的
   `superpowers:subagent-driven-development`。
2. 从计划 Task 1 开始。
3. 读取 Task 1 的全部步骤和涉及文件。
4. 严格执行 RED → GREEN → REFACTOR。
5. 不要提前实现 Task 2 或创建百度/知乎生产代码。

## 11. 可直接复制给其他 Agent 的提示

```text
请接手 Baidu Hot Search and Zhihu Daily MVP。

只在以下隔离工作树工作：
E:\.code\My\heatedTopics\heatedTopics\.worktrees\baidu-zhihu-daily-mvp

分支：
feature/baidu-zhihu-daily-mvp

首先完整阅读：
1. docs/handoffs/2026-07-23-baidu-zhihu-daily-mvp-handoff.md
2. docs/superpowers/specs/2026-07-23-baidu-zhihu-daily-mvp-design.md
3. docs/superpowers/plans/2026-07-23-baidu-zhihu-daily-mvp.md

当前只完成了设计和计划，没有实现生产代码。基线为 277 passed。

使用 superpowers:test-driven-development，严格从计划 Task 1 开始。
先写失败测试并运行确认 RED，再写最小实现。每个任务按计划独立提交。

不要使用长期 Cookie、登录态、Playwright、验证码绕过、LLM 或搜索排名作为热度。
百度热度属于热点事件，正文必须单独标注支持文章来源。
知乎日报只使用官方推荐日期和当日排名，不得虚构互动量。
没有完整正文的记录必须淘汰。
不要触碰或复制其他工作树中的未提交改动。
```
