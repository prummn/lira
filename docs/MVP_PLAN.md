# Research Intelligence Workspace MVP 实施计划

> 文档类型：**实施计划**。下文阶段没有隐含“已完成”状态；每一项只有在 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 中附有验证证据后才能标为完成。前轮交付了界面原型和基础 API skeleton，未跑通真实 PDF 阅读端到端流程。

2026-10-07 当前迭代已补齐本地真实阅读闭环，并新增 arXiv/公开 PDF 链接导入、首页版式书目识别、arXiv/Crossref 补全、字段来源、手动修正与保留用户锚点的刷新；数据库版本为 `0006_arxiv_revision`，保留实际 PDF 版本。Attention/BERT/LoRA 官方来源和真实验证见 [real-paper-import-validation.md](real-paper-import-validation.md)，新增 17 篇 GitHub RAG 清单实测见 [github-rag-import-validation.md](github-rag-import-validation.md)。下文仍保留原始阶段设计，当前已验证功能与后续目标以状态文档区分。

## 1. 交付目标

第一轮交付是一个可以在本机运行的 React/Vite + FastAPI + SQLite skeleton，并用 8–12 篇高质量 mock AI 论文跑通：导入/解析 → Paper Card → 中英摘要 → PDF 阅读 → Evidence 问答 → Collection → 多论文比较 → Citation Graph → 基础 Method/Concept Graph。

每个阶段结束都必须能启动前端和后端；真实 LLM 质量验收和 Tauri 打包保持后续范围。arXiv/Crossref 真实书目查询已经实现；OpenAlex/Semantic Scholar 的完整作者与引用网络仍是目标扩展。

## 2. 阶段划分

### Phase 0：工程基线（第 1 个工作块）

创建 monorepo 目录、前端 Vite React TypeScript、后端 FastAPI、共享类型、`.env.example`、README 启动说明。启用 TypeScript strict、Python lint/type check、统一 API 错误格式和基础日志。完成后检查 `npm run build`、后端健康检查和空数据库迁移。

### Phase 1：数据层与 mock 数据（第 2 个工作块）

实现 SQLAlchemy models、Alembic 初始迁移、SQLite WAL/外键、Repository 层和 jobs 表。编写 seed 脚本导入 8–12 篇虚构但语义完整的 AI 论文，包含作者、venue、年份、摘要、chunks、claims、evidence、引用边、method/concept 节点和结构化 Paper Card。Seed 后可直接打开 Library/Knowledge。

验收：重复执行 seed 不产生重复记录；`/api/papers`、`/api/collections/{id}/field` 返回稳定 JSON；所有 evidence 都能对应 page/chunk。

### Phase 2：应用壳层与 Library（第 3 个工作块）

实现简中 locale、浅色/深色主题、设计 tokens、sidebar、全局搜索入口、Settings 基础页。完成 Library 列表、过滤排序、收藏、阅读状态、Collection 创建/添加/移除、loading/empty/error 状态。

验收：1440p 和 1080p 均无横向溢出；刷新页面状态从 API 恢复；无 API key 时 mock 数据可用。

### Phase 3：PDF 导入与 Reader（第 4–5 个工作块）

后端实现 multipart 导入、sha256 去重、PyMuPDF parser、Page/Chunk 持久化和 job 状态；前端接入 PDF.js，完成页码、缩放、搜索、目录、文本选择、highlight。Reader 右栏显示 TL;DR、Structured Summary、Evidence 和 Notes 标签。

验收：导入一份真实 PDF 后能看到页数和文本；点击 evidence 能切换到页面并绘制 approximate/exact overlay；解析失败能重试且错误可见。

### Phase 4：AI Adapter、Paper Card 与 Ask（第 6 个工作块）

定义 `ModelProvider`、`MockProvider`、Pydantic 输出 schema 和 prompts 版本。实现分析 job、Paper Card 三层摘要、Explain 五种动作、Ask 检索当前论文 chunks 并返回证据。真实 OpenAI provider 仅在配置 key 后启用。

