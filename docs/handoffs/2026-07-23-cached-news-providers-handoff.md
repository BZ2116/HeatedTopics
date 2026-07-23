# Cached News Providers Handoff

## 1. 当前结论

新浪新闻、澎湃新闻和网易新闻的数据源设计与实施计划已经完成。
实现工作已完成 Task 1，并通过独立的规格符合性与代码质量复审。

Task 2 子代理已按用户要求中断，中断前没有产生代码改动或提交。
当前功能分支工作树是干净的，可以直接由其他 agent 接手。

## 2. 仓库与工作树

主仓库：

```text
E:\.code\My\heatedTopics\heatedTopics
```

不要在当前 `V3` 主工作区继续实现。实现分支位于隔离工作树：

```text
E:\.code\My\heatedTopics\heatedTopics\.worktrees\cached-news-providers
```

分支：

```text
feature/cached-news-providers
```

当前 HEAD：

```text
121d4fd fix: harden article qualification validation
```

代码基线：

```text
15965aa V4 / feature/hot-topic-workflow
```

当前工作树状态：

```text
clean
```

## 3. 关键文档

设计文档：

```text
docs/superpowers/specs/2026-07-23-sina-thepaper-netease-provider-design.md
```

实施计划：

```text
docs/superpowers/plans/2026-07-23-cached-news-providers.md
```

子代理持久进度：

```text
.superpowers/sdd/progress.md
```

Task 1 实现报告：

```text
.superpowers/sdd/cached-news-task-1-report.md
```

Task 1 审查 findings：

```text
.superpowers/sdd/cached-news-task-1-review.md
```

Task 2 brief 已经生成：

```text
.superpowers/sdd/task-2-brief.md
```

`.superpowers/sdd/` 中的 brief、review package、progress 和
`cached-news-*` 报告受该目录自己的 `.gitignore` 管理，属于本工作树的
恢复材料，不需要提交。

## 4. 已确认的产品规则

支持的第一批平台：

```text
sina_news
thepaper
netease_news
```

腾讯新闻暂缓。腾讯热榜和正文不需要 Cookie，但没有确认到稳定、匿名的
原生关键词搜索接口，暂时无法完成搜索补足闭环。

统一常量：

```python
MIN_RESULTS = 5
MAX_RESULTS = 20
SEARCH_PAGE_SIZE = 15
MAX_SEARCH_CANDIDATES = 60
```

每个平台独立执行：

1. 每天请求一次热榜并提前抓取、缓存正文。
2. 用户请求只读取本地有效热榜快照。
3. 有效热榜关键词匹配达到 5 条，不调用搜索。
4. 少于 5 条，调用该平台搜索，最多检查 60 条去重候选。
5. 正式结果最多返回 20 条。
6. 官方热榜匹配和搜索合格文章放在同一平台候选池统一计算热度分。
7. 最终排序不直接使用官方榜单顺序或搜索返回顺序。
8. 没有完整正文或没有可验证热点证据的文章必须淘汰。
9. 不允许摘要、标题或生成内容代替正文。
10. 不使用长期 Cookie、登录会话或验证码绕过。

正文门槛已由用户修订为分级规则：

- 平台结构化正文或明确正文容器：至少 80 个有效字符。
- GNE 通用兜底正文：至少 200 个有效字符。
- 两种来源都必须至少有 2 个真实段落或 3 个完整句子。
- 标题、摘要、重复摘要、标题与摘要拼接、页面导航、登录提示、评论区、
  页脚和重复框架不能通过。

热点排序：

- 指标先执行 `log1p`，再计算同平台候选池百分位。
- 缺失指标按零处理，不重新分配权重。
- 热点证据必须与真实官方榜单身份或正数公开互动指标一致。

## 5. 平台接口

新浪热榜：

```text
https://top.news.sina.com.cn/ws/GetTopDataList.php?js_var=data&top_cat=www_www_all_suda_suda&top_channel=news&top_order=DESC&top_show_num=50&top_time=today&top_type=day
```

新浪搜索：

```text
https://search.sina.com.cn/api/news?q=<keyword>&page=<page>
```

澎湃热榜：

```text
https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar
```

澎湃搜索：

```text
POST https://api.thepaper.cn/search/web/news
Client-Type: 1
Content-Type: application/json
```

网易正式热榜：

```text
https://gw.m.163.com/nc-main/api/v1/hqc/no-repeat-hot-list
```

不要把下面这个缺少热度指标的弱接口作为网易正式热榜：

```text
https://m.163.com/fe/api/hot/news/flow
```

网易搜索：

```text
https://www.163.com/search?keyword=<keyword>
```

## 6. 已完成工作

### 6.1 文档

```text
37e42f0 docs: design cached news providers
0fe23ef docs: plan cached news providers
088e20a docs: validate short native news bodies
```

### 6.2 Task 1：资格契约与正文硬校验

```text
590276b feat: enforce full-text qualification contracts
121d4fd fix: harden article qualification validation
```

Task 1 新增或修改：

- `src/heated_topics_v3/contracts.py`
- `src/heated_topics_v3/content.py`
- `tests/test_content.py`
- `tests/test_contracts.py`
- `pyproject.toml`
- `uv.lock`

