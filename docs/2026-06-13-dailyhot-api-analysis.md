# DailyHotApi 接口采样结论

结论：这里应按 `DailyHotApi` 处理，不是 `DailyHop API`。当前本地源码共发现 56 个路由，本地 `http://localhost:6688` 实测默认接口成功 46 个、失败 10 个；补充采样 40 个参数变体，成功 36 个。它适合作为热点候选池，不适合单独承担事件背景、事实核验和正文采集。

采样数据已保存到 `data/2026-06-13-dailyhot-api-sample.json`。本次采样时间为 2026-06-13，线上 `https://api-hot.imsyy.top/all` 和 `https://dailyhot.imsyy.top/all` 在当前环境出现 SSL EOF 错误，因此正式采样使用本地 DailyHotApi 实例。

## 来源

- 项目源码：`tools/DailyHotApi/src/routes/`
- 本地接口：`http://localhost:6688/all`
- 官方仓库：https://github.com/imsyy/DailyHotApi
- 官方 README 示例接口域名：https://api-hot.imsyy.top

## 返回结构

默认 JSON 响应是统一外壳：

```json
{
  "code": 200,
  "name": "baidu",
  "title": "百度",
  "type": "热搜",
  "params": {},
  "link": "https://top.baidu.com/board",
  "total": 5,
  "updateTime": "2026-06-13 21:00:00",
  "fromCache": false,
  "data": []
}
```

`data[]` 的常见字段如下：

| 字段 | 含义 | 稳定性 |
| --- | --- | --- |
| `id` | 平台内条目标识或排名 | 高 |
| `title` | 热点标题 | 高 |
| `url` | PC 详情页或搜索页 | 高 |
| `mobileUrl` | 移动端链接 | 中 |
| `desc` | 摘要、简介或话题文本 | 中 |
| `hot` | 热度、阅读量、评论数或榜单分值 | 中 |
| `cover` | 封面图 | 中 |
| `author` | 作者或媒体来源 | 中 |
| `timestamp` | 发布时间或上榜时间，毫秒时间戳 | 中 |

GitHub 接口额外返回 `owner`、`repo`、`description`、`language`、`stars`、`forks`。历史上的今天接口额外有 `year`。

## 接口清单

### 默认采样成功

成功接口共 46 个：

`36kr`、`51cto`、`52pojie`、`acfun`、`baidu`、`bilibili`、`csdn`、`dgtle`、`douban-group`、`douban-movie`、`douyin`、`gameres`、`geekpark`、`genshin`、`github`、`guokr`、`hellogithub`、`history`、`honkai`、`hupu`、`huxiu`、`ifanr`、`ithome`、`ithome-xijiayi`、`jianshu`、`juejin`、`kuaishou`、`lol`、`miyoushe`、`netease-news`、`newsmth`、`ngabbs`、`qq-news`、`sina`、`sina-news`、`smzdm`、`starrail`、`thepaper`、`tieba`、`toutiao`、`weatheralarm`、`weibo`、`weread`、`yystv`、`zhihu`、`zhihu-daily`。

### 默认采样失败

失败接口共 10 个，均为本地 API 返回 HTTP 500：

`coolapk`、`earthquake`、`hackernews`、`hostloc`、`linuxdo`、`nodeseek`、`nytimes`、`producthunt`、`sspai`、`v2ex`。

这些失败不代表接口永久不可用，更可能是源站访问、RSS 解析、反爬、网络出口或当前依赖状态导致。Demo 版不要依赖它们做主链路。

## 参数接口

