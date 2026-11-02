# Research Intelligence Workspace 数据模型

> 文档类型：**目标数据模型**。本表清单与字段是预期 schema，不能视为当前 SQLite 已有表。前轮仅实现核心 ORM 表的简化字段；本轮已有 Alembic、证据定位与用户笔记字段，完整类型知识实体仍属于后续目标。实际表结构以当前 Alembic migration 与 ORM 模型为准，交付情况见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。

当前已实现的默认存储为 `backend/paper_reader.db` 和 `backend/storage/{paper_id}.pdf`。Alembic 最新版本 `0007_intelligence` 新增智能分析状态／报告、持久化任务和模型调用缓存；`0005_import_metadata` 的书目来源／警告与 `0006_arxiv_revision` 的实际 PDF 版本继续保留。以下标为「当前」的字段以实际 ORM／迁移为准；其余完整目标路径、实体和冲突表尚未全部落地。迁移与真实模型验证的执行结果分别见实施状态与 [intelligence-validation.md](intelligence-validation.md)。

## 1. 目标存储约定

主数据库为 `data/workspace.db`，由 Alembic 管理迁移；原始 PDF 位于 `data/library/{paper_id}/original.pdf`，解析缓存和缩略图位于同目录。所有表使用 UUID 字符串主键、UTC `created_at/updated_at`，软删除字段仅用于用户可恢复的实体。

来源枚举统一为：`paper`、`ai`、`user`、`external_metadata`。关系来源统一为：`metadata`、`explicit`、`llm_inferred`、`user`。

## 2. 核心表

### papers

`id, title, abstract, year, venue, doi, arxiv_id, source_url, file_path, file_sha256, page_count, language, reading_status, is_favorite, analysis_status, parse_status, last_read_page, created_at, updated_at`。

`reading_status`：`unread|skimming|reading|read|important`；`analysis_status`：`none|queued|running|ready|failed`；`parse_status` 同理。对 `file_sha256` 建唯一索引，避免重复导入。

当前 ORM 使用 `pdf_path` 和唯一 `sha256` 保存文件路径与内容哈希；书目字段为 `title, year, venue, doi, arxiv_id`，作者按 `paper_authors.order_index` 读取。新增 `source_url` 保存用户输入的下载来源；`metadata_sources_json` 按 title/authors/year/venue/doi/arxiv_id 记录 `pdf_layout`、`pdf_metadata`、`pdf_text`、`arxiv_identifier`、`source_url`、`arxiv`、`crossref`、`filename` 或 `manual`。`metadata_warnings_json` 保存 provider 失败及原文块不能安全匹配等警告。API 将这两项 JSON 解码为 `metadata_sources` 对象和 `metadata_warnings` 数组。

手动 PATCH 只将提交的书目字段标为 `manual`；手动清空 nullable 字段也保留该来源。重新识别跳过 manual 字段，不替换现有 chunk ID、原文、bbox、个人 notes 和 translations。arXiv 权威字段的 year 为首次提交年份，PDF 本地日期另有 `pdf_text` 或 `arxiv_identifier` 来源；当前没有独立 revision_year 字段。

当前新增智能分析列为 `intelligence_status VARCHAR(32) NOT NULL DEFAULT 'unanalyzed'`、nullable `intelligence_report_json TEXT` 与 `intelligence_analyzed_at DATETIME`。`intelligence_status` 是 `unanalyzed|queued|running|completed|partial|failed|cancelled`，独立于 `reading_status` 和已有本地 `analysis_status`；Mock 原文摘录即使 ready 也不标远端智能分析已完成。API 解码为 `intelligence_report` 并附最新 `intelligence_task`，不返回内部 worker lease。

### authors / paper_authors

`authors(id, name, normalized_name, institution_id, homepage, orcid, semantic_scholar_id, openalex_id, dblp_url, created_at, updated_at)`。

`paper_authors(paper_id, author_id, author_order, is_corresponding)`。唯一键为 `(paper_id, author_id)`，保留顺序以支持第一作者展示。

### institutions / research_groups

保存 `name, normalized_name, country, homepage, external_ids`；`research_groups` 通过 `institution_id` 关联。作者与机构的历史关系可扩展 `author_affiliations(author_id, institution_id, group_id, start_year, end_year, source_evidence_id)`。

