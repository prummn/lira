# Research Intelligence Workspace

本地优先的科研论文阅读与知识管理工具。它把 PDF、书目信息、原文证据、论文卡片、个人笔记和跨论文检索放在同一个工作区中。

默认界面是简体中文。论文和笔记保存在本机；模型只在你主动选择智能分析、提问、解释或翻译时接收对应资料。

## 先完成一次真实工作流

### 1. 启动

需要 Python 3.11+、Node.js 20+ 和 npm。在项目根目录执行：

```powershell
.\scripts\start.ps1
```

随后打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。停止服务：

```powershell
.\scripts\stop.ps1
```

以后最简单的方式是直接双击仓库根目录的 `启动工作台.cmd`；停止时双击 `停止工作台.cmd`。这两个文件会自动绕过 PowerShell 执行策略并保留启动日志。默认使用 8000/5173；如果端口被其他程序占用，会自动选择下一个空闲端口并打开实际地址，不会停止或覆盖其他程序。

首次运行会准备后端虚拟环境并安装依赖。日志在 `.local-runtime/`。

### 2. 导入一篇论文

在「文献库」选择 PDF、拖入文件，或点击「链接导入」粘贴 arXiv 页面、arXiv PDF 或公开 PDF 直链。导入会：

- 检查文件格式、大小和重复内容；
- 解析 PDF 文本、页码、章节和可定位坐标；
- 从 arXiv 或 Crossref 补全书目信息，并保留每个字段的来源；
- 立即提供本地原文搜索和摘录。

批量导入会先让你确认文件和重复项，再选择「只导入原文」或「导入后智能分析」。这个选择可以按批次改变。单份 PDF 上限为 50 MB。扫描 PDF 可以保存文件和笔记，但没有文本层时无法自动分析；当前没有 OCR。

### 3. 阅读和核对

点击论文标题进入阅读器。左侧是原始 PDF，右侧是论文卡片、证据与笔记、问答。卡片中的每条证据都可以回到 PDF 的页码和原文区域；阅读位置、笔记、高亮、收藏和集合归属会保存在本机。

书目信息可以在列表或阅读器中修改。重新识别会保留已经保存的手动修正、原文块、笔记和集合。没有来源的卡片字段保持空白，不用占位内容猜测。

### 4. 选择智能分析

列表和阅读器会明确显示以下状态：

| 状态 | 可以做什么 |
| --- | --- |
| 仅原文 | 阅读、全文搜索、摘录和提问仍可用，尚未生成模型卡片 |
| 等待分析 / 分析中 | 任务在后台运行，当前论文仍可阅读和记笔记 |
| 已完成 | 本轮窗口处理完成，打开分析报告查看覆盖和引用 |
| 部分完成 | 有字段或条目没有通过本地核验，需要查看报告 |
| 需重试 | 本轮失败，原有卡片保留，可以重新提交 |
| 已取消 | 后续任务停止，已发布的旧卡片保留 |

分析按窗口读取全文，再从已核验事实归纳论文卡片。报告会显示处理窗口、字符量、已匹配引文、缺失字段、实际调用和服务返回的 token。完成表示任务结束，不表示论文的每个字段或每个语义结论都已经正确。

### 5. 跨论文检索

「AI 文献员」可以检索全库、集合或指定论文。回答中的论文事实、个人笔记、书目信息和模型推断会分开标注；引用可以打开原文并定位。未分析论文仍可通过本地原文参与检索。

文献员只读本地研究资料，不自动修改论文、笔记或集合。每轮都会显示检索范围和覆盖限制；“库中没有找到”不等于全球不存在。返回原文后，当前问题、范围和滚动位置会保留在页面会话中。

## 模型配置（可选）

不配置模型也能导入、阅读、搜索、保存笔记和查看原文摘录。需要模型时，直接打开应用里的「设置 → 分析与模型」：

