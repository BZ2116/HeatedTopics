# V3 Platform Hot List Matrix

First batch:

1. `juejin`
2. `bilibili`
3. `baidu` — implemented. Hot words come from `https://top.baidu.com/api/board?platform=wise&page=realtime`; per-word recall and article body follow via mobile Baidu search and baijiahao.baidu.com. See `docs/superpowers/specs/2026-07-19-baidu-hotword-source-design.md`.

Second batch:

1. `weibo`
2. `toutiao` - hot-list JSON implemented; full detail needs browser/session support.
3. `zhihu`

Excluded:

- `xiaohongshu`: handled by an external project.
