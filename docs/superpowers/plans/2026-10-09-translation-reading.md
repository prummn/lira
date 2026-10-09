# 论文对照阅读实施记录

目标：原版 PDF 始终存在；按自然段选择翻译；译文以中文学术排版和 KaTeX 数学公式展示。设计见 [论文对照阅读](../specs/2026-10-09-translation-reading-design.md)。

技术：React、TypeScript、PDF.js、KaTeX、FastAPI、PyMuPDF、SQLite、Playwright。

## 实施步骤

- [x] 在原有对照阅读测试中重现 PDF 被替换的问题，建立悬停、显式请求和缓存阅读的浏览器测试。
- [x] 从原文块和 PDF 排版派生阅读段落；保留来源与坐标，处理自然段、跨页续句、图注和短公式片段。
- [x] 提供 reading-paragraphs 接口，translate 接口支持 paragraph_id；复用 Translation 存储和原有缓存规则。
- [x] 在 PdfViewer 中加入段落命中测试和浮框，原文文本层保留文字选择、搜索、缩放和翻页。
- [x] 实现 TranslationPanel 和 ScientificText：右侧／底部译文、局部等待与重试、前后段导航、缓存展开、安全数学排版。
- [x] ReaderPage 按段管理请求，去重并隔离结果；笔记本隐藏时仍保留编辑状态，支持收起侧栏。
- [x] 用真实论文复核段落顺序；增加重叠文本块、短公式、多锚点悬停和窄屏自动布局的回归。
- [x] 用配置的 gpt-6.1-sol 实际翻译缩放点积注意力段落，确认译文中的上下标和根号，以及重复请求命中缓存。
- [x] 更新 README、使用指南和最终设计，说明实际操作及 PDF 数学提取边界。
- [x] 完成最终全量测试、生产构建、真实界面截图检查，并提交实现。

最终实现保留原始 PDF，不使用抽取文本重排英文，也不提供会隐藏英文原文的「仅中文」模式。验证详情见 [对照阅读验证](../../translation-reading-validation.md)。
