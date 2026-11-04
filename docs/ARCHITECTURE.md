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

- 正文解析、摘录和保存本地完成；用户导入 PDF 或重新识别时，检测到 arXiv/DOI 编号会查询官方书目，链接导入会下载全文。远程 LLM 由显式分析、问答、解释、翻译操作，或已启用专题的闲时研究触发。
- API 和数据库操作必须可重复执行，导入以 sha256 去重。
- 大文件上传使用流式写入；PDF 解析和分析在后台 job 中执行，避免阻塞 HTTP。
- SQLite 开启 WAL、外键约束和合理索引；写入事务短小明确。
- 日志包含 request_id、job_id、paper_id，但不记录完整 PDF 或 API secret。
- 测试覆盖 service 的关键路径、schema 校验、evidence 定位和 API smoke；前端至少覆盖路由、空状态和 Reader evidence 交互。


## 8. 后台研究与阅读优先

`BackgroundResearchWorker` 在服务生命周期内运行，按专题材料指纹安排有限的研读、写作与审读，独立于论文首次分析。原文作为事实来源，已确认知识作为索引，个人笔记和问题表达研究兴趣。长文按章节选择片段并展示覆盖，不把缺失部分假装成全文。

研读检查点保存 `teaching`：读者问题、关联原文证据的机制步骤、可选的论文案例或假设示例。写作和审读接收同一份提纲；原文匹配与引用身份由程序校验，语义支持及讲解质量仍由模型审读和实际阅读检验。审读保留有效例子与行文，只修正实质问题。材料指纹包含三阶段提示词的摘要，写作流程变化也能生成新版；已有版本保持不可变，旧检查点会被替代，不能混入新流程发布。

`ProfileStore.subscription_provider()` 在同一锁下检查连接类型并冻结官方 provider，避免并发编辑配置时落到付费 API。`ResearchPriority` 用共享账户容量、前台请求计数和带过期时间的阅读页面心跳协调前后台。官方 exec 的队列轮询约每 200ms 检查取消，终止后台子进程后释放同一账号通道；中断不承诺退还额度或保留模型内部推理。

额度来自官方 app-server 的 account/rateLimits/read；保留多桶 ID 和实际窗口时长，未知字段阻止后台生成。账户状态缓存 10 秒；额度快照独立缓存，成功后 60 秒允许自动刷新，失败后 15 秒允许重读，UI 强制刷新跳过缓存。快照绑定账号身份，登录、退出及账号变化会清空；保留成功读取与最近尝试的两个时间戳。空闲无任务时每分钟按策略检查。小于一天的窗口应用启停阈值，长窗口应用保留比例。不把 token 量换算成订阅余额。

登录与模型目录通过 `status(include_limits=False)` 检查，不触发额度 RPC。额度查询失败保留登录状态并返回安全的 `limits_error_code`；后台状态暴露 `quota_error_code`。仅网络超时、连接失败和可重试账户 RPC 错误允许沿用 120 秒以内的成功快照，并保留原读取时间；每次生成仍检查短长窗口、重置时间和保留线。快照过期或缺失时以 `quota_timeout` / `quota_unavailable` 等待，约 60 秒后重试；401/403、429 不沿用旧快照。显式刷新取得窗口后解除旧的查询等待。`quota_attempted_at`、`quota_using_recent` 供 UI 区分最新查询与近期结果。上游错误原文和认证信息不会进入状态接口。

CLI 子进程环境独立合并 Windows 注册表系统代理与环境代理，逐协议显式变量及 `ALL_PROXY` 优先，`NO_PROXY` 独立保留。系统代理直接读取以避免仅设置 `NO_PROXY` 时 Python 跳过注册表发现的问题；不修改父进程环境、系统代理或桌面 Codex 配置。

`/api/research` 提供状态、额度、设置、专题方向、版本、任务更新/取消/重试与阅读心跳。React 专题文章页复用安全 Markdown/KaTeX，编号引文打开原文后支持 PDF 定位，版本和阅读位置可在离开页面后恢复。

同一队列支持 `essay` 与 `findings` 两类任务，各自去重、替代和恢复。专题 `work_types` 选择文章、论文联系、知识缺口、复习题与研究问题；旧专题默认只做文章。线索以 `discover → assess → published` 两次调用完成：发现阶段读取原文及已有线索摘要，复核阶段只读取候选与关联原文。先校验原句和类别，复核通过后原子发布。跨论文联系至少包含两篇论文证据，输出最多12条，可为空。两阶段提示词独立进入线索材料指纹，文章原有指纹保持兼容。用户的保留、忽略与复习操作不改变材料指纹，不触发重新生成。

每次阶段调用记录开始时间，结束时保留最近20条安全事件，包括阶段、保存/让出/失败代码及原因。已返回但未通过校验的输出也计入已知token用量；未返回用量的中断不猜测费用。任务恢复后保留事件，不因当前错误清空而失去故障依据。

`research_findings` 保存可持续更新的内容与独立用户状态，`research_finding_revisions` 保存不可变修订。模型复核利用历史ID与用户选择进行语义去重；程序补充同类型、标题与论文身份校验，以及正文、下一步和原文锚点相同的改名副本识别，保留状态和复习计划。该校验不能形式证明不同表述是否同义。线索不会自动修改知识摄取目录或执行外部搜索。

研究线索页使用列表与阅读区，类别/状态筛选保存在会话内。复习答案主动展开，进度在数据库保存，间隔为10分钟重试或1/3/7/14/30/60天。安排复习不调用模型。引文复用文章的原文弹窗与PDF定位；窄屏切换列表/详情，按实际滚动容器恢复位置。异步修订请求按选中ID与请求序号校验，避免迟到响应混入其他线索。

