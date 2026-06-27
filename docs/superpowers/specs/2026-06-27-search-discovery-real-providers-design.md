# 搜索发现层接入真实数据源设计方案

## 目标

把 `src/search_discovery/` 当前只用 `MockProvider` 的搜索链路替换为可调用的真实数据源，保留 mock 作为开发期兜底。

完成本设计后：

- 给定一个 CreatorProfile，`run_discovery_command()` 能用真实 API 召回候选话题。
- 没配置 API key 的源自动 fallback 到 `MockProvider(rows=[])`，而不是塞假数据。
- 真实 provider 运行时失败（401 / 429 / 5xx / 超时 / 解析错）有统一的归一化处理和重试策略。
- 失败结果仍写入 `data/search_discovery/raw/search_results.jsonl`，方便调试，但不进入 topic 排序。

## 非目标

- 不引入异步并发。第一版用同步串行调用足够，单 profile 4 个源 × 6 个 query × 1 个响应即可，后续按需再 async。
- 不做结果缓存层。开发期重跑成本可控，长期再做。
- 不接入付费 SERP 服务（SerpAPI、DataForSEO、SearchAPI）。第一版只用免费档 + 百度千帆免费额度。
- 不抓取登录态平台（小红书、微信公众号）。
- 不重写 `discovery.py` 的聚类逻辑或 `ranking.py` 的评分公式。
- 不动 `config.py` 里的 8 个 source ID 和权重表，映射在 provider 层完成。

## 接入源

| 现有 source ID | 真实实现 | 服务 | 鉴权 | 免费档 | 角色 |
| --- | --- | --- | --- | --- | --- |
| `github_search` | `GitHubSearchProvider` | `api.github.com/search/repositories` | Token（可选） | 60/h 无 token / 5000/h 有 token | tech_project 主力 |
| `baidu_qianfan_search` | `QianfanSearchProvider` | 百度智能云千帆 AppBuilder 搜索增强 | AK + SK | 申请后有免费额度 | 中文权威搜索 |
| `news_api_cn` | `BochaSearchProvider` | `bochaai.com` AI 搜索 API | API Key | 注册领免费 key | 中文资讯 / 通用搜索 |
| `juejin_content` | `BailianWebSearchProvider` | 阿里云百炼 `enable_search` / Web Search | API Key | 注册有免费额度 | 通用补充 |

四个 provider 都用 `BaseHTTPSearchProvider` 作为基类，统一处理 HTTP 调用、限流、重试、错误归一化。

## 架构

```text
                ┌──────────────────────────┐
                │ BaseHTTPSearchProvider   │
                │  - httpx.Client           │
                │  - 令牌桶限流 (rpm)       │
                │  - 指数退避重试 (最多 3)  │
                │  - 错误归一化             │
                │  - from_env() 类方法      │
                └─────────┬────────────────┘
                          │
        ┌─────────────────┼──────────────────┬──────────────────┐
        │                 │                  │                  │
GitHubSearchProvider  BochaSearchProvider BailianWebSearchProvider QianfanSearchProvider
   (GitHub API)        (博查 AI 搜索)        (阿里云百炼)              (百度千帆)
```

### BaseHTTPSearchProvider 职责

```python
class BaseHTTPSearchProvider:
    source_id: str
    rpm_limit: int = 60           # 子类可覆盖
    timeout_seconds: float = 10.0
    max_retries: int = 3

    def search_rows(self, query: str) -> list[dict]: ...

    # 子类实现
    def _build_request(self, query: str) -> httpx.Request: ...
    def _parse_response(self, response: httpx.Response, query: str) -> list[dict]: ...
    def _auth_headers(self) -> dict[str, str]: ...

    # 错误处理
    def _is_retryable_status(self, status: int) -> bool: ...
    def _execute(self, query: str) -> list[SearchResult]:
        # 1) 令牌桶 acquire
        # 2) 发送请求
        # 3) 5xx / 429 / 超时 -> 指数退避重试
        # 4) 401/403/解析错 -> 不重试, 标 fetch_status
```

### 子类差异点

