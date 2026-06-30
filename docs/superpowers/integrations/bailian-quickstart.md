# Aliyun Bailian Web Search Quickstart

## 获取 API Key

1. 访问 https://bailian.console.aliyun.com/ 并使用阿里云账号登录
2. 在模型广场开通 **Web Search** 能力（绑定到一个模型）
3. 进入左侧菜单 **API-KEY 管理**，点击 **创建我的 API-KEY**
4. 复制 key（以 `sk-` 开头），保存到本地

## 配置 .env

```
BAILIAN_API_KEY=sk-your_key_here
```

## 验证

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

查看 `data/search_discovery/raw/search_results.jsonl`，应能看到 `source_id: "juejin_content"` 的记录，对应掘金内容检索结果。

来源：https://bailian.console.aliyun.com/