### collections / collection_papers / tags

`collections(id, name, description, color, is_archived, created_at, updated_at)`；`collection_papers(collection_id, paper_id, position, added_at)`；`tags(id, name, normalized_name)`；`paper_tags(paper_id, tag_id)`。Collection 删除采用归档，论文关系可重复添加前由唯一约束拦截。

### pages / paper_chunks

`pages(id, paper_id, page_number, width, height, text, created_at)`。

`paper_chunks(id, paper_id, page_id, paragraph_id, section, block_type, ordinal, text, bbox_json, token_count, embedding_ref, created_at)`。

`paragraph_id` 在单篇论文内稳定；`bbox_json` 保存 `[x0,y0,x1,y1]`，坐标系与 PDF.js 映射约定写入 parser 版本。对 `(paper_id, ordinal)`、`paper_id/page_id` 建索引。SQLite FTS5 虚表 `paper_chunks_fts(chunk_id UNINDEXED, paper_id UNINDEXED, section, text)` 与 chunks 同步。

## 3. 结构化分析与证据

### paper_analysis

`id, paper_id, analysis_version, provider, model, prompt_version, status, payload_json, error_message, created_at, updated_at`。`payload_json` 保存经过 schema 校验的 Paper Card，禁止把未校验的模型响应直接提供给前端；同一论文可保留多版本，当前版本通过 `status=ready` 和最新时间确定。

上述多版本模型是目标。当前 `paper_analysis` 以 `paper_id` 为主键，每篇保存一张当前卡片：legacy 摘要字段、`card_json`、`provider`、`mode`、`model_version`、`prompt_version` 与 `evidence_ids_json`。新全文任务从可验证的分窗口抽取结果逐层归纳，通过引用校验后才替换当前卡片和机器 evidence；失败或取消保留已有结果，个人 notes 独立保存。卡片的模型写作仍标 AI，总结引文存在只说明来源匹配，不证明其语义必然成立。未知字段保留 null／空数组。

### evidence

`id, paper_id, page_id, chunk_id, page_number, section, source_text, bbox_json, content_type, confidence, source_type, locator_status, created_at`。

`content_type`：`claim|summary|translation|answer|relation|note`；`locator_status`：`exact|approximate|unavailable`。Evidence 可被多个分析项复用，`source_text` 保存生成时的原文快照，防止解析器升级后历史结果失去可审计性。`confidence` 范围 0–1，用户内容可为空。

### analysis_items

为避免 JSON 无法查询，Paper Card 的重要字段拆成可检索项：`id, analysis_id, field, ordinal, content, item_type, source_type, confidence`；多对多表 `analysis_item_evidence(item_id, evidence_id)`。例如 `field=contributions`、`item_type=claim`。

## 4. 知识图谱实体与关系

MVP 允许先使用 `concepts`、`methods`、`datasets`、`metrics`、`problems`、`claims`，未来继续加入 Experiment、Result、Project、Venue 等。

每种实体至少包含 `id, name, normalized_name, description, aliases_json, created_at, updated_at`。`claims` 额外包含 `paper_id, statement, polarity`。

统一关系表：

```text
edges(
  id,
  source_id, source_type,
  relation,
  target_id, target_type,
  evidence_id,
  confidence,
  relation_source,
  created_at, updated_at
)
```

允许的 relation 包括 `cites, authored_by, affiliated_with, proposes, uses, extends, improves, inspired_by, compared_with, solves, evaluated_on, measured_by, supports, contradicts, requires_concept, related_to`。`(source_id, source_type, relation, target_id, target_type)` 建唯一索引；同一关系若有多条证据，使用 `edge_evidence(edge_id, evidence_id)` 扩展。

Citation Graph 的明确引用边应来自 `metadata` 或 `explicit`；Method Lineage/Concept Graph 的推断边必须显示 `AI inferred`，用户确认后可复制为 `user` 边并保留原推断记录。

## 5. 笔记与阅读行为

`notes(id, paper_id, collection_id, page_id, chunk_id, title, content, note_type, source_type, pinned, created_at, updated_at)`。

