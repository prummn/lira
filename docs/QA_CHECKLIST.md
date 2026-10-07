# MVP 验收清单与源码审查风险

更新日期：2026-10-07（Asia/Shanghai）。最终后端 55 项、浏览器 10 项通过，strict TypeScript + Vite build exit 0。勾选项只覆盖已有执行证据的范围；多个边界输入或完整人工审计未覆盖的条目保留未勾选。审查只修改 `docs/`，实现由对应功能负责人完成。

## 1. 优先级与来源规则

P0 表示会破坏证据真实性或用户数据的交付阻塞项；P1 表示核心工作流正确性；P2 表示后续体验和扩展质量。

论文结论应记录两层信息：**内容是谁写的**（paper/ai/user/external_metadata）与**支持它的关系来自哪里**（explicit/metadata/llm_inferred/user）。有原文支持的 AI 总结仍是 AI 写作；有页码的用户判断仍是用户判断。虚构 demo、MockProvider、未知定位状态要明确标示，不能仅通过 `explicit`、0.93 置信度或“已定位”toast 制造已核实的印象。

## 2. P0：Evidence 的真实性与定位

- [ ] 导入两份内容明显不同的真实 PDF，分别打开 Reader；每篇 summary、Ask、notes、evidence 只属于对应 paper_id，切换论文后清空旧选区/旧回答/旧高亮。
- [x] 接受的模型 source_text 必须出现在本地当前论文 chunk 中；page/bbox 从本地原文块读取，伪造位置和跨论文引用被拒绝。后端引用校验回归已通过。
- [x] 点击 Evidence 后真正渲染目标 PDF 页并显示区域 overlay；浏览器真实导入场景已检查画布与定位区域。
- [ ] bbox 从解析器坐标映射到 PDF.js viewport 后准确；验证非第一页、缩放 75%/150%、旋转页和不同页面尺寸。不能只验收最常见的 A4 第 1 页。
- [x] AI paraphrase 与原文 source_text 分开展示；Card/回答保留 provider/model/prompt 来源，条目有 evidence_ids；中文Card fixture 与原文跳转已通过浏览器回归。
- [x] 对不在论文中的问题回答明确表达无法确认且无引用；浏览器 Ask 场景检查超出论文的预测问题。
- [ ] demo/fictional paper 始终有可见标签；如果 demo PDF 是程序生成的样本，明确其用途，不能声称是外部发表论文原文。
- [x] 无文本层 PDF 保留文件并标 no_text，不生成伪造分析；`test_scanned_pdf_does_not_invent_analysis` 已通过。

## 3. P0：本地数据持久化与来源隔离

- [x] 保存阅读状态、收藏、notes、Collection membership 后刷新前端仍存在；浏览器闭环已检查。
- [ ] 用生产数据目录停止并重启后端，复验以上记录；浏览器刷新不能替代完整进程重启检查。
- [x] 用户 note 使用独立 API/表/来源类型，与论文分析分离；保存、删除与 user 来源由后端及浏览器闭环覆盖。
- [x] API 返回的论文 ID 与前端显示一致，不存在前端 `p1` 与后端 `paper-001` 双重 Library；导入、阅读和笔记使用同一真实 API 数据。
- [ ] 密钥不会出现在 SQLite、响应 JSON、日志或 version control；Settings 中尚未接入的 provider 选项不能显示为已连接。
- [x] 新建库与无版本号旧库通过 Alembic 升级到 `0004_translation_cache`；旧 notes/analysis 保留，连续两次 migrate 可执行。
- [ ] 数据升级不删除用户论文、notes、collections；seed 不能因非空库而部分覆盖用户记录。

## 4. P1：PDF 导入与处理

- [ ] 文件选择、拖拽和批量导入均触发真实 multipart 请求；成功刷新 Library，失败逐文件可见。
- [ ] 上传真实 PDF、空文件、假 `.pdf`、损坏 PDF、加密 PDF、无文本层 PDF；失败后不留下“ready”论文、孤儿文件或半写入 chunks。
- [ ] 同一 PDF 二次上传按 sha256 去重；相同文件名但不同内容可分别保存。
- [ ] PDF 文件 API 根据数据库里的 paper_id 返回文件，不接受任意路径；文件不存在时返回可理解错误。
- [ ] 页码上下限、缩放、搜索、文本选择可用；切换 paper_id 时阅读页重置到有效范围。
- [ ] 缓慢解析有 loading/processing 状态；用户无法因双击生成重复记录。

