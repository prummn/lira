# Research Intelligence Workspace 架构设计

> 文档类型：**目标架构**。接口、适配器、目录与运行机制是设计约定；不能用本文证明实现已经存在。当前仓库使用 `frontend/` 与 `backend/`，尚未采用下文的 `apps/web`、`packages/shared` 完整 monorepo 结构。当前实际使用统一 API client、PDF.js、Provider protocol 与 Alembic，但未实现下文所有扩展模块。当前实现与验证情况见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。

当前已交付的导入链路位于 `backend/app/services/{downloads,pdf,pdf_metadata,metadata,importing}.py`：公开 PDF 下载、首页版式识别、arXiv HTML/Atom 与 Crossref DOI 补全、字段来源和手动修正。导入同步完成，前端逐文件调用；下文 jobs 队列、OpenAlex/Semantic Scholar、完整 MetadataProvider protocol 属于目标扩展。默认真实数据库与 PDF 路径是 `backend/paper_reader.db` 和 `backend/storage/`。

## 1. 总体方案

MVP 采用本地单机、前后端分离的模块化单体：React + TypeScript + Vite 前端，通过 HTTP/JSON 调用 Python FastAPI；FastAPI 使用 SQLAlchemy 访问 SQLite，文件系统保存 PDF 和派生文件。开发时前端与后端分别启动，未来再用 Tauri 2 将两者打包为桌面应用。

```text
React/Vite (apps/web)
  ├─ pages / components / features
  ├─ i18n / theme / query cache
  └─ typed API client (packages/shared)
              │ HTTP JSON
FastAPI (backend/app)
  ├─ api routes + Pydantic schemas
  ├─ services (papers, collections, notes, knowledge)
  ├─ pdf (parser, locator)
  ├─ llm (adapter, prompts, retrieval)
  ├─ metadata (OpenAlex/S2/Crossref adapters)
  └─ search (FTS5, embedding abstraction)
              │
SQLite + Alembic        data/papers/{paper_id}/original.pdf
```

## 2. 目标工程结构

```text
apps/web/
  src/{app,components,features,pages,lib,locales,styles}
backend/app/
  api/{routes,dependencies.py}
  models/ schemas/ services/
  pdf/ llm/ metadata/ knowledge/ search/
  db/{session.py,migrations/}
packages/shared/{api-types,constants}
prompts/{paper_card,qa,translation,relation}
data/{library,cache,workspace.db}
docs/
```

前端按功能拆分 `library`、`reader`、`knowledge`、`researchers`，页面只负责编排；数据请求统一通过 query/mutation hooks，禁止在组件中直接写 fetch。后端 route 只做鉴权（未来）、参数校验和服务调用，业务逻辑进入 service，SQLAlchemy model 不直接暴露给 API。

## 3. 前端设计

- TypeScript strict；共享 API 类型由 `packages/shared` 或 OpenAPI 生成，避免手写漂移。
- Tailwind CSS + 少量 Radix/shadcn primitives；颜色、间距、圆角、字体通过 design tokens 管理。
- React Router 页面路由：`/library`、`/papers/:paperId`、`/collections/:id`、`/knowledge/:id`、`/researchers/:id`、`/settings`。
- TanStack Query 管理服务端状态，Zustand 或 React context 仅管理主题、Reader 面板和临时选择状态。
- PDF.js 封装为 `PdfViewport`、`PdfToolbar`、`PdfSearch`、`EvidenceOverlay`，不要让 Reader 成为单一巨型组件。
- 图谱首选 Cytoscape.js；时间线与比较矩阵先用可访问的 DOM/CSS，复杂布局再引入 D3。
- i18n 采用 `locales/zh-CN.json` 与 `en-US.json`，组件只引用 key。字体栈优先系统中文字体。

## 4. 目标后端边界与 API