`note_type`：`user_note|reading_note|research_idea|question|todo|connection`。用户笔记和论文事实永不共用同一字段；引用论文时通过 evidence/chunk 外键连接。可选 `reading_sessions(id, paper_id, started_at, ended_at, start_page, end_page)`，用于最近阅读与后续统计。

## 6. 外部元数据、任务和设置

`external_identifiers(id, paper_id, provider, external_id, url, raw_json, fetched_at)` 用于 OpenAlex/Semantic Scholar/Crossref 等来源；`metadata_conflicts` 保存不同 provider 的冲突字段，待用户确认。

上述独立 external_identifiers/metadata_conflicts 表是目标。当前 arXiv/Crossref 查询已经可用，结果保存到 papers 的书目字段、字段来源与警告；不保存完整外部响应，也没有完整冲突历史／作者机构网络数据库。

通用 `jobs(id, type, entity_id, status, progress, error_code, error_message, started_at, finished_at, created_at)` 和 `settings(key, value_json, updated_at)` 仍是目标。当前实际智能分析任务、缓存和设置如下。

### 当前 intelligence_tasks

`id, paper_id, status, phase, run_token, completed_steps, total_steps, report_json, error, created_at, updated_at`。`paper_id` 外键级联到 papers；状态为 `queued|running|completed|partial|failed|cancelled`。SQLite 部分唯一索引 `uq_intelligence_active_paper` 对 `status IN ('queued','running')` 的 `paper_id` 建唯一约束，同一篇不能同时入两个活动任务。`run_token` 是 worker lease，不能当作 API key；API 不暴露它。

单后台 worker 用短事务更新阶段，网络请求不持有 ORM 事务。内部阶段含 structure、extract、reduce、synthesize、complete；重启将 interrupted running 转为 queued/recovered。取消条件化更新状态，worker 在每个模型调用前后检查 lease／取消；已经发出的 HTTP 不能撤回，取消后仍记录该调用的 usage，但不得覆盖卡片。失败保留安全错误及已完成阶段的报告，不无限自动重试。

`report_json` 保存文本覆盖（total／processed chars、windows、complete）、结构索引、通过核验的事实／citation 数、invalid_entries、accepted_card_fields、missing_fields、partial、model、prompt_version、usage 和 result_fingerprint。Usage 使用服务报告值，缺失保持未知；缓存命中与远端请求分开计数。`source_authenticity=locally_verified` 和 `semantic_verification=not_automatically_proven` 明确区分原句匹配与语义支持。Completed 可仍有 missing_fields，不能解释成所有卡片字段已知。

任务由 `POST /api/intelligence/tasks` 接收 `{paper_ids, force:false}`（最多200个），GET 列表读取进度，`POST /api/intelligence/tasks/{id}/cancel` 请求取消。文件／链接导入的 `analyze` 默认 false；明确启用且有远端 provider 时才入队。重复请求复用已有活动任务；相同 completed 结果指纹可直接返回完成任务。Force 可重新入队，但完全一致的阶段请求仍使用缓存。

### 当前 model_call_cache

`key VARCHAR(64) PRIMARY KEY, operation VARCHAR(100), response_json TEXT, usage_json TEXT, model VARCHAR(200), created_at`。缓存键为 operation、system/payload 内容、输出预算、provider、endpoint、model、wire_api、reasoning effort、completion parameter 与 JSON mode 的 SHA-256，不包含凭证。`response_json` 保存解析后的模型 JSON，`usage_json` 保存净化后的 usage；消费者核验失败会移除不能重用的结果。

全文处理以约20,000字符窗口覆盖每个实际 chunk，超长块按精确偏移拆分；每窗口最多128个片段。归纳组预算为24,000字符，最多8层，无法收敛时安全失败并保留已有结果及阶段缓存，不静默跳过后半文。结果指纹另包含源 chunk ID／全文／page／section／bbox、页面尺寸、算法和提示词，用于防止原文或配置变化后复用旧完成状态。

### 当前只读文献员与来源契约

`POST /api/intelligence/ask` 接收 question、collection_id、paper_ids、有限 history；question 最大4,000字符、显式论文最多50篇、history schema最多12条，实际模型上下文只取最近6条，每条末4,000字符。未指定论文的全库范围排除 demo，指定论文必须存在并属于指定集合。文献员读取 metadata、FTS5、当前 card 和 notes，由模型提出有限查询词与候选 ID；没有改库、任意 SQL、shell 或外部检索工具。只读指研究资料：模型请求缓存可写 SQLite，论文／笔记／集合不会由回答自动修改。