阅读问题通过 `research_reading` 独立接入同一队列。问题笔记及失败/中断提问保留原始身份、选段和页码；成功提问不重答。问题在调用前后重新检查，删除、改写、后续成功回答及用户忽略/完成会影响发布。`intent_key` 跨专题去重，同一论文有稳定归属；阅读任务不依赖基础文章，也不使整轮文章失效。相同答案可以通过 `answered_by` 关联，保持正文与修订不变，并继承后续人工状态。

定向任务先选读相关章节、选段附近及仍匹配原文的历史证据，附完整章节目录和真实覆盖。模型可请求一次有界扩读，来源ID稳定；旧解释只作线索。引用校验失败时检查点保存被拒草稿及错误位置，下次定点修复；不放宽引用规则。核验步骤和已有调用的任务优先于新任务，维护批次同样区分启动与续跑。

后台准入只依据官方返回的短、长额度窗口、保留线与前台活动状态。每次生成前重新检查这些条件；本地不设置小时调用上限，也不从长窗口推算每日后台预算。研究控制表内旧预算快照只为兼容既有数据库保留，不参与运行时判断。

## 9. 持久翻译队列

`translation_queue` 把手选段落和全文预译保存在 SQLite，由同一个 `BackgroundResearchWorker` 执行。HTTP 入队只保存任务，不等待模型返回。按段保存到既有 `translations`，直接翻译和队列共用原文、配置与提示词身份以及来源锁，避免重复生成。作业快照不保存凭证。

手选任务与全文预译均可在阅读时运行，阅读心跳不取消翻译；提问、单段翻译和分析拥有更高优先级。全文任务使用研究设置里的官方连接，受后台开关和官方短长窗口保留线约束，并与待处理的专题研究、知识维护轮换；专题研究与知识维护仍等待阅读结束及空闲窗口。选段提升按共享工作身份让其他工作协作退出，同一在途段落不中断，暂停与已完成项不抢占。每次模型调用前再次检查实际前台占用和可执行的更高优先级段落，冷却中的任务不阻塞其他段落。边界检查与翻译分别检查官方准入条件并保存进度。全文任务不会进入付费备用路由。

段落来源按 chunk 与偏移校验，合并通过 refs 重定向，调用前后重新核对原文和模型配置。暂停、取消及暂时抢占保留已保存译文；内容失败有限重试。服务恢复时把未完成的 running 项放回队列，已完成项复用缓存。

阅读器的 `useTranslationQueue` 只观察服务端任务，卸载时停止轮询，不取消作业。进度、批量选择和当前译文独立，已完成一段即可阅读，迟到结果不会切换当前段落。轮询返回段落状态、合并别名和译文，不重复传输整篇原文。

段落活动状态同时检查作业和项，暂停作业不显示持续加载，也不因选读而恢复。暂停中的单段翻译或重试会建立手选授权，保留整篇暂停；跨作业复用缓存和工作，但不混淆授权状态。

## 10. 阅读对话的收起与恢复

选段问答在提交前创建本地对话，`run_question` 先提交 running 的问题记录，再生成和保存回答。`ReadingConversations` 固定打开时的选段或页码，收起时保留 `ExplainPanel` 的组件生命周期与草稿，界面卸载不会主动取消已提交请求。切页或改选其他段落不会改变原问题的上下文。服务重启仍按原有逻辑标记 interrupted，由用户明确重试，不自动重复生成。

阅读器顶部提供当前对话与本篇历史入口。历史跨选段查询，摘要只附最新问题、状态和轮次 ID；后端用一个窗口查询取得本页最新轮次，不拉取完整回答或逐条查询。活动时约两秒刷新，空闲时十五秒，后台标签停止轮询，重新聚焦时刷新。分页刷新保留已经展开的旧页。历史菜单挂载到 body，按视口测量位置与高度，避免阅读页面的 transform 或容器裁剪导致越界。

显式对话 ID 用于导航和刷新后的恢复，SQLite 是正文与状态的来源。中文选段作为 translated_text 保存，但不参与上下文身份哈希，旧英文证据身份继续兼容；恢复时同时显示中文摘录与英文依据。图、表、公式问答保存页码、区域坐标、类型和标签，从原 PDF 在浏览器本地重建预览与追问所需图像，不把 base64 图像写入数据库。恢复只读档案，不重新调用模型。

## 11. 公式与图表定位

`visual_regions` 使用原生 PDF 的文字、图像与矢量坐标定位图表，排除目录、页眉页脚和几乎透明的出版底纹。三线表先拼接单元格边线，再匹配表头与表底；图注按字号、行距和栏边界恢复连续行，同编号双语图注共用一个目标。相邻图注和正文构成候选图像的边界。

`equation_regions` 单独定位显示公式。正文基线排除行内数学，双栏栏缝阻止跨栏合并；纵向重叠的分子、分母、上下标和装饰符组成裁图，支持中文层级编号与旧 Symbol 字体。区域保留 PDF 点坐标，不将损坏的文字层猜写为 LaTeX，也不改写存储的原文证据。

提问时优先提供实际选区内的原文块与裁图，再按现有机制补充相关上下文。视觉连接负责按需转写和解释，公式要求用 LaTeX 并保留编号；遇到无法辨认的符号明确指出。临时请求错误只允许一次携带同一图像的重试，不静默改成纯文字回答。扫描件的完整 OCR、全文公式 LaTeX 索引和表格 HTML 重建尚未接入。真实中文 PDF 的检查范围与结果见 [识别验证记录](superpowers/evidence/2026-11-04-chinese-visual-recognition.md)。
