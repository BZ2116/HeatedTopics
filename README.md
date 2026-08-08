# HeatedTopics 推荐项目

这是一个面向内容创作者的文章推荐模块。输入用户的一级赛道、二级赛道和人设，项目从多个平台的热榜、搜索结果以及最近 30 天数据中获取候选内容，抓取正文、清洗无效内容并进行相关性排序，最后输出推荐文章。

项目当前最重要的原则是：推荐流程和调用方式分离。终端命令用于本地调试，其他项目接入时应直接调用 Python 接口。

## 一、整体流程

```text
用户输入
  │
  ├─ 用户关键词解析
  ├─ V3 平台热榜读取
  ├─ 热榜不足时调用平台搜索
  ├─ last30days 最近 30 天数据
  ├─ 正文抓取与来源识别
  ├─ 文章清洗和相关性保护
  └─ 推荐排序与 JSON 输出
```

当前推荐数据源包括 V3 热榜平台和 last30days 平台。热榜按日期缓存，同一天内不同用户和同一用户的多次调用不会重复抓取同一份热榜。

## 二、安装和配置

项目使用 `uv` 管理 Python 环境：

```powershell
uv sync
```

复制 `.env.example` 为 `.env`，配置必要的模型和平台信息：

```env
OPENBILICLAW_LLM_API_KEY=你的模型API_KEY
ZHIHU_COOKIE=你的知乎Cookie
```

正文和搜索能力依赖各平台的网络可访问性。使用关键词提取和相关性排序时，还需要保证 Ollama 正常运行，并准备配置文件中的 embedding 模型，例如：

```powershell
ollama pull bge-m3
```

`last30days` 是外部数据项目，需要通过 `--last30days-cli-path` 指向它的脚本。

## 三、终端运行方式

### 1. 准备用户 Excel

Excel 至少包含以下字段：

```text
user_id | track_1 | track_2 | persona
```

其中：

- `user_id`：外部系统中的用户 ID；
- `track_1`：一级赛道；
- `track_2`：二级赛道；
- `persona`：用户人设描述。

### 2. 执行推荐

```powershell
uv run python -m heated_topics_v3.openbiliclaw_integration.cli `
  --users-excel data/users.xlsx `
  --output-dir data/run_20260808 `
  --source both `
  --last30days-cli-path E:\.code\My\last30days-skill-cn\scripts\last30days.py `
  --last30days-days 30 `
  --last30days-max-queries 3 `
  --max-parallel 3 `
  --limit 15
```

说明：

- `--source both`：同时使用 V3 热榜和 last30days；
- `--limit 15`：最多输出 15 篇，默认也是 15 篇；
- `--max-parallel 3`：最多同时处理 3 个用户；
- `--output-dir` 应该直接指向当天目录，例如 `data/run_20260808`。

退出码：`0` 表示全部成功，`1` 表示部分用户失败，`2` 表示参数或环境配置错误，`4` 表示整体执行错误。

## 四、推荐输出目录

```text
data/run_20260808/
├── hot_cache/                         # 当天共享热榜缓存
├── daily_summary/                     # 热榜总结功能的输出
└── u_001/
    ├── keyword_cache/                 # 用户关键词缓存
    ├── hard_cache/                     # 用户级推荐运行缓存
    └── round_001/                      # 本次调用
        ├── input/
        │   └── input.json
        └── outputs/
            ├── recommended/           # 最终推荐文章
            ├── search/                # 全部候选文章
            │   ├── hot/               # 热榜候选，按平台划分
            │   └── search/            # 搜索候选，按平台划分
            └── text/                  # 推荐正文文本
```

同一个用户再次调用会生成 `round_002`，不会覆盖之前结果。每篇文章的 JSON 至少包含标题、来源和正文；作者、发布时间、阅读量、点赞量、评论量存在时一并保存。

## 五、给其他项目调用

核心接口位于：

```text
src/heated_topics_v3/openbiliclaw_integration/service.py
```

单用户调用：

```python
from heated_topics_v3.openbiliclaw_integration.service import recommend_user

result = recommend_user(
    user_id="u_001",
    track_1="旅行攻略",
    track_2="穷游周末",
    persona="预算敏感型旅行爱好者，专做两天一夜短途攻略。",
    run_dir="data/run_20260808",
    limit=15,
    source="both",
    last30days_config={
        "cli_path": r"E:\.code\My\last30days-skill-cn\scripts\last30days.py",
        "days": 30,
        "fetch_bodies": True,
    },
)
```

返回值包含 `recommendations`、`searched_articles`、`user_id`、`run_dir` 和本次 `round_dir`。外部项目可以直接读取返回值，也可以读取 `round_dir` 下的标准 JSON 文件。

## 六、并发调用

如果外部项目会同时触发多个用户，使用 `RecommendationService`：

```python
from heated_topics_v3.openbiliclaw_integration.service import RecommendationService

service = RecommendationService(max_concurrency=3)
result = await service.recommend_user(
    user_id="u_001",
    track_1="旅行攻略",
    track_2="穷游周末",
    persona="预算敏感型旅行爱好者。",
    run_dir="data/run_20260808",
    source="both",
)
```

并发规则：

1. 全局并发最多 3 个用户；
2. 同一个用户同时触发时串行执行，避免竞争用户缓存和轮次目录；
3. 不同用户互不影响，一个用户失败不会取消其他用户；
4. 热榜缓存位于日期层，由所有用户共享。

## 七、当天热榜总结

推荐流程之外，项目预留了独立的热榜总结接口：

```python
from heated_topics_v3.openbiliclaw_integration.service import summarize_daily_hot

summary = summarize_daily_hot(run_dir="data/run_20260808")
```

它读取当天 `hot_cache` 中的全部热榜数据，输出：

```text
data/run_20260808/daily_summary/summary.json
```

后续可以在这个接口外层接入 LLM 总结、消息推送、飞书或企业微信，不需要改动用户推荐流程。

## 八、测试

运行核心测试：

```powershell
uv run pytest tests/openbiliclaw_integration tests/providers -q
```

服务接口测试覆盖：

- 单用户标准目录输出；
- 用户级 round 生成；
- 最大并发数限制；
- 热榜缓存读取与每日总结输出。

## 九、项目结构

```text
src/heated_topics_v3/openbiliclaw_integration/
├── cli.py                    # 终端参数解析和批量入口
├── service.py               # 对外稳定业务接口
├── recommender.py            # 候选获取、正文处理和推荐排序
├── candidate_adapter.py     # 平台数据统一转换
├── body_enricher.py         # 正文抓取和来源识别
├── keyword_extractor.py     # 用户关键词提取与缓存
├── report_writer.py         # 标准目录和 JSON 输出
├── user_profile.py          # 用户输入校验
└── runtime.py               # OpenBiliClaw、LLM、环境检查
```

接手项目时，建议先阅读本 README，再从 `service.py` 的 `recommend_user()` 开始跟踪；终端 CLI 只负责输入转换和调用，不应成为其他项目的直接依赖。
