# 当前实现状态

更新日期：2026-10-07（Asia/Shanghai）。本文件区分代码审查、实施计划与执行验证；未附验证证据的功能不能宣称通过验收。

## 最新智能服务迭代

本轮按已批准的 [智能服务设计](superpowers/specs/2026-10-07-research-intelligence-design.md) 接入用户确认的 SpacetimeAI Responses 服务，新增全文分窗口分析、持久任务与阶段缓存、批次分析选择，以及支持全库／集合／选定论文的 AI 文献员。研究事实、书目、个人笔记与推断分别标记；单篇 Notebook 使用同一检索服务。迁移版本为 `0007_intelligence`。

主代理已在冻结源码上重新运行后端完整回归：**291 passed，39.75秒**，仅有一条既有 Starlette/httpx 上游弃用提示。默认浏览器**27 passed、1 opt-in skipped（1.7分钟）**；strict TypeScript 与 Vite 构建 **exit 0**。长论文与实际界面引用导航记录见 [智能分析验证](intelligence-validation.md)。下方第2–6节保留此前本地闭环与导入迭代的历史验收；其中153条测试、0006迁移和“尚未验证真实远端生成”描述的是当时的阶段，不能用作本轮最新结论。

真实个人库中的 RGB 和 Ragas 已生成带原文证据的卡片：RGB全部3窗口、52,810字符处理结束，1条抽取未通过核验，明确标为部分完成；Ragas全部2窗口、31,778字符处理完成且没有拒绝条目。两份卡片的217条引用逐条匹配本地原句、页码和坐标；独立科学复核未发现实质结果错误，同时记录AR聚合公式缺失、章节标签及摘要遗漏等限制。Ragas在最新编排版本再次运行全部命中阶段缓存，新增模型调用为0。ARES也完成全部4窗口、61,607字符分析，72个条目和234条引用经核验，1条无效条目被拒绝，保留partial。GraphRAG全部9窗口抽取完成，后续归纳先后遭遇事实血缘遗漏和流式请求失败，未发布新的智能卡片，成功阶段缓存和失败记录均保留；该论文的原文文献员回答及来源跳转已实际通过。最新Ragas／ARES比较提供6条论点、22条原文引用；相同问答重放没有新增调用。最新跨论文比较、空笔记拒答、书目和界面导航的具体证据以验证报告为准。

程序引用核验不自动证明结论语义，已处理全文也不表示摘要逐节无遗漏。OpenAlex/Semantic Scholar作者与引用补全、embedding语义索引、OCR、完整类型知识图谱／方法谱系和Tauri安装包仍为后续范围。

## 1. 状态口径

| 标记 | 含义 |
|---|---|
| 目标 | 产品/架构设计要求，尚不能由代码证明已落地 |
| 代码存在，未验证 | 已阅读对应实现，但没有本轮运行证据 |
| 实现中 | 本轮分工已在开发，交付结果未合并验证 |
| 已验证 | 有具体命令/操作、输入、退出结果和验证范围 |
| 缺口 | 前轮代码无法满足该目标 |

目标文档：`PRODUCT_SPEC.md`、`ARCHITECTURE.md`、`DATA_MODEL.md`、`MVP_PLAN.md`。真实实现目录目前为 `frontend/` 与 `backend/`；完整 monorepo、Tauri 封装和云服务属于目标或后续工作。

## 2. 前轮基线：已知缺口

以下结果来自本轮开始时对源码的只读审查，不是对本轮正在变化的代码的最终判断。