| Provider | 鉴权位置 | 请求体 | 响应字段映射 | 特殊处理 |
| --- | --- | --- | --- | --- |
| GitHubSearchProvider | `Authorization: Bearer` header | GET `/search/repositories?q={query}&sort=stars` | `items[].full_name` → title, `items[].html_url` → url, `items[].description` → snippet | 带 `Accept: application/vnd.github+json` 头，per_page=10 |
| BochaSearchProvider | `Authorization: Bearer` header | POST `{endpoint}` JSON `{query, summary: true, count: 10}` | `data.webPages.value[]` → 结果列表 | 中文 URL 需要 urlencode |
| BailianWebSearchProvider | `Authorization: Bearer` header | POST `{endpoint}` JSON `{query}` | 响应 JSON 按字段映射 | 走 DashScope 协议 |
| QianfanSearchProvider | `?access_token=` query param (OAuth 拿 token) | POST 千帆 AppBuilder 搜索接口 | 响应 JSON 按字段映射 | 需要先 `access_token` 接口换 token，token 缓存到实例属性 |

### MockProvider 保留

`providers.py` 里的 `MockProvider` 不删。当某个真实 provider 的 `from_env()` 返回 None（缺 key），CLI 装配时用 `MockProvider(source_id, rows=[])` 顶替——返回空结果而不是假数据。

```python
def _build_provider(cls) -> SearchProvider:
    real = cls.from_env()
    if real is not None:
        return real
    return MockProvider(cls.source_id, rows=[])  # 无 key -> 空 mock
```

## 配置策略

### 依赖

`pyproject.toml` 新增：

```toml
dependencies = [
    "playwright>=1.59.0",
    "httpx>=0.27.0",       # HTTP 客户端
    "python-dotenv>=1.0",  # .env 加载
]
```

### `.env.example`（进 commit）

```bash
# GitHub Search（可选，无 token 也能跑，限速 60/h）
GITHUB_TOKEN=

# 博查 AI 搜索（https://bochaai.com 注册）
BOCHA_API_KEY=

# 阿里云百炼 Web Search（阿里云控制台开通）
BAILIAN_API_KEY=

# 百度智能云千帆（控制台创建应用）
QIANFAN_API_KEY=
QIANFAN_SECRET_KEY=
```

`.env` 进 `.gitignore`。

### 加载流程

1. `cli.py` 入口调 `load_dotenv()` 从项目根目录读 `.env`。
2. 每个真实 provider 通过 `from_env()` 试初始化。
3. 返回 None → CLI 用 `MockProvider(source_id, rows=[])` 顶替。
4. 测试时直接 `monkeypatch.setenv()` 注入，不需要碰文件系统。

## 错误处理

| 场景 | 重试 | fetch_status | error_type |
| --- | --- | --- | --- |
| 无 key（`from_env()` 返回 None） | 不调用 | `mock_unavailable` | `missing_key` |
| 401 / 403 | 不重试 | `auth_failed` | `unauthorized` / `forbidden` |
| 429 限流 | 按 `Retry-After` 头等待，最多 3 次 | 成功后 `ok`，否则 `upstream_failed` | `rate_limited` |
| 5xx | 指数退避 1s → 2s → 4s，最多 3 次 | 成功后 `ok`，否则 `upstream_failed` | `server_error` |
| 连接超时 / 读超时 | 指数退避 3 次 | 成功后 `ok`，否则 `upstream_failed` | `timeout` |
| JSON 解析错 | 不重试 | `parse_failed` | `invalid_json` |
| 业务码非 0（如千帆 errno） | 不重试 | `upstream_failed` | 业务错误码 |

### 关键原则

1. 重试只在 provider 内部，CLI 看到的就是 `fetch_status` 字段，不需要上层处理。
2. 失败结果**仍然写入** `data/search_discovery/raw/search_results.jsonl`，便于排查。
3. **mock fallback 仅限"无 key"场景**——key 存在但调用失败时不 fallback，避免假数据混入。
4. 失败结果在 `cluster_results()` 里被 drop，不进入 topic 排序。

### 限流

