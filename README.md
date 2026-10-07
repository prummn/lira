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

1. 在文献库拖入或批量选择 PDF。系统校验文件、去重，解析实际文本和页码坐标；每份文件最多 50 MB。
2. 打开论文：左侧阅读原始 PDF，右侧看论文卡片、原文证据、问答与笔记。可搜索、缩放、使用目录或页码导航。
3. 点击卡片或回答中的“定位原文”，跳转到对应页面和区域。选择 PDF 文本可保存高亮、引用到笔记或解释选区。
4. 创建专题集合，编辑标签、阅读状态与收藏。领域知识提供时间线、2–4 篇比较、概念索引和已记录的论文关系。
5. 用全局搜索查找标题、作者、标签和正文，正文结果可以直接打开出处。

详细操作见 [使用指南](docs/USER_GUIDE.md)。10 篇初始示例及其作者、关系均为虚构，界面明确标注；示例 PDF 实际可读。

## 可选模型

无需 API key 即可导入、阅读、做笔记和使用真实原文摘录。`MockProvider` 只抽取当前论文中的文字；不能回答时明确拒答，也不会伪造中文翻译。

可接入支持 Chat Completions 与 JSON 输出的模型服务：

```powershell
Copy-Item .env.example .env
```

在 `.env` 填入：

```dotenv
PAPER_READER_MODEL_BASE_URL=https://api.openai.com/v1
PAPER_READER_MODEL_NAME=gpt-4.1-mini
PAPER_READER_MODEL_API_KEY=your-key
```

停止并重新运行启动脚本。脚本按数据读取 `.env`，现有进程环境变量优先。也可使用 `OPENAI_API_KEY` 作为备用 key，同时显式设置本应用的模型地址或名称；单独存在宿主环境的通用 key 不会启用远端。手动启动后端时需自行设置环境变量。

导入始终使用本地摘录。只有显式点击分析、提问、解释或翻译，才向所配置的服务发送相关文本；key 不返回浏览器。AI 总结与原文摘录、个人判断分别标注。每条生成结论的引用会核对当前论文的文本块，不能验证的引用不作为证据保存。存在引用不等于总结语义已被自动证明，阅读时仍可复核原文。

段落译文保存在 SQLite，附带完整原文、模型与提示词来源。已缓存的译文在刷新、重启或取消模型配置后仍可阅读。

分析/问答上下文最多 24 个文本块、24,000 字符，单块最多 4,000 字符；长论文的摘要可能只覆盖部分内容。端点需支持 `response_format: json_object` 与 `max_completion_tokens`。模型适配器已用隔离的响应测试验证，没有宣称真实在线模型已完成验收。

## 本地数据

默认位置：

- `backend/paper_reader.db`：SQLite 数据库。
- `backend/storage/`：原始 PDF。
- 浏览器 localStorage：语言、主题与阅读位置。

启动时自动执行 Alembic 迁移。迁移测试覆盖旧数据库分析与笔记保留。备份时先停止服务，再同时复制数据库、同名 `-wal` / `-shm` 文件（若存在）与 PDF 目录；界面 JSON 导出用于查阅元数据或集合，并非完整文件备份。

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

已实现实际 PDF 解析与阅读、可定位证据、完整卡片字段结构、三层摘要视图、源引用问答/选区解释、持久化笔记与高亮、集合、SQLite 全文搜索、基础比较/关系图/作者视图以及可选模型接入。缺少原文根据的字段保持为空，图中只显示已记录关系。

OCR、语义搜索、OpenAlex/Crossref 等外部元数据补全、自动解析引用网络、DOI/arXiv/Zotero 导入和 Tauri 安装包尚未实现。当前比较是已提取字段的对照，尚非自动跨论文综合推理。MetadataProvider 和 EmbeddingProvider 仅预留接口。

产品设计与最终验收记录见 [产品规格](docs/PRODUCT_SPEC.md)、[架构](docs/ARCHITECTURE.md)、[数据模型](docs/DATA_MODEL.md)、[实施状态](docs/IMPLEMENTATION_STATUS.md)。