## 5. P1：Collection、Graph 与 Comparison

- [ ] 创建空 Collection、添加/移除论文、再次添加、刷新后重开；列表计数、Library 过滤、graph nodes 都一致。
- [ ] Collection 中只有 0、1、2 篇论文时，Timeline/Graph/Compare 显示正确空状态，不用固定 demo 网络填充。
- [ ] graph API 返回 relation_source、evidence/locator 状态或明确来源；AI inferred 与 metadata/explicit 边在 UI 上可区分。
- [x] Citation Graph 将示例关系标为 demo，新建真实单篇集合无虚构边；浏览器已检查无已记录关系的提示。
- [ ] 对新增真实论文引用关系验收外部出处；当前并无自动可信引用/继承抽取。
- [ ] Comparison 每格来自所选论文的 analysis，不复用一份固定 results/limitations；没有字段时显示缺失，不编造 GSM8K/MATH 等实验。
- [ ] Researcher 页仅声明已知的共著/机构事实；未知主页/Scholar/ORCID 不填虚构链接。

## 6. P1：搜索、API 与状态

- [ ] Metadata 搜索覆盖标题、作者、venue、tag；FTS 用真实正文中独有的短语能返回正确 paper/page/snippet。
- [ ] FTS 处理中文、空白、标点、双引号、括号、`OR`、`*` 等用户输入，无未处理 SQL/FTS 语法异常。
- [x] 带多个匹配作者的论文只占分页一个条目：后端已修复分页前去重，`test_pagination_does_not_duplicate_authors` 回归覆盖。
- [ ] 创建标题/Collection 名仅空白时被拒绝；阅读状态/来源类型等枚举由 schema 或服务验证。
- [ ] 后端不可用时页面显示明确错误和重试，不能自动展示 demo 并让用户误以为真实数据已保存。
- [ ] mutation 成功后刷新相应 query/cache；失败时撤销乐观状态或恢复原值。
- [ ] 用户连续问不同问题或快速切换论文，过时响应不会覆盖当前 Reader。

## 7. 本轮补齐的 Card、Explain 与缓存

- [x] 完整 Paper Card 未知字段留空，每条有效条目带当前论文 evidence_ids；Mock 不从结果中猜造数据集或中文摘要。
- [x] 快速概览/结构化摘要/章节摘要展示与引用跳转可用；浏览器中文Card使用响应fixture，不能据此宣称远端中文摘要质量通过。
- [x] 真实选区执行技术解释可返回原文引用，点击回到PDF区域；StrictMode生命周期问题修复后最终回归通过。其余解释styles有后端契约测试。
- [x] 阅读位置第2页刷新恢复；前端201条分页fixture中的最后一篇可打开。
- [x] 翻译首次显式生成存SQLite，重建应用后可读缓存；没有模型时缓存可读，force生成失败保留旧结果。
- [x] 模型地址/prompt/源文本改变时不重用过期缓存；伪造chunk/跨论文访问不能读取其他缓存。
- [x] 无模型但有缓存的段落视图刷新可读，浏览器断言0次translate调用；新翻译和生成式中英文摘要需要有效模型。
- [ ] 真实远端摘要/解释/翻译质量：没有live key，本轮未验证。模拟传输通过不替代真实生成质量。

## 8. P2：界面与可访问性

- [x] zh-CN 默认 locale 可用，切换 en-US 触发真实 Settings/Library UI 更新；浏览器检查已通过。
- [ ] 审计 en-US/zh-CN 键完整性、所有页面和缺失 key fallback。
- [x] 浅色/深色主题在刷新后保留；1440/1080 Library 宽度没有页面横向溢出。
- [ ] 深色主题下完整 Reader/Knowledge 可读性与键盘交互审计。
- [ ] 1440p 和 1080p 查看 Library、Reader、Knowledge、Settings，无关键工具被裁切、长标题撑破布局。
- [ ] 输入框、tabs、图谱节点与 dialog 能用键盘操作；焦点可见，图标按钮有 aria-label。
- [ ] 按钮没有实际能力时明确标注尚未实现，不能只弹“已保存/已高亮/已导入”消息。

## 9. 本轮开始时的具体源码风险