每轮目录最多200篇，目录 summary 截取600字符；最多5个查询、12篇候选、72个来源、来源正文合计48,000字符，单来源最多6,000字符。检索报告标 `retrieval_is_partial`、候选 IDs、查询词、sources／characters 和目录截断，比较覆盖不全时提示。有限上下文不能证明库内全部不存在，更不能证明文献全球不存在。

来源 ID 为 `chunk:{id}`、`note:{id}`、`metadata:{paper_id}`、`card:{paper_id}`，类型是 paper／user／external_metadata／ai。`metadata` 是带字段 provenance 的本地书目记录，包含 manual 等来源，不能把整个记录视为每个字段均由外部权威核实。卡片和最近历史只作检索背景；fact／comparison／inference 的引文须来自本次提交的 paper 原文，user_note 须来自 note，metadata 须来自目录记录。Comparison 条目须引用至少两篇；引用 page/bbox 来自本地 chunk，拒绝模型自报位置及跨范围 quote。

响应包含分条 content／kind／citations、limitations、retrieved_paper_ids、coverage、usage 和 cached。请求缓存绑定本次目录、实际检索来源、问题和有限历史；每次重新读取当前研究资料，变化后的 notes／card 不沿用旧来源。文献员对话不建独立 DB conversation 表，当前 UI 仅在页面会话内保留最近轮次，刷新后不恢复；打开原文返回可继续。

### 当前设置与凭证

语言、主题、阅读位置和批次分析偏好在浏览器 localStorage；模型配置来自启动环境与 `.env`。支持 chat_completions／responses；SpacetimeAI profile 的公开地址／模型配置见 README，真实 key 不进入前端、模型缓存键、报告或 SQLite。仅注入某个进程的凭证不会被应用持久化；重启需再次由启动环境提供，或用户自行设置 `.env`／用户环境变量。设置页只展示配置，不写 key；系统 keychain 集成仍是目标。

## 7. 典型查询

- Library：`papers` 联合 `paper_authors`、`collections`、最新 `paper_analysis`，按 updated_at 分页。
- Evidence：先按 `evidence.id` 取 `page/chunk/bbox`，返回 PDF.js 坐标和 source_text。
- Collection Graph：查 `collection_papers` 集合，再以 paper ids 过滤 `edges`，按 relation_source 聚合。
- Compare：选定 paper ids，按 analysis_items.field 聚合，返回每格 content + evidence。
- Full-text：FTS5 匹配 chunk，回表取论文、页码、section、bbox。

## 8. 迁移和数据安全

初始 migration 创建上述核心表、枚举约束、外键、索引和 FTS5 触发器。每次 schema 变更必须有 up/down migration 和 fixture 兼容检查。导入文件使用 sha256；删除操作先归档数据库记录并移动文件到回收站目录，清理任务由用户显式触发。

当前自动 upgrade 到 `0007_intelligence`：增加三列、创建 intelligence_tasks 与 model_call_cache，不重建用户 PDF／notes／collections。已有 remote paper_analysis 来自旧有限上下文路径，迁移仅将其智能状态标为 partial，并写入 `{"legacy":true,"coverage":{"complete":false}}`，保留卡片内容供查看，不把历史卡片称作全文完成。Down migration 会删除智能任务／缓存及对应列；降级会丢失这些新增数据，执行前应备份。

实际备份应停止服务后复制 SQLite、同名 WAL／SHM（若存在）和原始 PDF 目录；智能报告、个人笔记、翻译和模型输出缓存也属于研究数据。`.env`／用户环境配置须自行管理；数据库备份不包含模型凭证。完整目标软删除、回收站和所有扩展知识表不据迁移说明视为已实现。


### 专题文章与后台研究（0013）

`research_control` 单例保存全局订阅连接、空闲时间、额度阈值和每小时调用次数。`research_scopes` 按 collection_id 保存是否启用和研究方向。默认关闭，显式指定官方连接后才生成；只使用 Codex，不读取付费备用路由。