本次识别到的主要参数接口：

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `baidu` | `type=realtime/novel/movie/teleplay/car/game` | 热搜和垂类榜 |
| `bilibili` | `type=0/1/3/4/5/119/129/155/160/168/181/188` | 全站和分区排行榜 |
| `github` | `type=daily/weekly/monthly` | GitHub Trending 周期 |
| `sina-news` | `type=1..11` | 总排行、国内、国际、财经、科技等新闻分区 |
| `sina` | `type=all/hotcmnt/minivideo/ent/ai/auto/mother/fashion/travel/esg` | 新浪热榜分区 |
| `miyoushe` | `game=1..8`，`type=1/2/3` | 游戏分类和公告/活动/资讯 |
| `juejin` | `type` | 综合、后端、前端、AI、开发工具等 |
| `weread` | `type=rising/hot_search/newbook/general_novel_rising/all` | 微信读书榜单 |
| `weatheralarm` | `province=省份名称` | 按省份查询气象预警 |
| `36kr`、`52pojie`、`acfun`、`hupu`、`smzdm` | `type` 或 `range` | 平台内分类 |
| `history` | `month`、`day` | 指定日期 |

补充采样结果：`baidu`、`bilibili`、`github`、`sina-news`、`miyoushe`、`weread`、`weatheralarm` 关键变体可用；`nytimes` 和 `v2ex` 变体在当前本地 API 返回 HTTP 500。

## 项目优先级

### Demo 版

Demo 版建议只接高收益、低阻塞接口：

1. 主热点池：`weibo`、`baidu`、`zhihu`、`toutiao`、`sina-news`、`thepaper`、`qq-news`、`netease-news`。
2. 科技和 AI 选题池：`36kr`、`ithome`、`juejin`、`csdn`、`github`、`hellogithub`。
3. 内容平台辅助：`bilibili`、`douyin`、`kuaishou`，只做热度信号，不直接当事实来源。
4. 公共事件源：`weatheralarm` 可保留，但只用于区域突发事件提醒。

Demo 版不要强依赖 `coolapk`、`hackernews`、`hostloc`、`linuxdo`、`nodeseek`、`nytimes`、`producthunt`、`sspai`、`v2ex`，因为本次默认采样失败。

### 长期稳定版

长期稳定版应把 DailyHotApi 放在第一层召回，不做唯一事实源：

1. DailyHotApi 负责批量拿候选标题、热度、平台链接、发布时间。
2. 新闻源和搜索接口负责补事件背景、时间线、相关报道。
3. 微博、小红书等登录态平台只做“讨论侧信号”，采集前检查登录态。
4. 遇到验证码、滑块、登录失效、风控页时记录 `login_required`、`captcha_required` 或 `rate_limited`，停止对应平台采集。
5. 对失败接口做健康检查和降级，不影响主流程生成日报。

## 登录页和搜索页处理

结论：需要登录的平台不要绕过；搜索页只做入口，不做最终事实来源。

- 微博：DailyHotApi 已能给热搜标题和搜索页链接。详情采集应使用保存的浏览器登录态；未登录时提示执行登录初始化，不自动抓登录页。
- 小红书：DailyHotApi 当前没有小红书路由。长期版如果要接，必须走登录态浏览器搜索；未登录或出现风控时停止。
- 百度：`baidu` 接口给热搜标题、摘要、热度和搜索链接。后续可用标题搜索新闻源，但百度搜索结果本身只用于发现来源。
- B 站、抖音、快手：接口可给视频热度和链接，但正文价值有限，适合作为传播热度证据。
- 新闻源：`sina-news`、`thepaper`、`qq-news`、`netease-news` 更适合直接补事件事实。

## 采集建议

短期把 `src/demo_config.py` 的平台列表扩到 12 到 16 个即可，不要一次启用全部 56 个接口。推荐顺序：

```python
PLATFORMS = [
    "weibo",
    "baidu",
    "zhihu",
    "toutiao",
    "sina-news",
    "thepaper",
    "qq-news",
    "netease-news",
    "36kr",
    "ithome",
    "juejin",
    "csdn",
    "github",
    "hellogithub",
    "bilibili",
    "weatheralarm",
]
```

长期再把参数接口拆成独立 source，例如 `baidu:game`、`bilibili:188`、`github:weekly`，避免把垂类榜和综合热榜混在同一个权重池里。

