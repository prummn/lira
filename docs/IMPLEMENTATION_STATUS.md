# 当前实现状态

更新日期：2026-10-07（Asia/Shanghai）。本文件区分代码审查、实施计划与执行验证；未附验证证据的功能不能宣称通过验收。

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

主代理于 2026-10-07 完成最终回归：后端 **55 passed**、浏览器 **10 passed（26.2 秒）**、前端 strict TypeScript + Vite build **exit 0**。文档角色已阅读对应测试的操作与断言，并检查 Playwright 最近运行记录为 passed；以下说明真实验证范围与边界。

| 模块 | 已验证行为 | 实际边界 |
|---|---|---|
| Library / import | 真实 PDF 导入、阅读状态、收藏；损坏 PDF 报错且不增加论文 | 不据此宣称所有复杂版式/OCR 兼容 |
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
- **选区 Explain**：technical/simple/mathematical/prerequisites 模式经后端与浏览器验证。StrictMode 存活标记问题已修复，选区解释和引用跳转已在最终 10 项回归中通过。未配置模型时只返回相关原文。
- **段落翻译缓存**：译文与来源、provider/model/prompt metadata 存入 SQLite。4 项后端测试用 MockTransport 检查首次生成、应用重建后读取、无模型读取缓存、force 失败保留旧结果，以及模型地址/prompt/原文变化时失效；浏览器用缓存响应 fixture 验证无模型打开/刷新段落视图且 `/translate` 请求为 0。新的中文翻译需要有效模型；已有缓存可继续阅读。
- **Collection 搜索过滤与长 Library**：后端 scope 先过滤再 limit；前端读取超过首 200 条并能打开末条记录，均有最终回归覆盖。
- **构建与迁移**：strict TypeScript + Vite build exit 0；旧库无版本号升级到 `0004_translation_cache` 后保留 notes/analysis，迁移可连续执行。生产库备份/恢复演练不在本轮测试范围内。

## 5. 模型适配器验证边界

已建立 MockProvider 与可配置的 OpenAI-compatible Chat Completions adapter。最终后端 55 项测试通过，覆盖 Card、Ask、Explain、翻译缓存及模拟远端错误契约；此前 40/51 项和浏览器 6/9 项均为历史阶段数量，最终结果以本节与第 6 节为准。

远端 adapter 的已有验证使用 `httpx.MockTransport`：检查真实本地 chunk 引用校验、拒绝伪造/跨论文引用、model/prompt provenance、超时/认证/无效 JSON 与安全错误契约、已有结果保留。**没有可用 live key，未执行真实远端 API 调用。** 翻译或远端解释的生成质量、外部端点兼容性与真实计费均未验证。

导入过程固定使用本地解析和摘录；设置远端模型不自动上传论文。分析、提问、解释和逐段翻译由用户显式触发。

## 6. 验证记录与后续边界

| 检查 | 日期 | 当前证据/来源 | 结果 |
|---|---|---|---|
| 浏览器完整回归 | 2026-10-07 | 主代理 fresh `npm --prefix frontend run test:e2e` | 10 passed，26.2 秒；含位置恢复、Card/Explain/201条分页/缓存阅读 |
| 后端完整回归 | 2026-10-07 | 主代理 fresh `python -m pytest backend/tests -q` | 55 passed；1 条上游 Starlette/httpx warning，无失败 |
| 前端构建 | 2026-10-07 | 主代理 fresh `npm --prefix frontend run build` | exit 0；strict TypeScript + Vite |
| 默认环境与依赖安装 | 2026-10-07 | 主代理本机创建 `backend/.venv`、安装 requirements；修复 Windows npm.ps1 调用后运行 `.\scripts\start.ps1 -NoBrowser -InstallDependencies` | exit 0；脚本内 npm.cmd ci 成功安装 77 packages |
| 默认 start/stop + health + proxy | 2026-10-07 | 主代理随后 fresh `.\scripts\start.ps1 -NoBrowser`；检查 health、papers 与 Vite proxy；运行 stop 后立刻探测端口 | smoke exit 0；health=ok、papers=10；8000/5173 均未监听 |
| 默认 venv 后端回归 | 2026-10-07 | `.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q` | 55 passed；1 条上游 warning |
| 文档角色审查 | 2026-10-07 | 文件校验、内存 SQLite 分页复现、源码审查 | 记录缺陷，不代替 UI/Provider 验收 |

默认启动路径的检查为修复后的分步验证：先建立虚拟环境和安装依赖，再验证默认启动及停止。Windows npm.cmd 显式调用避免 npm.ps1 误解析；stop 在虚拟环境子进程释放端口后才报告 stopped。这些结果不暗示在无任何既有环境的机器上完成过一次无中断安装。

外部 Metadata Provider、embedding 语义搜索、OCR、完整作者网络、完整类型知识实体、自动可信方法谱系、Tauri 打包、云同步仍未交付。当前 Timeline 在没有明确关系时只按年份显示，图谱不填造边。段落级翻译可显式调用并长期缓存；已验证缓存契约，未验证真实远端翻译质量。现有 scope 之外的事项不构成本轮已完成声明。

