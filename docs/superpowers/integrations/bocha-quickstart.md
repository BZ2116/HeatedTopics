# Bocha AI Search Quickstart

## 获取 API Key

1. 访问 https://bochaai.com 注册并登录
2. 进入 **控制台** → **API Key 管理**
3. 点击 **创建 API Key**，选择免费档位
4. 复制生成的 key（以 `sk-` 开头），关闭弹窗后无法再次查看完整 key

## 配置 .env

```
BOCHA_API_KEY=sk-your_key_here
```

免费档位有月度配额限制，注意控制调用频率。

## 验证

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

查看 `data/search_discovery/raw/search_results.jsonl`，应能看到 `source_id: "news_api_cn"` 的记录，对应中文资讯类结果。

来源：https://bochaai.com