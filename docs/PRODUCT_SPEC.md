# Research Intelligence Workspace 产品规格

> 文档类型：**产品目标与验收标准**。本文中的“支持”“提供”“必须”描述目标行为，不代表当前版本已经实现或通过验证。实际交付状态见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)，验收证据见 [QA_CHECKLIST.md](QA_CHECKLIST.md)。

## 1. 产品定位

Research Intelligence Workspace（以下简称 RIW）是一个 Local-first 的科研论文阅读与知识管理工作台。用户以论文为入口，在原文证据、个人笔记与结构化知识之间建立可追溯连接，逐步形成对一个研究领域的长期认知。

目标用户是需要持续阅读、比较、追踪 AI/计算机论文的研究人员。产品优先服务“每天阅读”和“半年后仍能理解自己的判断”两个场景，不以 ChatPDF 式的一次性问答或炫技图谱为目标。

核心价值排序：**Evidence → Reading → Structured Knowledge → Cross-paper Synthesis → Visualization → AI Fancy Features**。

## 2. 产品原则

- **Local-first**：PDF、解析文本、批注、笔记、分析结果默认存于本机文件系统与 SQLite；MVP 不引入账号、云同步或远端数据库。
- **Evidence-backed**：AI 生成的结论必须携带证据类型、页面、章节、原文和置信度；用户可从结论定位到 PDF。
- **来源分层**：原文事实（explicit）、外部元数据（metadata）、AI 推断（llm_inferred）、用户判断（user）在数据和界面上分开。
- **可渐进使用**：没有 API key 时，MockProvider 也能跑通导入、阅读、分析、问答和图谱演示。
- **简洁耐用**：中文优先、信息密度高、低饱和度、少装饰，避免营销式卡片堆叠和过度动画。

## 3. MVP 成功标准

一个新用户能够在本地完成以下闭环：

1. 将一个或多个 PDF 导入 Library，看到基础元数据和解析状态。
2. 打开 Paper Reader，在左侧阅读 PDF，在右侧查看 TL;DR、结构化 Paper Card 和证据。
3. 选中原文进行翻译、解释或提问；回答显示 `Page · Section`，点击可回到原文位置。
4. 将论文加入 Collection，查看时间线、比较矩阵和引用图。
5. 写一条带来源的阅读笔记或研究想法，并在之后从论文或 Collection 找回。

验收指标（本地演示数据）：导入 8–12 篇 mock 论文后，页面无 API key 仍可操作；核心列表、Reader、Evidence 跳转和 Citation Graph 在 1440p/1080p Windows 屏幕上可用；API 错误、解析失败和空数据都有可理解的状态提示。

## 4. 信息架构与页面

### 4.1 全局壳层

左侧固定导航：Library、Collections、Reading、Knowledge、Researchers、Settings。底部显示数据目录、索引状态和主题切换。顶部提供全局搜索、当前页面上下文和快捷键提示。

默认语言为 `zh-CN`，所有 UI 文案来自 locale 文件；保留 `en-US` 的键结构。支持浅色/深色主题，主题只影响颜色和阴影，不改变信息架构。

### 4.2 Library

提供拖拽和文件选择两种 PDF 导入方式，支持批量导入、重复文件检测和失败重试。列表字段：标题、作者、年份、venue、标签、阅读状态、收藏、AI 分析状态、最近阅读时间。

过滤器：Collection、Tag、阅读状态（Unread/Skimming/Reading/Read/Important）、分析状态、年份。支持标题/作者/venue 全文检索、按更新时间/年份/标题排序。空状态要给出“导入 PDF”主操作和 mock 数据入口。

### 4.3 Paper Reader

Reader 使用双栏布局：左侧 PDF.js 画布（页面、缩放、搜索、目录、文本选择、highlight）；右侧 AI Notebook（Summary、Translation、Explain、Ask、Structured Info、Notes 标签）。工具栏显示标题、阅读状态、收藏、Collection、页面号、阅读模式（原文/中英对照/仅中文）。

Evidence 卡片必须显示 source type、页面、章节、原文片段和“定位到原文”按钮；点击后切换 PDF 页并高亮对应文本块。无法定位时展示原因和页码，不伪造精确位置。

### 4.4 Knowledge / Field View

以 Collection 为上下文，提供 Timeline、Citation Graph、Method Lineage、Concept Graph、Paper Comparison 五种视图。AI 推断的关系必须有 `AI inferred` 徽标和置信度；明确引用关系或论文原文关系显示 evidence。

Timeline 描述技术变化（introduced/extended/challenged/unified），而不是仅按年份排卡片。Comparison Matrix 允许选择 2–5 篇论文，行包括 Problem、Method、Training、Dataset、Metric、Strength、Limitation，单元格可展开到 Evidence。

### 4.5 Researcher View

作者页展示姓名、机构、研究组、公开链接和代表论文。显示其在当前 Library 中的论文数、Collection 关联、共同作者和研究方向变化。关系分类为 verified、collaboration、AI inferred；没有证据时不输出师生等身份关系。

## 5. 核心功能规格

### 导入与解析

导入任务创建后立即出现在 Library，状态依次为 `queued → parsing → ready`，失败为 `failed` 并保存错误原因。解析管线：PDF → Page → Block → Paragraph → Section；每个文本块保存页码、bbox、section 和稳定 ID，以支持证据定位。PyMuPDF/PyMuPDF4LLM 为默认适配器，GROBID 作为未来可替换实现。

### Paper Card 与摘要

统一字段：one_sentence_summary、problem、motivation、background、core_idea、method、contributions、datasets、metrics、baselines、main_results、ablation_findings、limitations、future_work、prerequisite_concepts、claims、related_methods。每个数组项可附一个或多个 Evidence。展示层级为 TL;DR（3–5 行）、Structured Summary、Section Summary。

### Ask / Explain

Ask 只检索当前论文或用户明确选择的 Collection，回答上下文和来源可见。结果由 answer、citations、uncertainty、follow_up 组成；证据不足时明确说“当前材料无法确认”。Explain 支持翻译、简单解释、数学解释、先修概念和与其他论文比较五种动作。

### 双语阅读

翻译按 paragraph 对齐，保留公式、citation、模型名、数据集名和 acronym；翻译结果可缓存，缓存失效不影响原文阅读。UI 三态为原文、中英对照、仅中文。

### 搜索

MVP 实现 metadata search 与 SQLite FTS5 full-text search；后端保留 `EmbeddingProvider` 接口，先用本地 mock embedding/可选向量索引，后续再接真实模型。搜索结果必须标注匹配来源（标题、正文、语义）。

## 6. 非目标与边界

MVP 不做用户注册、云同步、支付、多人协作、完整 Zotero/BibTeX 替代、Neo4j、微服务、复杂 Agent swarm、自动写论文和大规模爬虫。Tauri 2 仅作为后续封装，不能阻塞 Web + 本地 FastAPI 可运行。

## 7. 关键交互与质量要求

- 任何异步操作都有 loading、empty、error、retry 状态。
- 删除论文前需要二次确认，并保留可恢复的文件路径策略。
- 键盘快捷键：`Cmd/Ctrl+K` 全局搜索、`Cmd/Ctrl+Enter` 提问、`G then L/R/K` 切换工作区。
- 长标题、中文字体、窄窗口必须可读；颜色不能单独承担状态含义。
- 所有 AI 结论都能查看原始 prompt/model/时间和证据列表，便于复核。