| 模块 | 前轮观察 | 影响 |
|---|---|---|
| 前端 API | `App.tsx` 从 `data.ts` 读取论文，收藏/阅读状态只存 React state；没有 API 接线 | 页面刷新丢失更改；前后端数据不是同一 Library |
| PDF Reader | 使用固定 HTML 模拟第 4 页；导入按钮只弹 toast | 未渲染真实 PDF，页码变化不能证明跳转成功 |
| AI / Model Adapter | Ask 使用固定回答，Settings 显示 provider 名称但没有 adapter 实现 | 缺少可替换模型边界、schema 验证与生成 provenance |
| i18n | 中文直接写在组件；无 locale 文件 | 语言选项没有对应翻译机制 |
| SQLite migration | `init_db()` 通过 `Base.metadata.create_all()` 建表；没有 Alembic 目录/版本 | 现有数据库结构升级无可靠路径 |
| Evidence | `Evidence` 无 chunk/bbox/locator 字段；全局 evidence 在所有论文间复用 | 不可证明引用来自当前论文或对应 PDF 位置 |
| Mock 数据 | 两套 mock 数据的 ID/内容不同；后端 source_text 标 explicit，但无匹配的 PDF 文本块 | 演示内容可能被误读成真实原文证据 |
| Graph 来源 | Edge 与 graph API 缺少 relation_source/evidence/confidence；seed 按相邻论文产生 extends | 演化关系缺乏可见的推断/演示标记 |
| Notes | ORM 有简化 Note 表，但没有前端持久化流程或来源类型 | 用户想法不能稳定保存，也无法和论文事实分层 |
| 搜索 | 前端只搜索内存列表，后端为元数据 SQL LIKE | 尚无正文 FTS 或真正语义搜索 |

## 3. 本轮已验证的本地闭环

主代理于 2026-10-07 完成 GitHub RAG 实测修复后的最终回归：后端 **153 passed（16.95 秒）**、默认浏览器 **13 passed、1 个真实论文 opt-in 场景 skipped（31.3 秒）**、前端 strict TypeScript + Vite build **exit 0（18.02 秒）**。本次另在个人应用中逐篇导入并检查 17 篇 RAG 论文，见 [GitHub RAG 导入测试](github-rag-import-validation.md)。此前另行启用的真实 Attention/BERT/LoRA 浏览器场景 **1 passed（测试 32.8 秒／总计 41.0 秒）**，包含三篇官方论文及 BERT 两栏章节语义修复，历史记录见 [真实论文验证](real-paper-import-validation.md)。跳过的 opt-in 不计作默认测试验证；以下说明实际验证范围与边界。

| 模块 | 已验证行为 | 实际边界 |
|---|---|---|
| Library / import | 真实 PDF 上传和 arXiv/公开 PDF 链接导入；元数据编辑／刷新；下载错误保留输入；集合归属失败可仅重试 membership | 链接需返回可公开下载的 PDF，纯 DOI 解析下载和 Zotero 尚未实现；不据此宣称所有版式/OCR 兼容 |
| Reader / Evidence | PDF.js 渲染，引用点击显示原文区域 overlay；第 2 页阅读位置刷新恢复 | 定位证明文本来自 PDF，不自动证明摘要含义成立 |
| Notes / highlights | 保存笔记、选区高亮，刷新后仍存在并可重新定位 | 内容标记 user，不成为论文 explicit 事实 |
| Collection | 创建集合、保存 membership、刷新后筛选一致 | 单篇集合图谱明确为空，不自动发明引用或继承关系 |
| Knowledge / Researchers | Timeline、Compare、概念索引、关系图与作者从 Library 数据读取 | 示例关系带 demo 来源；未知机构不推断，概念索引不是完整 typed graph |
| Ask / MockProvider | 当前论文原文引用；无支持问题拒答；未配置模型且无缓存时翻译明确不可用 | Mock 为摘录，不提供生成式中英文摘要、中文翻译或知识推理 |
| Search / pagination | FTS 匹配正文并回原文，高亮保存；Collection 过滤先于 limit；前端跨页读取 201 条并打开末条论文 | 这是全文关键词搜索，不是 embedding 语义搜索；201 条前端回归使用分页响应 fixture |
| Theme / locale | 主题刷新保留、中文/英文切换、1440 与 1080 宽度 Library 检查 | 不代表全部页面/键盘与屏幕阅读器已做完整审计 |
| Scripts / proxy | 默认 `backend/.venv`、requirements 安装、脚本内 npm.cmd ci、start/stop、health 与 Vite proxy 均已分步验证 | 结果来自 Windows 调用与端口释放修复后的分步检查；不宣称一次无中断全新安装；没有 Tauri 桌面包 |