这些是前轮基线的静态审查结果或已修复缺陷的历史记录，不表示当前代码仍存在同样问题。当前实现结果以第 10 节和 IMPLEMENTATION_STATUS 为准。

| 优先级 | 代码位置 | 观察与后果 | 最小复验 |
|---|---|---|---|
| P0 | `frontend/src/App.tsx` Reader / `data.ts` evidence | 所有论文复用全局 evidence、固定第4页和同一 Ask 回答 | 打开内容不同的两篇论文并问不同问题 |
| P0 | `backend/app/seed.py` evidence/chunks | explicit 引文对应 page 3–7，但唯一 chunk 为 page1 abstract，没有真实 PDF | 对每条 demo evidence 检查可见 demo 标签与 source chunk |
| P0 | `backend/app/models.py` Note/Evidence/Edge | 来源字段不足，evidence 缺少精确定位引用 | 检查 API 与 UI 中来源和 locator 元数据 |
| P1 | `backend/app/api/routes.py` import | 前轮仅按扩展名验证，全文件 read 后写盘，无解析/去重 | 损坏 PDF 和重复 PDF 导入 |
| P1（已修复并有回归） | `backend/app/api/papers.py` list_papers | 前轮作者 outerjoin 后分页导致重复，本轮先过滤/去重再分页 | `test_pagination_does_not_duplicate_authors` |
| P1 | `backend/app/db.py` init_db | create_all，无 SQLite FK/WAL 设置或 migration | 前轮旧库运行本轮 upgrade 并检查 FK |
| P1 | `backend/app/seed.py` edges / graph API | 相邻论文全是 extends，无证据/推断标签 | 图中检查 relation_source 与引用/演化区别 |

## 10. 最终执行记录与验证边界

| 日期 | 命令或操作 | 输入/环境 | 实际结果 | 证明范围 | 未证明事项 |
|---|---|---|---|---|---|
| 2026-10-07 | 直接调用前轮 list_papers，Python -B | 内存 SQLite；3篇×3匹配作者；limit=2 | offset=0/2/4 分别1/2/1条且跨页重复；total=3 | 前轮缺陷可复现；本轮已加入回归修复 | 不代表当前代码仍有该缺陷 |
| 2026-10-07 | npm --prefix frontend run test:e2e（主代理fresh运行） | 临时库，1440×1000 与1080宽度；部分响应fixture | 10 passed，26.2秒 | 原真实闭环及位置恢复、201条分页、Card摘要/引用、真实选区Explain、无模型缓存阅读0请求 | 不证明live生成质量或所有复杂PDF兼容性 |
| 2026-10-07 | 默认环境安装（主代理分步运行） | 本机创建backend/.venv、requirements安装；Windows npm.cmd调用修复后start -NoBrowser -InstallDependencies | exit0；脚本npm.cmd ci安装77packages | 默认依赖安装与脚本启动路径 | 不代表一次全新无中断安装 |
| 2026-10-07 | 默认start/stop + health + Vite proxy（主代理fresh运行） | start.ps1 -NoBrowser；stop等待venv子进程释放端口 | smoke exit0；health=ok/papers10；stop后立即8000/5173均未监听 | 默认本地服务启动、访问、停止和端口释放 | 不证明Tauri安装包或live模型质量 |
| 2026-10-07 | backend/.venv/Scripts/python.exe -m pytest backend/tests -q（主代理fresh运行） | 脚本默认虚拟环境 | 55passed；1条上游warning | 默认Python环境中的后端回归 | 远端仍使用MockTransport |
| 2026-10-07 | python -m pytest backend/tests -q（主代理fresh运行） | 隔离测试库；远端使用httpx.MockTransport | 55 passed；1条上游Starlette/httpx warning | 当前后端含Card/Explain/search scope/4项翻译缓存测试 | 无live key；真实生成质量未验证 |
| 2026-10-07 | npm --prefix frontend run build（主代理fresh运行） | 当前工作区 | exit0 | strict TypeScript与Vite打包 | 不单独证明浏览器行为 |
| 2026-10-07 | legacy迁移回归（55项内） | 隔离旧库，连续两次migrate | 升级到0004_translation_cache并保留notes/analysis | schema升级与历史数据保留 | 不证明生产库备份/恢复 |

启动与安装证据是修复后的分步检查；未将其描述为一轮全新、无中断安装。