推荐 API：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/papers` | 分页、过滤、排序、搜索论文 |
| POST | `/api/papers/import` | 上传一个或多个 PDF，创建导入任务 |
| GET | `/api/papers/{id}` | 论文详情、处理状态、Paper Card |
| GET | `/api/papers/{id}/pages/{page}` | 页面文本块和定位信息 |
| POST | `/api/papers/{id}/analyze` | 触发 Paper Card 生成 |
| POST | `/api/papers/{id}/ask` | 当前论文问答与证据 |
| POST | `/api/papers/{id}/explain` | 对选中文本执行翻译/解释 |
| GET/POST | `/api/collections` | Collection 列表与创建 |
| POST/DELETE | `/api/collections/{id}/papers/{paper_id}` | 添加或移除论文 |
| GET | `/api/collections/{id}/field` | 时间线、图谱、比较数据 |
| GET/POST | `/api/notes` | 笔记和研究想法 |
| GET | `/api/search` | metadata/FTS/semantic 统一搜索 |

当前新增可用接口：`POST /api/papers/import-url` 接收 `{url}`；`POST /api/papers/{id}/refresh-metadata` 保留原文锚点刷新书目；`PATCH /api/papers/{id}` 可局部修改标题、作者、年份、venue、DOI 与 arXiv 编号。列表和详情增加 `source_url`、`metadata_sources`、`metadata_warnings`；当前错误响应使用 FastAPI `{detail}`。上传接口一次接收一个文件，前端批量流程逐文件调用。当前集合添加使用 `PUT`，移除使用 `DELETE`。

统一错误格式：`{code, message, details, request_id}`。长任务返回 `job_id`，前端轮询 `/api/jobs/{id}`；MVP 可使用进程内任务队列，接口保持可替换为 Celery/RQ 的形状。所有时间使用 UTC 存储、前端按本地时区展示。

## 5. 关键服务与适配器

### PDF 服务

`PdfParser` 输出 Page/Block/Paragraph/Section；`PdfLocator` 接受 evidence 的 page、paragraph_id、bbox，返回前端 overlay 所需坐标。解析文本和原 PDF 均按 paper_id 隔离存储。解析失败只能将任务标记为 failed 并记录异常，不能吞掉错误。

### LLM 服务

```python
class ModelProvider(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

实现 `MockProvider`、`OpenAIProvider`，未来可加入 Anthropic/Gemini/Local。业务层只依赖 protocol；prompt 独立存于 `prompts/`，输出先通过 Pydantic schema 校验，再写入 `paper_analysis`/`evidence`。每次生成保存 provider、model、prompt_version、时间和原始响应摘要。

### Metadata 服务

```python
class MetadataProvider(Protocol):
    def search_papers(self, query: str) -> list[PaperMetadata]: ...
    def get_paper(self, external_id: str) -> PaperMetadata | None: ...
    def get_author(self, external_id: str) -> AuthorMetadata | None: ...
    def get_references(self, external_id: str) -> list[str]: ...
    def get_citations(self, external_id: str) -> list[str]: ...
```

按 OpenAlex、Semantic Scholar、Crossref 分别实现并记录 provider/source_id；合并逻辑放在 `MetadataResolver`，业务层不直接调用厂商 SDK。网络不可用时导入仍可使用文件名和 PDF 内嵌元数据。

当前实现用 `enrich_metadata` 返回 fields/sources/warnings：arXiv citation HTML 必须匹配论文编号，缺失或无效时尝试 Atom；最终地址须为官方 HTTPS 来源。Crossref 必须返回匹配 DOI，且不能覆盖已取得的 arXiv 标题、作者或首次提交年份。手动字段在合并时优先。公开 HTTP 下载逐重定向检查 DNS 解析结果、拒绝私网地址，连接固定到已检查的 IP，保留 Host/TLS 校验，并限制响应大小、读超时和流式总预算。全文 PDF 保存在本机；元数据查询只发送编号，不调用 LLM。

重新识别不会重建现有 chunks：只在页面、原文和 bbox 可匹配时修正其 section；无法匹配的块保留 ID、内容与定位并提示。保存书目时同步卡片标题，既有分析内容需主动重新分析。Mock 分析和问答从论文已出现的编号章节恢复父节上下文，使 `6.1` 正文可归入 `6 Results` 的摘录候选；引用仍核对真实原文。

解析器在两栏持续正文页面中按 body columns 和 full-width bands 传播 section，以避免右栏标题误标左栏训练段；输出 chunk 仍按既有原始块顺序，保留文本和 bbox。真实 BERT 470 块与 Attention 544 块已逐项验证兼容；此规则仍是局部版式启发式，复杂多栏文档需要另行验收。

### 检索服务

MVP 使用 SQLite FTS5 对 paper_chunks 建全文索引；`SearchService` 统一 metadata、全文和 semantic 三类结果，并返回 `match_type`、score、chunk_id。Embedding 通过接口隔离，默认 MockProvider，不强制安装向量数据库。

## 6. 数据流

```text
上传 PDF
  → ImportService 复制文件、计算 sha256、创建 paper/job
  → PdfParser 生成 pages/chunks/sections
  → MetadataResolver 补充标题、作者、venue、年份
  → PaperAnalyzer 检索 chunks，调用 ModelProvider
  → SchemaValidator 拆出 claims/evidence/edges
  → UI 查询 Paper Card、Reader 和 Knowledge View
```

引用关系优先来自 PDF/metadata 的明确引用；AI 推断关系必须写入 `relation_source=llm_inferred`。用户编辑只更新 user 类型记录，不覆盖原文 evidence。

## 7. 非功能要求

- 正文解析、摘录和保存本地完成；用户导入 PDF 或重新识别时，检测到 arXiv/DOI 编号会查询官方书目，链接导入会下载全文。远程 LLM 仅由显式分析、问答、解释、翻译操作触发。
- API 和数据库操作必须可重复执行，导入以 sha256 去重。
- 大文件上传使用流式写入；PDF 解析和分析在后台 job 中执行，避免阻塞 HTTP。
- SQLite 开启 WAL、外键约束和合理索引；写入事务短小明确。
- 日志包含 request_id、job_id、paper_id，但不记录完整 PDF 或 API secret。
- 测试覆盖 service 的关键路径、schema 校验、evidence 定位和 API smoke；前端至少覆盖路由、空状态和 Reader evidence 交互。
