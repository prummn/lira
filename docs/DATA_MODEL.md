# Research Intelligence Workspace 数据模型

> 文档类型：**目标数据模型**。本表清单与字段是预期 schema，不能视为当前 SQLite 已有表。前轮仅实现核心 ORM 表的简化字段；本轮已有 Alembic、证据定位与用户笔记字段，完整类型知识实体仍属于后续目标。实际表结构以当前 Alembic migration 与 ORM 模型为准，交付情况见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。

当前已实现的默认存储为 `backend/paper_reader.db` 和 `backend/storage/{paper_id}.pdf`。Alembic 最新版本 `0005_import_metadata` 仅向现有 papers 增加 `source_url VARCHAR(2048)`、`metadata_sources_json TEXT NOT NULL DEFAULT '{}'` 与 `metadata_warnings_json TEXT NOT NULL DEFAULT '[]'`，保留已有论文、分析、笔记与集合；下文的完整目标路径、实体和冲突表尚未全部落地。

## 1. 目标存储约定

主数据库为 `data/workspace.db`，由 Alembic 管理迁移；原始 PDF 位于 `data/library/{paper_id}/original.pdf`，解析缓存和缩略图位于同目录。所有表使用 UUID 字符串主键、UTC `created_at/updated_at`，软删除字段仅用于用户可恢复的实体。

来源枚举统一为：`paper`、`ai`、`user`、`external_metadata`。关系来源统一为：`metadata`、`explicit`、`llm_inferred`、`user`。

## 2. 核心表

### papers

`id, title, abstract, year, venue, doi, arxiv_id, source_url, file_path, file_sha256, page_count, language, reading_status, is_favorite, analysis_status, parse_status, last_read_page, created_at, updated_at`。

`reading_status`：`unread|skimming|reading|read|important`；`analysis_status`：`none|queued|running|ready|failed`；`parse_status` 同理。对 `file_sha256` 建唯一索引，避免重复导入。

当前 ORM 使用 `pdf_path` 和唯一 `sha256` 保存文件路径与内容哈希；书目字段为 `title, year, venue, doi, arxiv_id`，作者按 `paper_authors.order_index` 读取。新增 `source_url` 保存用户输入的下载来源；`metadata_sources_json` 按 title/authors/year/venue/doi/arxiv_id 记录 `pdf_layout`、`pdf_metadata`、`pdf_text`、`arxiv_identifier`、`source_url`、`arxiv`、`crossref`、`filename` 或 `manual`。`metadata_warnings_json` 保存 provider 失败及原文块不能安全匹配等警告。API 将这两项 JSON 解码为 `metadata_sources` 对象和 `metadata_warnings` 数组。

手动 PATCH 只将提交的书目字段标为 `manual`；手动清空 nullable 字段也保留该来源。重新识别跳过 manual 字段，不替换现有 chunk ID、原文、bbox、个人 notes 和 translations。arXiv 权威字段的 year 为首次提交年份，PDF 本地日期另有 `pdf_text` 或 `arxiv_identifier` 来源；当前没有独立 revision_year 字段。

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

`jobs(id, type, entity_id, status, progress, error_code, error_message, started_at, finished_at, created_at)` 支持导入、解析、分析、索引和翻译任务。`settings(key, value_json, updated_at)` 保存主题、语言、默认 provider 等非敏感本地设置；密钥使用系统 keychain/环境变量，不写入 SQLite。

## 7. 典型查询

- Library：`papers` 联合 `paper_authors`、`collections`、最新 `paper_analysis`，按 updated_at 分页。
- Evidence：先按 `evidence.id` 取 `page/chunk/bbox`，返回 PDF.js 坐标和 source_text。
- Collection Graph：查 `collection_papers` 集合，再以 paper ids 过滤 `edges`，按 relation_source 聚合。
- Compare：选定 paper ids，按 analysis_items.field 聚合，返回每格 content + evidence。
- Full-text：FTS5 匹配 chunk，回表取论文、页码、section、bbox。

## 8. 迁移和数据安全

初始 migration 创建上述核心表、枚举约束、外键、索引和 FTS5 触发器。每次 schema 变更必须有 up/down migration 和 fixture 兼容检查。导入文件使用 sha256；删除操作先归档数据库记录并移动文件到回收站目录，清理任务由用户显式触发。