1. 点击「使用 SpacetimeAI」或填写自己的模型 API 地址、模型名称；
2. 贴入 API key，选择 Responses / Chat Completions、推理强度和请求超时；
3. 点击「测试连接并保存」。连接测试成功后配置立即生效，不需要重启服务。

API key 只提交到本机后端，页面只显示“已保存”状态，不会返回 key；配置写入项目根目录被 Git 忽略的 `.env`，不写入 SQLite。点击「移除模型配置」可清除本机配置。批量导入论文时仍可逐批选择是否启动智能分析。

无浏览器环境或自动化部署仍可使用 `.env` 作为启动时的初始配置：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写：

```dotenv
PAPER_READER_MODEL_BASE_URL=https://api.openai.com/v1
PAPER_READER_MODEL_NAME=gpt-4.1-mini
PAPER_READER_MODEL_API_KEY=your-key
PAPER_READER_MODEL_WIRE_API=chat_completions
PAPER_READER_MODEL_REASONING_EFFORT=disabled
PAPER_READER_MODEL_TIMEOUT=600
```

也支持 Responses 协议。已确认的 SpacetimeAI profile：

```dotenv
PAPER_READER_MODEL_BASE_URL=https://spacetimeai.cc/v1
PAPER_READER_MODEL_NAME=gpt-6.1-sol
PAPER_READER_MODEL_WIRE_API=responses
PAPER_READER_MODEL_REASONING_EFFORT=xhigh
PAPER_READER_MODEL_TIMEOUT=600
```

启动时，进程环境变量优先于 `.env`。设置页保存的配置会更新当前进程并持久化到 `.env`，因此下一次启动也会自动使用。配置显示“已配置”只说明参数存在，不代表远端请求一定成功；「测试连接并保存」会在写入前发起最小请求并报告连接错误。

模型请求使用流式 Responses 或 Chat Completions，并要求返回可校验的 JSON。服务错误、超时和截断会保留原 PDF、旧卡片和失败记录；不会把未完成的结果标记为完成。取消任务只能阻止后续请求，无法撤回已经发出的请求或费用。

## 本地数据与备份

默认位置：

- `backend/paper_reader.db`：SQLite 数据库，包含书目、原文块、证据、笔记、译文和模型缓存；
- `backend/storage/`：原始 PDF；
- 浏览器 localStorage：语言、主题、阅读位置和批量分析偏好。

备份前先停止服务，再同时复制数据库、同名 `-wal` / `-shm` 文件（若存在）和 PDF 目录。「导出 JSON」只导出元数据与集合，不包含原始 PDF，也不代替完整备份。

可以用 `PAPER_READER_DATABASE_URL` 和 `PAPER_READER_STORAGE_DIR` 改变位置。配置和个人研究数据已加入 Git 忽略规则。

## 开发与验证

```powershell
python -m pytest backend/tests -q
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

浏览器测试使用临时数据库和 PDF 目录，不修改个人文献库。手动开发时可以分别运行：

```powershell
python -m uvicorn backend.app.main:app --reload --port 8000
npm --prefix frontend run dev
```

## 当前范围

已实现：实际 PDF 解析与阅读、公开 PDF 链接导入、arXiv/Crossref 书目补全、手动元数据修正、可定位证据、持久化笔记、高亮、集合、SQLite 全文搜索、分窗口智能分析、分析任务恢复与缓存、带来源的跨论文 AI 文献员、单篇问答、选区解释、段落翻译缓存、基础比较、关系图和作者视图。

暂未实现：OCR、embedding 语义搜索、OpenAlex/Semantic Scholar 作者与引用网络补全、自动引用网络解析、任意 DOI 全文下载、Zotero 导入和 Tauri 安装包。关系图只显示已记录的关系；比较矩阵只对已有字段做对照。

真实论文和 GitHub RAG 批量导入记录见 [真实论文验证](docs/real-paper-import-validation.md) 与 [GitHub RAG 导入测试](docs/github-rag-import-validation.md)。更多数据边界和验证范围见 [智能分析验证](docs/intelligence-validation.md)。
