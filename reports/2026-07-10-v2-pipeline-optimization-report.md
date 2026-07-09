# V2 搜索发现流程优化报告

**日期**：2026-07-10
**版本**：V2 分支

---

## 一、本次优化的背景

V2 分支上线后，测试发现以下问题需要解决：

1. **英文内容混入国内热点**：Tavily 搜索源返回英文文章，污染了中文创作者的内容池
2. **小红书/微博平台关键词无法触达**：suffix 列表共 11 项，但代码只取前 3 项，平台关键词排在末尾，永远不会被使用
3. **内容复用不足**：Enrich 阶段未对英文内容做翻译处理

---

## 二、具体改动

### 2.1 搜索 Query 平台关键词优先

**文件**：`src/search_discovery/domestic_sources.py`

将 `"小红书 微博 热门 爆款"` 移到 `CONTENT_MODE_QUERY_SUFFIXES` 第 1 位，并加入 `FALLBACK_QUERY_SUFFIXIXES`：

```python
CONTENT_MODE_QUERY_SUFFIXES = [
    "小红书 微博 热门 爆款",  # 移至第1位
    "融资 发布 重大更新",
    ...
]
```

### 2.2 扩大 Query Suffix 截取范围

**文件**：`src/search_discovery/domestic_sources.py`

`suffixes[:3]` → `suffixes[:6]`，使前 6 个角度都能被实际使用，平台关键词能确保被搜索。

### 2.3 英文内容自动翻译为中文

**两处修改**：

- **`src/search_discovery/enrich.py`**：在 Enrich 阶段，对英文 title/snippet/content 调用 Google Translate API 翻译为中文
- **`src/search_discovery/discovery.py`**：在 Cluster 阶段前，对英文搜索结果（title + snippet）先翻译再进行话题质量过滤

翻译函数使用 Google Translate 公开接口（`translate.googleapis.com/translate_a/single`），无需 API Key：

```python
def _translate_en_to_zh(text: str) -> str:
    if _has_chinese(text):
        return text  # 已有中文直接返回
    # 调用 Google Translate 译为中文
    ...
```

### 2.4 放宽近期英文结果的中文信号检查

**文件**：`src/search_discovery/topic_quality.py`

对于 ≤30 天内的英文结果，放宽 `_has_chinese_signal` 检查——热门话题常在英文媒体先出现，国内创作者仍可参考使用。

```python
is_recent = _is_recent_result(result, max_age_days=30)
if not is_recent and not _has_chinese_signal(...):
    return None  # 非近期内容仍需中文信号
```

同时新增 `_is_recent_result()` 和 `_parse_datetime()` 辅助函数，复用了 `discovery.py` 中已有的日期解析逻辑。

---

## 三、测试结果

**测试 Profile**：`persona_0013`（从奶茶、咖啡、商场和新品牌切入消费趋势观察）

| 指标 | 改动前 | 改动后 |
|------|--------|--------|
| 话题总数 | 0（原 pipeline 无话题） | 19 |
| 平台关键词覆盖 | ❌ 未出现在 Query 列表 | ✅ 第一个 Query 角度 |
| 英文标题 | ❌ 原文保留 | ✅ 中文标题（如"巴西 Natura 第二季度收入同比下降 9% 至 10%"） |
| 内容摘要 | ❌ 英文片段 | ✅ 翻译后中文 |

**样本输出（优先级高）**：

1. 巴西 Natura 第二季度收入同比下降 9% 至 10% — 时尚商业评论
2. 网上消费飙升，香港 5 月份零售额增长 7.9% — 亚洲商业评论
3. LV 不能因使用中国图案而起诉商标侵权（微博话题 3300 万浏览）

---

## 四、仍存在的限制

1. **翻译质量**：Google Translate 对含 Markdown 残留符号的片段翻译效果一般，后续可考虑 Jina Reader 提取纯内容后再翻译
2. **中文数据源缺失时依赖英文翻译**：国内新闻源（news_api_cn、TianAPI）对部分关键词近期无数据，英文结果填补了空缺但相关性不如中文源
3. **翻译延迟**：每次翻译为一次 HTTP 请求，后续可考虑批量翻译或本地模型

---

## 五、下一步计划

1. 接入 Jina Reader 提取页面正文后再翻译，提升翻译质量
2. 对 persona_profiles.jsonl 中的 21 个 Creator Profile 批量运行，评估各 Profile 的话题产出质量
3. 完善"高可信话题"判断标准（当前为 0，因单一来源限制）