作者搜索分页问题已经由后端修复，并有 `test_pagination_does_not_duplicate_authors` 回归覆盖。前轮的内存 SQLite 复现记录仍保留于 QA，作为缺陷历史。

## 4. 本轮新增功能的验收结果

- **完整 Paper Card 与摘要层次**：统一 schema 与字段级 evidence_ids 已实现；快速概览、结构化摘要、章节摘要和中英文摘要字段可显示。未知或无可靠引用的字段保持空值。后端逐项校验真实 chunk 引用；浏览器通过中文卡片响应 fixture 检查摘要层次与引用跳转。生成式中英文摘要需要有效模型，MockProvider 不编造摘要或翻译；真实远端生成质量未验证。
- **选区 Explain**：technical/simple/mathematical/prerequisites 模式经后端与浏览器验证。StrictMode 存活标记问题已修复，选区解释和引用跳转已纳入完整浏览器回归。未配置模型时只返回相关原文。
- **段落翻译缓存**：译文与来源、provider/model/prompt metadata 存入 SQLite。4 项后端测试用 MockTransport 检查首次生成、应用重建后读取、无模型读取缓存、force 失败保留旧结果，以及模型地址/prompt/原文变化时失效；浏览器用缓存响应 fixture 验证无模型打开/刷新段落视图且 `/translate` 请求为 0。新的中文翻译需要有效模型；已有缓存可继续阅读。
- **Collection 搜索过滤与长 Library**：后端 scope 先过滤再 limit；前端读取超过首 200 条并能打开末条记录，均有最终回归覆盖。
- **真实论文书目与下载**：独立取得三份官方 PDF 与摘要 HTML，核对完整标题、署名顺序和首次提交年份。首页解析修复许可段误作标题、跨行标题截断、LoRA 断词和旋转 arXiv 版本日期误识别。arXiv HTML/Atom 与 Crossref DOI 字段带来源，权威结果绑定官方 HTTPS 最终地址和匹配编号；网络异常降级为本地结果与警告。下载拒绝私网、未知格式及超限内容，逐重定向核查 DNS 并固定连接 IP，流式超时已回归验证。官方记录中 BERT 为 2018、LoRA 为 2021，未确认 venue 时保留未知。
- **书目编辑与安全刷新**：列表／Reader 入口可修改完整书目；只将实际变更字段标 manual。重新识别保留已保存手动更正、手动清空编号、notes、集合、收藏、阅读状态与原文锚点。未保存 draft 需确认再刷新；refresh/save 失败保留编辑。独立 browser routing 验证集合加入失败显示“论文已保存”，仅重试归属且不再次下载。
- **摘录章节选择**：编号父节上下文让 Attention 的 `6.1 Machine Translation` 正文被选为 Results 摘录；BERT 两栏内部 section 传播顺序已修复，预训练数据属于 3.1、左右栏 fine-tuning 属于 3.2、真实 11 NLP tasks 段属于 4 Experiments。独立对照 470 个 BERT chunk 的原文／顺序／bbox 和 544 个 Attention chunk 的原文／顺序／bbox／section 均完全保留。LoRA figure/table 的 Method 伪章节已消除。标题／章节抽取仍是启发式，实际样本的引用核验不证明全部版式或每个摘要字段的语义分类正确。
- **GitHub RAG 真实批次**：三份完整清单 17 篇、414 页，均通过原始 arXiv 链接导入；独立核对标题、有序作者和首次提交年份，逐篇检查 PDF 渲染与首末证据定位，两次实际重复导入均返回 409。修复八篇摘要漏识别、CRUD v2 的跨版本署名、占位书目及慢速 PDF 总时限。3,478 条引用的原文与坐标可回查，原有 Attention 所有原字段不变。本地方法仅 4/17、主结果 12/17 有摘录，部分仍是实验设置；不宣称语义理解完成。详细证据见 [GitHub RAG 导入测试](github-rag-import-validation.md)。
- **构建与迁移**：strict TypeScript + Vite build exit 0；旧库无版本号升级到 `0006_arxiv_revision` 后保留 notes/analysis，迁移可连续执行。新增列包括原始链接、字段来源、识别警告及 nullable arxiv_version。版本在原 PDF 缺失时仍保留，手动换 arXiv 编号会清除旧版本。个人库已通过 SQLite backup API 备份并升级；尚未进行完整备份恢复演练。
- **既有用户论文修复**：主代理先备份 `.local-runtime/recovery/before-paper-import-fix-20261007-113202.db`，再对原 `paper-bd976889aea34e46` 执行 metadata refresh，修复 Attention 完整标题、8 作者、2017、NIPS 与 arXiv 编号。刷新时保留 544 个 chunk 的 ID／原文／bbox 和全部 111 条旧 evidence；notes、收藏、阅读状态、标签、集合及原 PDF 哈希不变。随后显式使用本地 Mock 重分析，重新生成卡片、方法与结果及 106 条当前核验 evidence；此步会替换机器 evidence，不能宣称旧 111 条在重分析后仍全部保留。544 chunks 与所有用户笔记／状态继续不变。实际打开个人库的 metadata、PDF 和原文 overlay，没有浏览器错误；截图保存在忽略目录。