基类用简单令牌桶，60 RPM 默认值（覆盖所有 4 个源的免费档）。子类可覆盖 `rpm_limit` 类属性。开发期不需要精细限流，60 RPM 足够。

## 测试

### 单元测试（`tests/search_discovery/`）

每个真实 provider 一个文件 `test_<provider>.py`，结构统一：

| 用例 | 覆盖点 |
| --- | --- |
| `test_<provider>_success` | 正常响应 → SearchResult 字段映射正确 |
| `test_<provider>_auth_failed` | mock 401 → `fetch_status="auth_failed"`，不重试 |
| `test_<provider>_retry_on_5xx` | mock 2 次 500 + 1 次 200 → 调用 3 次，最终成功 |
| `test_<provider>_retry_exhausted` | mock 一直 500 → `fetch_status="upstream_failed"` |
| `test_<provider>_rate_limit_429` | mock 429 带 Retry-After → 等候后重试 |
| `test_<provider>_from_env_missing_key` | 清空 `os.environ` → `from_env()` 返回 None |
| `test_<provider>_parse_failed` | mock 200 + 烂 JSON → `fetch_status="parse_failed"` |

mock 用 `httpx.MockTransport`，因为 provider 用 httpx，链路最短。

### 装配测试

`tests/search_discovery/test_registry_fallback.py`：

- `test_fallback_to_mock_when_no_key`：清空 env，跑 `run_discovery_command()`，断言 raw JSONL 里有 `fetch_status="mock_unavailable"` 的条目。
- `test_real_provider_used_when_key_present`：设 `GITHUB_TOKEN=fake`，断言 GitHub 走的是真实类（通过 `inspect.isclass(provider, GitHubSearchProvider)` 验证）。
- `test_failed_real_does_not_fallback`：mock 真实 provider 抛异常，断言没有 mock 数据混入最终 topic。

### 集成冒烟（手动）

每个 provider 给一段最小调用示例，文档写在 `docs/superpowers/integrations/<provider>-quickstart.md`。用户在本地填真 key 后跑：

```bash
python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

看 `reports/search_discovery/search_topic_recommendations.md` 不再是全 mock 克隆。

CI 不跑集成冒烟。

## 输出文件

复用现有路径，不新增：

```text
data/search_discovery/raw/search_results.jsonl
data/search_discovery/evidence/search_content_evidence.jsonl
data/search_discovery/processed/search_topic_index.json
reports/search_discovery/search_topic_recommendations.md
```

失败结果也进 `search_results.jsonl`，带 `fetch_status` 字段标记。

## 验证清单

- `pytest tests/search_discovery/ -q` 全绿。
- `python -m src.search_discovery.cli --profile ... --render-report` 跑通，退出码 0。
- raw JSONL 至少有 1-2 个 `fetch_status="ok"`（说明至少接到了一个真实源），其余是 `mock_unavailable` 或 `upstream_failed`。
- 报告里至少有一条非 mock 的真实候选话题（不同 provider 出不同结果）。
- `.env` 文件不进 commit（`git status` 看不到）。

## 实施顺序

1. 加 `httpx` 和 `python-dotenv` 依赖。
2. 写 `BaseHTTPSearchProvider` + 单元测试骨架。
3. 写 `GitHubSearchProvider`（最简单，先打通链路）。
4. 写 `BochaSearchProvider`（中文搜索代表）。
5. 写 `BailianWebSearchProvider`。
6. 写 `QianfanSearchProvider`（OAuth 拿 token 稍复杂，最后写）。
7. 改 `cli.py` 装配逻辑 + fallback。
8. 写每个 provider 的 quickstart 文档。

## 资料来源

- 博查 AI 搜索：https://bochaai.com/
- 阿里云百炼 Web Search：https://help.aliyun.com/zh/model-studio/developer-reference/web-search
- 百度智能云千帆：https://cloud.baidu.com/doc/qianfan/index
- 百度千帆 AppBuilder 搜索增强：https://ai.baidu.com/ai-doc/AppBuilder/pmaxd1hvy
- GitHub Search API：https://docs.github.com/rest/search
- httpx 文档：https://www.python-httpx.org/
- python-dotenv：https://pypi.org/project/python-dotenv/