验收：MockProvider 返回稳定结构；问答无证据时明确提示；每条回答有 page/section/source_text；模型失败不覆盖上一次 ready 结果。

### Phase 5：Knowledge / Field View（第 7 个工作块）

实现 Collection Timeline、Citation Graph（Cytoscape.js）、Method/Concept Graph、2–5 篇论文 Comparison Matrix。视图按 relation_source 显示徽标，支持点击节点回到论文或 evidence。

验收：mock Collection 可在无网络情况下完成五个视图；图谱布局在节点较少时稳定；比较单元格能够展开证据。

### Phase 6：Researcher、搜索与硬化（第 8 个工作块）

实现 Researcher View 和作者-论文关联；SQLite FTS5 metadata/full-text search；补充导入边界、权限路径、错误、可访问性和性能检查。编写 API smoke、service 单测和关键前端交互测试。

验收：核心路径可从全新数据目录重现；测试、lint、build 全通过；README 能让新开发者在 10 分钟内启动。

## 3. 并行工作拆分

可并行的任务：

- 前端壳层、Library、Reader 组件。
- FastAPI 数据模型、迁移、Repository。
- Mock dataset、prompt/schema、Provider 接口。
- PDF.js evidence overlay 与图谱视图。

共享约定：先冻结 API 类型和字段命名；所有分支只改自己负责的目录；合并前运行迁移、seed、前端 build 和后端测试。若共享 API 变化，先更新 `packages/shared` 与 OpenAPI，再调整双方实现。

## 4. API 与完成定义

每个功能以以下清单验收：

1. 数据库迁移可重复执行，模型有索引和外键。
2. API 有成功、空结果、参数错误、资源不存在和内部错误响应。
3. 前端有 loading、empty、error、retry；关键操作有 toast/inline feedback。
4. AI 结果带 provider/model/prompt_version 和 evidence，来源徽标可见。
5. 至少一个有意义的测试覆盖核心逻辑；测试不只镜像实现细节。
6. 文档、启动脚本和 mock 数据同步更新。

## 5. 测试矩阵

- 后端单测：sha256 去重、状态机、Paper Card schema、evidence locator、relation source、FTS 查询。
- API smoke：健康检查、导入、列表、详情、分析、Ask、Collection Field。
- 前端：路由与主题、Library 过滤、Reader evidence 跳转、Graph 空状态、错误提示。
- 手工验收：中文长标题、长作者列表、窄屏、深色主题、PDF 无文本层、网络不可用、MockProvider。

当前实际验证命令：`python -m pytest backend/tests -q`、`npm --prefix frontend run build`、`npm --prefix frontend run test:e2e`；真实论文场景需显式设置 `RIW_REAL_PAPER_FIXTURES`。Ruff／独立 npm lint 和完整 CI 是原目标，当前 package.json 没有 npm lint 脚本，不能宣称这些检查已执行。

## 6. 风险与取舍

- PDF 版式复杂：先保存 text/bbox 并允许 approximate 定位，GROBID 延后。
- LLM 输出不稳定：schema 校验、版本化 prompt、保留上一次结果和 MockProvider。
- 图谱噪声：只显示 Collection 内、带证据或明确标注 AI inferred 的边。
- SQLite 写入冲突：启用 WAL、短事务和任务串行写入；数据规模超出单机后再评估独立服务。
- 外部 API 限流：provider 适配器加超时、重试和缓存，网络失败不影响本地阅读。

## 7. 后续迭代顺序

完成 MVP 稳定性后，再按价值增加：OpenAlex/Semantic Scholar 作者与引用网络、embedding 语义搜索、用户确认关系、Researcher 外部链接、Tauri 打包与可选同步。段落级翻译缓存已落地，缓存契约已验证；有效模型真实翻译质量仍未验收。每项功能都要回答“是否加快阅读，或让未来更容易找回今天的理解”。