## 5. 模型适配器验证边界

已建立 MockProvider 与可配置的 OpenAI-compatible Chat Completions adapter。完整后端回归覆盖 Card、Ask、Explain、翻译缓存、默认配置与模拟远端错误契约；当前数量以第 3／6 节为准。真实 PDF／官方元数据验证与模型生成质量验收是不同事项。

默认 Provider 选择已修复：仅有宿主 `OPENAI_API_KEY`、未配置应用专用参数时，保持 MockProvider。远端需要 `PAPER_READER_MODEL_API_KEY`；也可使用通用 key，但必须显式设置 `PAPER_READER_MODEL_BASE_URL` 或 `PAPER_READER_MODEL_NAME` 至少一项。应用专用 key 优先。4 项新增回归经过 RED→GREEN，防止宿主通用 key 无意启用远端。

早期浏览器测试曾因继承宿主通用 key 触发认证失败；上述显式启用规则已修复默认模式，实际本地分析与 Ask smoke 已重新通过。

远端 adapter 的契约使用 `httpx.MockTransport` 验证：检查真实本地 chunk 引用校验、拒绝伪造/跨论文引用、model/prompt provenance、超时/认证/无效 JSON 与安全错误契约、已有结果保留。**未完成有效模型的真实推理/翻译质量验收。** 模拟传输通过不代表有效远端模型的摘要、解释或译文质量已经验收。

导入过程固定使用本地正文解析和摘录；识别到 arXiv/DOI 会请求官方书目服务，链接导入会下载 PDF，这些都不调用模型。设置远端模型不自动向模型上传论文。分析、提问、解释和逐段翻译由用户显式触发。

## 6. 验证记录与后续边界

