# 本地阅读闭环实施计划 · 2026-10-07

目标：将上一轮界面演示升级为可持久化、可阅读真实 PDF、可复核原文证据的本地 MVP。

用户已授权自主实施整体产品方案，常规架构和样式选择不再逐项确认。

## 实施顺序与边界

1. 后端：临时数据库测试先行；解析与 PDF 文件校验；页码/坐标文本块；证据抽取和拒答；笔记、Collection、FTS；迁移与兼容。
2. 阅读器：PDF.js 本地 worker、画布与可选文本层、全文搜索、目录、缩放、页码、坐标定位、文字选取。
3. 前端：移除与数据库脱节的演示状态，建立统一 API 客户端；拆分 Library、Reader、Knowledge、Researchers、Settings；locale 文件；导入/批注/笔记/收藏/状态真正保存。
4. 运行：一条命令启动前后端，本地数据目录和可选模型配置可见。
5. 验收：真实 PDF 导入→解析→阅读→证据定位→笔记→Collection→图谱；刷新保留数据；无文本、无模型、坏文档、离线错误如实显示；1080p/1440p 与深色主题浏览器检查。

## 具体契约

- 所有数据走 `/api`，Vite proxy 指向本机 8000，不依赖固定前端端口的 CORS。
- 文本块 bbox 是**未旋转、CropBox-relative、左上角原点的 PDF points**：`[x0,y0,x1,y1]` 相对于可见 CropBox；`page_width/page_height` 是未旋转 CropBox 的宽高。不能把 MediaBox、已旋转尺寸或 CSS pixel 当作持久化坐标。PDF.js viewport 负责在渲染时应用 CropBox 偏移、页面 rotation 和缩放，转换只应用一次；选区保存时使用逆变换回到同一契约。
- MockProvider 仅抽取原文，不假装生成技术结论或翻译；不足以回答时拒答。
- 示例论文、作者和关系显式标记为虚构；示例使用真实可渲染 PDF。
- 笔记与选区来源标记 user；论文事实、AI 推断与用户判断分别显示。
- 未接入的远程 metadata、semantic search、OCR、云同步保持明确边界。

## 核心规格补齐

在真实闭环稳定后补齐统一 Paper Card schema、多层摘要与选区 Explain：结构化条目携带 evidence_ids，未报告的字段保持为空；Mock 仅摘录上下文，远端模型总结显式标记 AI 来源。迁移保留已保存笔记与分析。通过解析引用验证、跨论文引用拒绝与浏览器选区定位验证后再交付。

启动脚本读取 .env 为数据，不执行其中内容；进程记录保存启动时间，停止服务核对本次启动，避免误停其他实例。

## 验证命令

`python -m pytest backend/tests -q`

`npm --prefix frontend run build`

`npm --prefix frontend run test:e2e`

浏览器测试使用临时数据库，不写开发 Library。