`research_tasks` 保存材料指纹、原文快照、阶段检查点、尝试次数和调用记录。阶段为 synthesis → draft → review → published；状态为 queued/running/paused/completed/failed/cancelled/superseded。相同材料复用任务，变化后替代旧活动任务；恢复历史研究方向可继续被替代的任务。历史完成内容再次成为当前方向时建立新的版本任务，保留旧版本。每个阶段最多两次失败尝试，每小时调用上限另行限制；取消/重试只影响明确的任务。

`research_revisions` 追加保存标题、导语、正文、更新说明、原文引语与定位、覆盖范围和审读模型。发布前匹配原句、检查全部引用目标并核对材料指纹；失败不得覆盖前版。引文匹配不等于论断被形式证明，语义由独立模型审读和用户回到原文检验。模型调用期间不持有写事务，重启及异常保存后的下一轮均恢复 stranded running 任务。

### 研究线索与复习（0014）

`research_scopes.work_types_json` 保存选择的 `essay/connections/gaps/review/questions`，迁移默认 `["essay"]`。`research_tasks.kind` 默认 `essay`，新增 `findings` 使用 discover → assess → published；两类任务的活动状态互不替代，仍共享原额度、每小时调用预算与前台优先通道。

`research_findings` 按专题保存 `connection/gap/review/question`，内容包括标题、解释/参考答案、下一步、完整原文摘录与定位、模型；独立字段保存 unread/kept/dismissed/done、复习次数与下次时间。专题与 identity 唯一。模型沿用已有ID时可以修订标题和证据，但不会重置人工状态或复习计划。程序同时识别标题相同及正文/下一步/证据锚点相同的副本，语义复核负责其他同义表达。

`research_finding_revisions` 追加保存线索ID、任务ID、内容摘要、完整内容快照和时间。完全相同的发布重放不追加历史；改写后的解释与原文保留为新修订。状态变更不改写内容历史，也不改变后台材料指纹。「记住了」按1/3/7/14/30/60天递增；「再复习」将熟悉次数重置并安排十分钟后，均由本地程序计算。

### 阅读疑问与持久预算（0016）

`research_control.budget_json` 独立于可编辑设置保存账号预算账本。每个长窗口包含日期、首次观测基线、用量高水位、固定日额度与重置时间。它记录账号整体观测增长，不是单任务的费用表。设置保存不得清空账本；同账号换模型不另起预算。

`research_tasks.intent_key` 为可空、有索引的阅读意图身份，包含论文、问题、选段与定位。阅读任务继续使用 `kind=investigation`，通过材料中的 `origin` 保存问题笔记或原始提问身份，并产出 `research_findings.kind=reading`。同一论文跨专题只安排一次；取消、忽略和完成不自动复活。问题修改按新内容调度，原文更新可在原答案上增加修订。

检查点中的 `reused_answer` 表示同义提问关联已有答案，没有正文更新时不伪造修订。后续调度同时读取正式修订与这个关联，以保留人工决定和修订目标。`validation_draft/validation_stage` 保留未通过校验的结构化输出供有限重试；成功后清除。历史引用复用仍核对论文、页码、章节与全文片段。

### 持久段落翻译（0017）

`translation_jobs` 保存论文、selected/full 模式、固定连接 ID、provider/config/prompt 身份、模型、状态、等待原因、错误和调用账本。queued/running/paused/completed/cancelled/failed 区分排队、运行、人工暂停、完成、取消和内容失败；额度等待不算内容失败。模型密钥仍只在连接配置中。

`translation_items` 保存作业、原始/当前段落 ID、合并 aliases、原文 refs 与快照、文中顺序、优先级、页码、状态、checking/translating 阶段、有限尝试次数和错误。跨批次重叠通过 `work_item_id` 引用共享段落工作，各作业保留自己的暂停与取消意图。`translation_id` 指向既有 `translations`；不重复保存译文正文。删除论文级联删除作业与项，移除某条译文会清空结果外键。

作业内按段持久化，刷新浏览器不影响执行。恢复时 running 项回到 queued，completed 项保持。模型或原文更新时不会将旧响应写入新身份；暂停和取消不删除已有译文。暂时网络故障的 `next_retry_at` 与退避次数保存在作业账本，调度期间跳过等待中的作业。全文调用时间纳入研究与知识维护共用的小时账本。
