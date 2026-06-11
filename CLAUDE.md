# heatedTopics 项目规范

## 目录约定

- `reports/`：调研汇报、讲稿、阶段性方案文档。
- `data/`：后续采集到的原始热榜、清洗结果、样例数据。
- `src/`：后续实现代码。
- `docs/`：长期技术设计、接口说明、运行手册。

## 命名约定

- 汇报文档使用 `YYYY-MM-DD-topic-report.md`。
- 讲稿使用 `YYYY-MM-DD-topic-script.md`。
- 样例数据使用 `YYYY-MM-DD-source-sample.json`。

## 写作约定

- 默认中文。
- 结论先行，再给理由。
- 技术名词、命令、字段名使用英文。
- 涉及市场现状、工具能力、官方说明时，优先附来源链接。

## 验证方式

- Markdown 文档完成后，至少检查：
  - 标题层级是否连续。
  - Mermaid 代码块是否闭合。
  - 链接是否保留完整 URL。
  - 是否包含 Demo 版和长期稳定版两阶段方案。
