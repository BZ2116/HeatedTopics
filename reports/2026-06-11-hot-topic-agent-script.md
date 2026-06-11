# 国内热点话题 Agent 系统调研汇报讲稿

> 建议时长：8-12 分钟  
> 使用方式：配合《国内热点话题 Agent 系统调研与实施建议汇报》逐页讲解。

## 开场

各位老师/同学好，我这次汇报的主题是：如何基于目前市场上的 Skills、Agents、MCP 工具和网页抓取工具，构建一个“国内热点话题收集与详情整理系统”。

这个系统要解决的问题不是简单列出热搜标题，而是每天或每隔几小时自动收集国内热点，并进一步整理出：

```text
发生了什么
为什么火
出现在哪些平台
排名和热度如何
有哪些来源
是否需要继续跟踪
后续观察点是什么
```

我的结论先放在前面：目前没有一个单一现成工具可以完整完成这个目标。更合理的做法是把系统拆成几层：热点发现、详情读取、LLM 结构化整理、定时任务、历史存储，以及最后的 Skill 或 MCP 封装。

## 第一部分：市场现状

目前市场上的相关工具大致可以分成五类。

第一类是 Skill。Skill 的作用是把一类任务的经验、脚本、模板和说明封装起来，让 Agent 在遇到类似任务时可以复用。比如 Claude Agent Skills、OpenClaw 每日热榜 Skill、LobeHub 上的每日热榜 Skill。这类工具适合沉淀固定流程，比如热点查询、报告生成、文档处理。

第二类是 Agent SDK 或 Agent Framework。代表工具包括 OpenAI Agents SDK、LangGraph、CrewAI、Microsoft Agent Framework。这类工具主要解决的是多步任务执行、工具调用、状态管理和复杂流程编排。它们适合长期稳定版，但对明早 Demo 来说，不应该一开始就上太复杂。

第三类是 MCP Server。MCP 可以理解为一种让模型调用外部工具的通用协议。比如 NewsNow MCP Server、HotNews MCP Server，都能把热点新闻能力暴露给 Agent。长期来看，我认为应该自建一个 Hot Topic MCP Server，把获取热榜、读取详情、查询历史、生成简报这些能力都封装成标准工具。

第四类是 Workflow 平台，比如 Dify、Coze、n8n、Zapier Agents。这类工具的优势是快速搭建可视化流程，连接模型、API、定时任务和通知渠道。它们适合做 Demo 或内部自动化，尤其是 n8n 很适合做定时采集和飞书、邮件推送。

第五类是底层数据和抓取工具。比如 DailyHotApi 负责获取国内平台热榜，RSSHub 负责长期订阅信息源，Jina Reader 负责把网页转成 LLM 可读 Markdown，Firecrawl 和 Crawl4AI 则更适合长期稳定抓取。

可以用一句话概括市场现状：

```text
Skill 负责经验复用，
MCP 负责工具接入，
Agent 负责调度决策，
Workflow 负责自动化落地，
数据和抓取工具负责提供原材料。
```

## 第二部分：各类工具特点

先看 Skill 类工具。

Claude Agent Skills 更像是官方定义的能力封装方式，适合把“热点分析流程”沉淀成一个可复用技能。OpenClaw 每日热榜 Skill 更贴近我们的目标，因为它基于 DailyHotApi，可以获取多个平台热榜。LobeHub 上的每日热榜 Skill 也能作为市场已有形态参考。

但这里有一个关键判断：这些 Skill 大多解决的是“发现热点”，不是“理解热点”。它们通常能提供标题、排名、热度和链接，但不保证能稳定输出事件背景、为什么火、争议点和后续观察。

再看 Agent Framework。

OpenAI Agents SDK 和 LangGraph 更适合长期工程化。它们可以管理多步流程，例如先获取热榜，再筛选重点话题，再调用网页读取工具，再生成热点卡片，最后写入数据库。CrewAI 强调多 Agent 协作，但对于这个项目，核心瓶颈不是 Agent 数量，而是数据链路是否稳定。

所以我的判断是：热点系统不应该为了展示 Agent 而堆多 Agent。真正重要的是把数据采集、详情补全、去重聚类和输出格式做好。

再看 MCP。

NewsNow MCP Server 和 HotNews MCP Server 说明，市场上已经有把热点信息封装成 MCP 工具的趋势。它们适合做问答式 Demo，比如用户问“今天有哪些热点”，Agent 调用 MCP 工具返回热点列表。

但长期稳定版不能只停留在热点列表。更合理的是自建 MCP Server，提供几个明确工具：

```text
get_hot_list
read_topic_detail
search_related_sources
get_topic_history
generate_daily_digest
```

