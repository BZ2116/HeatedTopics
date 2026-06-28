# GitHub Search Quickstart

## 获取 Token

1. 访问 https://github.com/settings/tokens
2. 点击 **Generate new token** → **Generate new token (classic)**
3. Note 随便填一个（如 `heatedTopics`），Expiration 按需选择
4. **Scopes 全部留空**（搜代码走公共 API，不需要任何权限）
5. 点击 **Generate token**，复制生成的 token（以 `ghp_` 开头）

## 配置 .env

在项目根目录的 `.env` 中追加：

```
GITHUB_TOKEN=ghp_your_token_here
```

## 速率限制

- 无 token：60 req/h
- 有 token：5000 req/h

强烈建议配置 token，否则一轮 discovery 很快就会触发限流。

## 验证

```bash
uv run python -m src.search_discovery.cli \
  --profile config/search_discovery/creator_profiles/tech_ai_creator.json \
  --render-report
```

查看 `data/search_discovery/raw/search_results.jsonl`，每条记录应包含 `source_id: "github_code"`。

来源：https://github.com/settings/tokens