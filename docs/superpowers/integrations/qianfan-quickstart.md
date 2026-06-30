# Baidu Qianfan Search Quickstart

## 获取 AK / SK

1. 访问 https://console.bce.baidu.com/qianfan/ 并登录百度智能云账号
2. 进入 **应用接入** → **创建应用**，名称任意
3. 在应用列表中点击 **查看**，复制 **API Key (AK)** 和 **Secret Key (SK)**
4. 在应用能力中开启 **AppBuilder 搜索增强**

## 配置 .env

```
QIANFAN_API_KEY=your_ak_here
QIANFAN_SECRET_KEY=your_sk_here
```

Provider 在启动时会用 AK/SK 换取短期 `access_token` 并缓存到内存，无需在请求时手动处理鉴权流程。

## 验证

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

查看 `data/search_discovery/raw/search_results.jsonl`，应能看到 `source_id: "baidu_qianfan_search"` 的记录。

来源：https://console.bce.baidu.com/qianfan/