| 检查 | 日期 | 当前证据/来源 | 结果 |
|---|---|---|---|
| 浏览器完整回归 | 2026-10-07 | 主代理 fresh `npx.cmd playwright test`（frontend 目录） | 13 passed、1 opt-in skipped，31.3 秒；含位置恢复、Card/Explain/分页/缓存阅读及链接错误／元数据保存／集合重试 |
| 后端完整回归 | 2026-10-07 | 主代理 fresh `.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q` | 153 passed，16.95 秒；1 条上游 Starlette/httpx warning，无失败 |
| GitHub RAG 真实批次 | 2026-10-07 | 个人应用逐篇 URL 导入，独立官方元数据审计及 Chromium 阅读器检查 | 17/17 成功，414 页；17 篇 PDF 与首末引用定位通过；两次重复 409；0 pageerror；Attention 原字段不变 |
| 三篇官方论文浏览器 | 2026-10-07 | 设置 `RIW_REAL_PAPER_FIXTURES` 后运行独立 opt-in 场景 | 1 passed，测试 32.8 秒／总计 41.0 秒；官方 arXiv URL、BERT/LoRA 实际文件导入，title／authors／原年份／abstract／method／results／证据跳转可用；BERT 预训练段正确归3.1、Results含11 NLP tasks且排除BooksCorpus；arXiv 直接 PDF 重复请求409 |
| 前端构建 | 2026-10-07 | 主代理 fresh `npm --prefix frontend run build` | exit 0，18.02 秒；strict TypeScript + Vite |
| 默认环境与依赖安装 | 2026-10-07 | 主代理本机创建 `backend/.venv`、安装 requirements；修复 Windows npm.ps1 调用后运行 `.\scripts\start.ps1 -NoBrowser -InstallDependencies` | exit 0；脚本内 npm.cmd ci 成功安装 77 packages |
| 默认 start/stop + health + proxy | 2026-10-07 | 主代理随后 fresh `.\scripts\start.ps1 -NoBrowser`；检查 health、papers 与 Vite proxy；运行 stop 后立刻探测端口 | smoke exit 0；health=ok、papers=10；8000/5173 均未监听 |
| 默认本地 Provider 实际 smoke | 2026-10-07 | 主代理重启默认服务，检查 settings 并实际 POST demo/analyze、提问 limitation | MockProvider / extractive / configured=false；分析成功；Ask 返回 1 条原文 citation，无出网 |
| 文档角色审查 | 2026-10-07 | 官方文件校验、只读解析、MockTransport 服务边界、独立 browser API routing、源码审查 | 权威来源／deadline／空作者／父节 Results／归属重试缺陷已复现并复核修复；详细证据见真实验证文档 |
| 个人 Attention 修复与本地重分析 | 2026-10-07 | 备份后 refresh 元数据，再显式本地 Mock 重分析；实际个人浏览器读取 | refresh 保留原 544 chunks／111 evidence；后续重分析生成 106 current evidence，用户笔记／状态／集合／原文件继续保留 |

默认启动路径的检查为修复后的分步验证：先建立虚拟环境和安装依赖，再验证默认启动及停止。Windows npm.cmd 显式调用避免 npm.ps1 误解析；stop 在虚拟环境子进程释放端口后才报告 stopped。这些结果不暗示在无任何既有环境的机器上完成过一次无中断安装。

最后配置修复后，主代理已重新启动默认服务，交付时页面运行于 `http://127.0.0.1:5173`。此记录描述交付时状态，不保证未来服务始终在线。

冻结源码最终重启后再次检查 5173 proxy／health、个人 Attention 的8作者／2017、PDF HTTP 200、544 chunks 及方法／结果均可读取。官方浏览器与个人库修复证明这些实际阅读路径，不等于全部复杂 PDF 或有效远端模型质量已验收。

OpenAlex/Semantic Scholar 作者与引用网络、embedding 语义搜索、OCR、完整作者网络、完整类型知识实体、自动可信方法谱系、Tauri 打包、云同步仍未交付；arXiv/Crossref 书目查询已经可用。当前 Timeline 在没有明确关系时只按年份显示，图谱不填造边。段落级翻译可显式调用并长期缓存；已验证缓存契约，未验证真实远端翻译质量。现有 scope 之外的事项不构成本轮已完成声明。
