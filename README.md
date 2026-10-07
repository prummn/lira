# Research Intelligence Workspace

本地优先的科研论文阅读与知识工作台。默认简体中文，提供浅色、深色与系统主题。React / TypeScript / PDF.js 前端连接本机 FastAPI；PDF、解析段落、证据、论文卡片、集合与个人笔记保存在文件系统和 SQLite。

## 启动

需要 Python 3.11+、Node.js 20+ 和 npm。在项目根目录执行：

```powershell
.\scripts\start.ps1
```

首次运行会创建 `backend/.venv` 并安装 Python 和前端依赖；随后打开 [本地工作台](http://127.0.0.1:5173)。依赖安装需要网络，安装后本地阅读与摘录模式可离线工作。端口 8000、5173 应空闲。

```powershell
# 不自动打开浏览器
.\scripts\start.ps1 -NoBrowser

# 使用已有 Python 环境
.\scripts\start.ps1 -PythonPath (Get-Command python).Source

# 停止本次启动的服务，保留数据
.\scripts\stop.ps1
```

脚本日志在 `.local-runtime/`。如果 PowerShell 执行策略阻止本地脚本，可用 `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1` 本次运行，不修改全局策略。

## 使用

1. 在文献库拖入或批量选择 PDF，或点击「链接导入」粘贴 arXiv abs/pdf 地址或公开 PDF 直链。系统校验文件、去重，解析实际文本和页码坐标；每份文件最多 50 MB。
2. 打开论文：左侧阅读原始 PDF，右侧看论文卡片、原文证据、问答与笔记。可搜索、缩放、使用目录或页码导航。
3. 点击卡片或回答中的“定位原文”，跳转到对应页面和区域。选择 PDF 文本可保存高亮、引用到笔记或解释选区。
4. 创建专题集合，编辑标签、阅读状态与收藏。领域知识提供时间线、2–4 篇比较、概念索引和已记录的论文关系。
5. 用全局搜索查找标题、作者、标签和正文，正文结果可以直接打开出处。

文件批次和链接导入都可选择「导入后智能分析」。首次默认为关闭，之后记住当前浏览器的选择，每批可调整；没有配置远端模型时该选项不可用。默认导入立即提供本地原文摘录，标为「未进行智能分析」。已导入论文可在 Library 批量选择，或在阅读器中单独启动智能分析。

「AI 文献员」可围绕问题检索全库、集合或指定论文，结合原文、书目、卡片和个人笔记回答并链接出处。它只读取研究资料，不自动改论文、笔记或集合；笔记、元数据和模型推断分别标注。未分析论文仍能检索原文，检索有数量与文本预算，不能据此证明“全部论文”或“没有相关工作”。

列表和阅读器的「论文信息」可查看、修改标题、有序作者、年份、期刊/会议及 DOI/arXiv 编号，每个字段显示来源。识别到编号后从 arXiv/Crossref 补全书目；arXiv 年份使用首次提交年份。重新识别保留已保存的手动修正、原文块 ID 和个人笔记，网络不可用时保留本地结果并显示警告。

详细操作见 [使用指南](docs/USER_GUIDE.md)。10 篇初始示例及其作者、关系均为虚构，界面明确标注；示例 PDF 实际可读。

## 可选模型

无需 API key 即可导入、阅读、做笔记和使用真实原文摘录。`MockProvider` 只抽取当前论文中的文字；不能回答时明确拒答，也不会伪造中文翻译。

可接入支持 JSON 输出的 Chat Completions 或 Responses 模型服务：

```powershell
Copy-Item .env.example .env
```

在 `.env` 填入：

```dotenv
PAPER_READER_MODEL_BASE_URL=https://api.openai.com/v1
PAPER_READER_MODEL_NAME=gpt-4.1-mini
PAPER_READER_MODEL_API_KEY=your-key
PAPER_READER_MODEL_WIRE_API=chat_completions
PAPER_READER_MODEL_REASONING_EFFORT=disabled
PAPER_READER_MODEL_TIMEOUT=600
```

模型请求超时默认为 600 秒，可按需设置为 1–1800 秒；长篇 Responses 合成可使用 1800 秒上限。

停止并重新运行启动脚本。脚本按数据读取 `.env`，现有进程环境变量优先。也可使用 `OPENAI_API_KEY` 作为备用 key，同时显式设置本应用的模型地址或名称；单独存在宿主环境的通用 key 不会启用远端。手动启动后端时需自行设置环境变量。

已确认的 SpacetimeAI Responses profile 使用以下非敏感配置；自行通过环境变量或被 Git 忽略的 `.env` 提供 key：

```dotenv
PAPER_READER_MODEL_BASE_URL=https://spacetimeai.cc
PAPER_READER_MODEL_NAME=gpt-6.1-sol
PAPER_READER_MODEL_WIRE_API=responses
PAPER_READER_MODEL_REASONING_EFFORT=xhigh
PAPER_READER_MODEL_TIMEOUT=600
```

Responses 协议在 base URL 后请求 `/responses`，使用流式传输并带 `store: false`，只接受完整完成的结果；Chat Completions 使用 `/chat/completions`。默认 `PAPER_READER_MODEL_REASONING_EFFORT=disabled` 会省略两个协议的推理参数，并优先于阶段 effort，适用于 gpt-4.1-mini 和不接受推理参数的兼容服务；支持推理的模型可显式设置 high/xhigh 等值，`none` 是实际发送给服务的 effort，不等于省略参数。较旧的 Chat Completions 服务可设置 `PAPER_READER_MODEL_COMPLETION_PARAMETER=max_tokens`，不接受 JSON mode 时可设置 `PAPER_READER_MODEL_JSON_MODE=none`，返回内容仍需通过 JSON 和引用校验。「设置」只展示实际配置，不保存或编辑凭证。

仅在某个进程中提供的 key 不会被应用写回配置文件、浏览器或 SQLite。关闭该进程后，新后端不会自动获得这份临时配置；需在启动环境重新设置，或自行配置 `.env`／用户环境变量。当前 live 会话的存在不等于下次启动已经配置好。

正文解析与本地摘录始终在本机完成；识别到 arXiv/DOI 时会查询官方书目，链接导入会下载 PDF，这些操作不调用模型。选择「导入后智能分析」、主动启动分析／提问／AI 文献员／解释／翻译时，才向所配置的模型服务发送对应资料；文献员可能包含当前范围的个人笔记。Key 不返回浏览器。每条生成结论的引用核对本地当前论文的文本块，无法验证的条目排除。引文存在不等于论断语义已被自动证明，仍需复核原文。

段落译文保存在 SQLite，附带完整原文、模型与提示词来源。已缓存的译文在刷新、重启或取消模型配置后仍可阅读。

智能分析把全部已解析文本分窗口抽取，再从通过原文核验的事实逐层归纳卡片。单后台 worker 顺序处理持久化任务，显示阶段、已处理窗口／字符、usage、引用和缺失字段；运行期间 PDF 和笔记可继续使用。失败保留已有卡片，重试复用成功阶段缓存；取消在模型 HTTP 请求之间检查，不能撤回已经发出的请求或已产生的费用。「重新分析全文」会重新建任务，完全相同的请求仍可命中缓存。

本地摘录不是模型总结；未知卡片字段保持空白。「完成」表示该轮文本窗口处理结束，不表示所有字段都有证据或所有论断已获语义证明。实际远端调用、缓存和人工原文检查的范围以 [智能分析验证](docs/intelligence-validation.md) 为准，不把模拟传输测试或少量现场样本扩大为普遍模型质量结论。

## 本地数据

默认位置：

- `backend/paper_reader.db`：SQLite 数据库。
- `backend/storage/`：原始 PDF。
- 浏览器 localStorage：语言、主题、阅读位置与批次分析偏好；文献员当前对话仅在页面会话中保留。

启动时自动执行 Alembic 迁移，当前版本为 `0007_intelligence`，新增智能分析任务、报告及不含凭证的模型结果缓存；旧远端卡片标为历史部分覆盖，不冒充全文完成。书目来源与 PDF arXiv 版本继续保留。迁移与实际数据保留的验证见实施状态。备份时先停止服务，再同时复制数据库、同名 `-wal` / `-shm` 文件（若存在）与 PDF 目录；数据库还包含个人笔记、译文及模型结果缓存。界面 JSON 导出用于查阅元数据或集合，并非完整备份。

可用 `PAPER_READER_DATABASE_URL`、`PAPER_READER_STORAGE_DIR` 改变存储位置，参考 `.env.example`。配置和本地研究数据均被 Git 忽略。

## 开发与验证

```powershell
python -m pytest backend/tests -q
npm --prefix frontend run build
# 首次运行浏览器测试前安装 Chromium
cd frontend
npx playwright install chromium
cd ..
npm --prefix frontend run test:e2e
```

测试使用临时 SQLite 和 PDF 目录，不改个人文献库；浏览器测试也隔离个人模型环境变量。手动开发可从根目录运行 `python -m uvicorn backend.app.main:app --reload --port 8000`，另一个终端运行 `npm --prefix frontend run dev`。

结构：`frontend/src/{components,pages,lib,locales}`、`backend/app/{api,providers,services}`、`backend/migrations`、`prompts`、`scripts`、`docs`。

## 当前范围

已实现实际 PDF 解析与阅读、arXiv/公开 PDF 链接导入、arXiv/Crossref 书目补全与手动修正、可定位证据、分窗口智能分析和三层卡片、持久化任务与缓存、带来源的跨论文 AI 文献员、单篇问答／选区解释、持久化笔记与高亮、集合、SQLite 全文搜索、基础比较／关系图／作者视图，以及 Chat Completions／Responses 接入。缺少原文根据的字段保持为空，图中只显示已记录关系。真实 Attention、BERT、LoRA 的下载来源与验收记录见 [真实论文验证](docs/real-paper-import-validation.md)。

另从 `awesome-rag/awesome-rag` 的三份完整清单逐篇测试 17 篇 RAG 论文，最终全部通过原始链接导入，共 414 页；标题、有序作者、原年份、阅读器及引用定位均经过实际核验。修复摘要漏识别、版本书目混用、模板占位信息和慢速下载超时，记录见 [GitHub RAG 导入测试](docs/github-rag-import-validation.md)。本地方法与结果摘录仍有缺失或语义分类不准，需要复核原文。

OCR、embedding 语义搜索、OpenAlex/Semantic Scholar 作者及引用网络补全、自动解析引用网络、纯 DOI 编号解析下载、Zotero 导入和 Tauri 安装包尚未实现。DOI 元数据查询不等于任意 DOI 均能下载全文。领域知识的比较矩阵仍是已提取字段对照；AI 文献员可另行生成带原文引用的跨论文比较，须检查其覆盖限制。EmbeddingProvider 仅预留接口。

产品设计与最终验收记录见 [产品规格](docs/PRODUCT_SPEC.md)、[架构](docs/ARCHITECTURE.md)、[数据模型](docs/DATA_MODEL.md)、[实施状态](docs/IMPLEMENTATION_STATUS.md)。