已实现：

- frozen `HeatEvidence`
- frozen `ContentValidation`
- frozen `QualifiedArticle`
- 不可绕过的热点证据一致性校验
- 原生正文 80 字、GNE 200 字分级门槛
- 标题、摘要和重复摘要降级识别
- 真实 block 边界提取，内联节点不会被误算成多个段落
- ignored DOM 子树深度正确维护，不泄漏正文容器外页面文本
- `gne>=0.4.3` 依赖

Task 1 最终验证：

```text
focused: 21 passed
full suite: 179 passed
```

Task 1 独立复审：

```text
Spec Compliance: approved
Critical: none
Important: none
Minor: none
Task quality: Approved
```

曾出现一次既有 Windows 文件锁并发测试的瞬时 `PermissionError`。该单测随后
连续通过 5 次，最终完整测试也通过。若以后再次出现，应按独立 flaky 问题调查，
不要把它误判为 Task 1 正文校验回归。

## 7. 当前暂停点

下一项是：

```text
Task 2: Add Dynamic Heat Floors and Stable Platform Ranking
```

Task 2 brief：

```text
.superpowers/sdd/task-2-brief.md
```

Task 2 基线：

```text
121d4fd
```

Task 2 子代理在开始后很快被中断，没有产生文件改动、暂存内容或提交。不要把
Task 2 视为已完成，直接从 brief 重新开始即可。

Task 2 的重点约束：

- 使用 TDD，先证明 `heated_topics_v3.heat` 不存在或行为失败。
- 正数样本的第 25 百分位作为动态门槛。
- 正数样本不足时使用配置化绝对门槛。
- 阅读、评论和点赞不能直接相加。
- 使用 `log1p` 和平台内百分位。
- 缺失指标为零且不重新分配权重。
- 排序必须完全确定性，不得使用 Python `hash()`。
- 完成后运行 focused tests 和一次完整测试，提交并独立审查。

## 8. 尚未完成工作

以下任务都尚未开始：

1. Task 2：动态热度门槛与稳定排序。
2. Task 3：有效快照、淘汰记录、搜索缓存、active snapshot 和隔离的
   `news_user_results` 存储。
3. Task 4：新浪新闻 Provider。
4. Task 5：澎湃新闻 Provider。
5. Task 6：网易新闻 Provider。
6. Task 7：通用每日采集、完整正文抓取和有效快照原子发布。
7. Task 8：少于 5 条时的条件搜索、最多 60 条候选、平台内去重和搜索缓存。
8. Task 9：三平台推荐工作流、`collect-news` / `generate-news` CLI 和 README。
9. Task 10：真实匿名 smoke test、凭据扫描和实施报告。
10. 全分支最终代码审查与开发分支收尾。

每个任务的完整文件、接口、测试、命令和提交边界都在实施计划中，不应只依赖本
handoff 的摘要重新设计。

## 9. 推荐恢复步骤

进入正确工作树：

```powershell
Set-Location 'E:\.code\My\heatedTopics\heatedTopics\.worktrees\cached-news-providers'
```

确认状态：

```powershell
git status --short --branch
git log --oneline -8
Get-Content -Raw .superpowers/sdd/progress.md
```

重新同步并验证当前基线：

```powershell
uv sync
uv run pytest -q
```

预期当前完整测试：

```text
179 passed
```

然后完整读取：

```text
docs/superpowers/plans/2026-07-23-cached-news-providers.md
.superpowers/sdd/task-2-brief.md
```

如果继续使用 Subagent-Driven Development：

1. 每次只派一个实现子代理。
2. 实现代理必须使用 `superpowers:test-driven-development`。
3. 每项完成后使用该任务开始前的 base SHA 生成 review package。
4. 再派独立 reviewer，同时检查 spec compliance 和 task quality。
5. Critical/Important 必须修复并复审。
6. 审查干净后才更新 `.superpowers/sdd/progress.md` 并进入下一任务。
7. 所有任务完成后再做一次全分支 review。

## 10. 可直接交给接手 Agent 的提示

```text
请接手 feature/cached-news-providers。

只在以下隔离工作树工作：
E:\.code\My\heatedTopics\heatedTopics\.worktrees\cached-news-providers

先读取：
1. docs/handoffs/2026-07-23-cached-news-providers-handoff.md
2. docs/superpowers/specs/2026-07-23-sina-thepaper-netease-provider-design.md
3. docs/superpowers/plans/2026-07-23-cached-news-providers.md
4. .superpowers/sdd/progress.md
5. .superpowers/sdd/task-2-brief.md

当前 HEAD 应为 121d4fd，工作树应干净，当前测试应为 179 passed。
Task 1 已完成并通过双重审查。Task 2 及以后尚未完成。

从 Task 2 开始，严格按计划使用 TDD，并在每个任务后进行独立的规格符合性和
代码质量审查。不要在 V3 主工作区实现，不要重做 Task 1，不要使用弱网易热榜
接口，不要把摘要/标题当正文，不要把搜索排名当热点证据。
```