这样无论后续接 Claude、OpenAI Agent、Cursor、Dify，还是其他 MCP Host，都可以复用同一套热点能力。

最后是数据和抓取工具。

DailyHotApi 是 Demo 版最核心的数据入口，因为它能聚合国内多个平台的热榜，接入成本低。Jina Reader 适合快速把网页 URL 转成 Markdown，给 LLM 做摘要和结构化分析。RSSHub 更适合长期订阅新闻、科技、论坛、博客等稳定信息源。Firecrawl 和 Crawl4AI 则适合长期版处理更复杂网页。

## 第三部分：Demo 版实施方案

Demo 版的目标不是做完整系统，而是跑通一条最短链路：

```text
获取热榜
→ 选择重点话题
→ 读取详情
→ 生成热点详情卡
→ 输出当前热点简报
```

我推荐 Demo 版使用：

```text
DailyHotApi + Jina Reader + LLM + Markdown
```

DailyHotApi 负责获取热榜。建议先覆盖六个平台：微博、百度、知乎、B站、36氪、IT之家。如果时间紧，可以降级为微博、百度、知乎、36氪四个平台。

Jina Reader 负责读取详情。它的好处是接入很轻，可以把 URL 转成比较适合 LLM 读取的 Markdown。对于抓不到的链接，可以用标题去搜索相关新闻页面作为兜底。

LLM 负责把原始信息整理成热点卡片。每张卡片至少包含：

```text
标题
来源平台
当前排名
一句话概括
事件背景
为什么火
相关主体
来源链接
是否继续跟踪
置信度
```

最终输出 Markdown 文件，方便展示，也方便后续转成 PDF 或网页。

Demo 版的重点不是覆盖所有平台，而是证明系统不只是列标题，而是能生成具体的热点详情卡和简报。

## 第四部分：长期稳定版实施方案

长期稳定版要解决三个问题：

第一，持续采集。系统需要每 1 到 3 小时自动运行，而不是手动触发。

第二，历史追踪。系统需要知道一个话题什么时候第一次出现、在哪些平台扩散、最高排名是多少、持续了多久。

第三，工具化封装。后续应该让 Agent 可以随时查询热点状态，而不是每次重新写脚本。

所以长期版推荐方案是：

```text
DailyHotApi + RSSHub + Jina Reader + Firecrawl/Crawl4AI
+ SQLite/Postgres
+ cron/n8n
+ OpenAI Agents SDK 或 LangGraph
+ 自建 Hot Topic MCP Server
+ 自定义 Hot Topic Skill
```

其中，DailyHotApi 继续作为热榜入口；RSSHub 补充长期稳定的信息源；Jina Reader 作为轻量详情读取工具；Firecrawl 或 Crawl4AI 作为复杂网页抓取兜底；数据库用来保存历史；cron 或 n8n 用来定时运行；OpenAI Agents SDK 或 LangGraph 用来做流程编排；MCP Server 和 Skill 用来封装能力。

长期版最终应该具备这些能力：

```text
多源采集
跨平台话题合并
详情补全
历史趋势追踪
自动日报
关键词告警
Agent 工具调用
```

## 第五部分：风险与规避

这个项目最大的风险不是模型，而是数据源。

国内平台普遍存在动态渲染、登录态、反爬和接口变化问题。所以 Demo 阶段不建议优先抓小红书、抖音、快手详情页。它们可以作为后续扩展，但不适合作为第一阶段核心链路。

第二个风险是热榜只有标题，信息不足。解决方式是增加详情读取和搜索补充。如果原始链接抓不到，就用标题去找更可读的新闻源。

第三个风险是 LLM 幻觉。解决方式是要求所有结论尽量绑定来源链接，并给每张热点卡片加置信度。信息不足时不要强行编背景，而是标记为低置信度。

第四个风险是系统一开始设计过重。我的建议是先用简单脚本跑通 Demo，再逐步加数据库、定时任务、MCP 和 Skill。

## 结尾

总结一下，最终建议分两阶段实施。

Demo 版：

```text
DailyHotApi + Jina Reader + LLM + Markdown
```

目标是快速跑通“热榜到热点卡片再到简报”的完整链路。

长期稳定版：

```text
DailyHotApi + RSSHub + Jina Reader + Firecrawl/Crawl4AI
+ 数据库
+ 定时任务
+ Agent 编排
+ MCP Server
+ 自定义 Skill
```

目标是持续运行、历史追踪、自动日报和 Agent 工具化调用。

最后一个判断是：这个系统不要做成“多 Agent 展示项目”，而应该做成“稳定的数据与分析管道”。Agent 是调度层，数据质量和详情补全才是核心。

我的汇报到这里，谢谢。
