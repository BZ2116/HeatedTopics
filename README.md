# heatedTopics

热点话题详情采集管道。从多个平台的热榜收集热点话题，去重后采集详情证据，生成 Markdown 报告。

## 快速开始

```bash
# 采集近期热点详情（默认 today 窗口）
make collect-recent-hot-details

# 指定窗口
python -m src.core_pipeline.run collect-recent-details --window last_7_days

# 查看输出
cat reports/recent_hot_topics_digest.md
```

## 命令

| 命令 | 说明 |
|------|------|
| `make test` | 运行所有测试 |
| `make collect-recent-hot-details` | 采集近期热点详情（today 窗口） |
| `python -m src.core_pipeline.run collect-recent-details --window today` | 采集今日热点 |
| `python -m src.core_pipeline.run collect-recent-details --window last_7_days` | 采集近7天热点 |
| `python -m src.core_pipeline.run paths` | 查看输出路径 |
| `python -m src.core_pipeline.run render-report` | 渲染报告 |
| `make check-sessions` | 检查浏览器登录状态 |
| `make login-weibo` | 登录微博 |
| `make login-xiaohongshu` | 登录小红书 |

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/raw/dailyhot_records.json` | 采集的热榜原始记录 |
| `data/processed/topic_clusters.json` | 去重后的话题集群 |
| `data/evidence/detail_evidence.json` | 详情证据数据 |
| `data/processed/topic_briefs.json` | 话题摘要 |
| `reports/recent_hot_topics_digest.md` | Markdown 格式的热点详情报告 |

## 支持的平台

### 热榜来源（core_discovery）
- `weibo` - 微博热搜
- `baidu` - 百度热搜
- `zhihu` - 知乎热榜
- `toutiao` - 头条热榜

### 详情采集
- **baidu** - 通过搜索结果采集详情（无需登录）
- **weibo** - 需要登录微博
- **xiaohongshu** - 需要登录小红书

## 架构

```
热榜采集 (dailyhot_client.py)
    ↓
话题去重 (recent_topics.py)
    ↓
详情采集 (detail_collector.py)
    ├── baidu 搜索
    ├── weibo 详情 (需登录)
    └── xiaohongshu 详情 (需登录)
    ↓
报告渲染 (report_renderer.py)
    ↓
Markdown 报告
```

## 数据类型

### HotRecord
热榜记录，包含平台、排名、热度值、标题等。

### DetailEvidence
详情证据，包含平台、来源方式、查询词、内容、URL 等。

## 目录结构

```
heatedTopics/
├── src/
│   ├── core_pipeline/       # 核心管道
│   │   ├── run.py           # CLI 入口
│   │   ├── dailyhot_client.py
│   │   ├── recent_topics.py
│   │   ├── detail_collector.py
│   │   ├── report_renderer.py
│   │   └── providers/       # 各平台详情采集
│   │       ├── baidu.py
│   │       ├── weibo.py
│   │       └── xiaohongshu.py
│   └── browser/             # 浏览器登录
├── tests/                   # 测试
├── data/                    # 数据输出
│   ├── raw/
│   ├── processed/
│   └── evidence/
└── reports/                 # 报告输出
```

## 配置

环境变量：
- `DAILYHOT_API_BASE` - DailyHotApi 服务地址（默认 `https://dailyhotapi.now.sh`）

## 依赖

- Python 3.10+
- 无需额外依赖（使用标准库）
- 详情采集需要浏览器登录（可选）
