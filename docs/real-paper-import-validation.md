# 真实论文导入与元数据验证

日期：2026-10-07（Asia/Shanghai）。本轮先独立下载官方论文与摘要页，建立原文参照，再验证解析与导入。本文不以 Demo 数据证明真实论文可用；实际浏览器结果由主代理补充。

## 1. 独立取得的真实文件

三个 PDF 均从 arXiv 官方页面实际 GET 下载，三份对应摘要 HTML 也已保存。六次请求均为 HTTP 200，没有触发镜像回退或重试。PDF signature、可打开性与页数均经 PyMuPDF 检查。

| arXiv ID | 官方论文标题 | 首次提交日／原始年份 | PDF 页数 | 文件字节数 |
|---|---|---|---|---|
| 1706.03762 | Attention Is All You Need | 12 Jun 2017／2017 | 15 | 2,215,244 |
| 1810.04805 | BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding | 11 Oct 2018／2018 | 16 | 775,166 |
| 2106.09685 | LoRA: Low-Rank Adaptation of Large Language Models | 17 Jun 2021／2021 | 26 | 1,609,513 |

下载来源：

- Attention：[PDF](https://arxiv.org/pdf/1706.03762)、[官方摘要页](https://arxiv.org/abs/1706.03762)。
- BERT：[PDF](https://arxiv.org/pdf/1810.04805)、[官方摘要页](https://arxiv.org/abs/1810.04805)。
- LoRA：[PDF](https://arxiv.org/pdf/2106.09685)、[官方摘要页](https://arxiv.org/abs/2106.09685)。

独立文件位于忽略目录 `D:\paper_reader\.local-runtime\research-fixtures\`：`{arxiv_id}.pdf`、`{arxiv_id}.abs.html`、`manifest.json`。Manifest 保存请求/最终 URL、HTTP 状态、字节数、SHA-256、PDF 内嵌元数据、官网标题、显示作者顺序、原始 citation_author、首次提交日期与年份来源。完整 PDF 和 HTML 不加入 Git。

| PDF | SHA-256 |
|---|---|
| 1706.03762.pdf | `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` |
| 1810.04805.pdf | `5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e` |
| 2106.09685.pdf | `e9a0d3128767db616085dc0f4e6e455e672e89af823e8ed1282793682787395a` |

已有用户文件 `D:\paper_reader\test_papers\1706.03762v7.pdf` 已保留。下载前后该文件哈希均为上述 Attention 哈希，独立官方下载与其字节完全一致；没有移动、重写或替换用户文件。

## 2. 权威元数据期望

标题、作者与原始年份来自上述官方摘要页，而非 LLM 记忆。作者列表保持官网显示顺序：

| 论文 | 按顺序的作者 |
|---|---|
| Attention | Ashish Vaswani；Noam Shazeer；Niki Parmar；Jakob Uszkoreit；Llion Jones；Aidan N. Gomez；Lukasz Kaiser；Illia Polosukhin |
| BERT | Jacob Devlin；Ming-Wei Chang；Kenton Lee；Kristina Toutanova |
| LoRA | Edward J. Hu；Yelong Shen；Phillip Wallis；Zeyuan Allen-Zhu；Yuanzhi Li；Shean Wang；Lu Wang；Weizhu Chen |

年字段在本次测试明确采用**首次 arXiv 提交年份**。Attention 当前 PDF 的页边版本日期是 2023，BERT 是 2019；这些修订日期不能替代 2017/2018 的首次提交年份。Conference publication year 是另一事实，不能不标来源地混入该字段。

来源差异需要保留：LoRA PDF 首页写 `Edward Hu`，官网是 `Edward J. Hu`；Attention PDF 首页写 `Łukasz Kaiser`，官网是 `Lukasz Kaiser`。本地解析不能凭记忆补中间名；权威补全可以使用官网元数据，但必须标记 external metadata 来源。温和的格式与变音符规范化不应改变作者次序或吞掉作者。

## 3. 当前缺陷的真实复现

独立下载的三份 PDF 均没有内嵌 title/author。已读取并渲染三份首页，保存 `.first-page.png` 作本地视觉参照；正式标题、作者区与竖排 arXiv 版本标记的位置可明确区分。

修复前调用当前生产 `parse_pdf`，只读取 PDF，不连接应用、不导入用户数据库。完整输出与解析器源码哈希保存于忽略目录 `parser-before.json`：

| 论文 | 修复前真实解析结果 | 应修正的问题 |
|---|---|---|
| Attention | 标题为 `Provided proper attribution is provided, Google hereby grants permission to`；authors 空；year 未知 | 版权许可段位于正式标题之前，“第一个文本行”不能作为标题规则 |
| BERT | 标题仅 `BERT: Pre-training of Deep Bidirectional Transformers for`；authors 空；year 未知 | 正式标题跨两行，必须合并 `Language Understanding` |
| LoRA | 标题仅 `LORA: LOW-RANK ADAPTATION OF LARGE LAN-`；authors 空；year 未知 | 正式标题跨行且单词 `LANGUAGE` 被断开，不能保留片段或多加连字符 |

LoRA 修复前章节列表还将正文长句 `experiment: if the downstream task were in a different language ...` 识别为章节标题。章节识别需要考虑布局/样式及标题长度，不能仅因正文以 `experiment:` 开头就切换章节。

这些问题已告知 parser/backend 代理。实现不得为 Attention、BERT、LoRA 在生产代码中硬编码标题、作者或年份；回归 fixture 可以保留有出处的首页片段和预期事实。

## 4. 下载与网络边界

本轮获取脚本使用既有 `backend/.venv` 的 httpx，PDF 最大 20 MiB、摘要 HTML 最大 4 MiB；连接超时 10 秒、读超时 20 秒、流式接收预算 45 秒，最多五次重定向。仅对 arxiv.org 和 export.arxiv.org 两个官方地址按次尝试。

实际结果：六个 arxiv.org 首选地址全部成功；export.arxiv.org 没有被请求。没有观察到网络失败，不把未发生的失败或镜像可用性写成已验证。

单独的用户 URL 导入、未知重定向、HTML 伪装 PDF、私网目标、超限响应和 metadata provider outage 需要后端契约测试；本次官方下载成功不能代替这些安全与降级检查。网站获取失败时应保留本地解析结果与来源警告，不能填造 bibliographic metadata。

## 5. 实际导入与浏览器验收

主代理实际执行了以下产品流程；独立审查另外核验官网下载、首页布局、原文引用与错误边界。产品场景使用真实 PDF 和实际网络，个人库修复保留原记录及用户数据。

| 场景 | 实际输入 | 实际结果 | 验证范围 |
|---|---|---|---|
| Attention 链接导入 | 官网 `https://arxiv.org/abs/1706.03762`，实际联网下载 PDF | 通过 | 完整标题、8 位作者及顺序、2017、NIPS 原文出处、摘要、方法、结果与阅读器定位 |
| BERT 本地导入 | 独立下载 1810.04805.pdf，使用实际文件上传入口 | 通过 | 完整长标题、4 位作者、2018；双栏预训练保持 3.1，结果摘录来自真正实验节的 11 NLP tasks |
| LoRA 本地导入 | 独立下载 2106.09685.pdf，使用实际文件上传入口 | 通过 | 完整标题、8 位官网作者、2021；方法／结果摘录与来源定位，图表标签不误作 Method 章节 |
| 直接 PDF 链接 | 官网 `https://arxiv.org/pdf/1706.03762` | 通过 | 实际下载相同 PDF，返回 409 重复提示；没有重复创建论文 |
| 既有用户 Attention 修复 | 原记录 `paper-bd976889aea34e46`、原 PDF | 通过 | SQLite backup 后升级；refresh 保留 544 chunks 和 111 旧 evidence；显式本地重分析生成 106 当前 evidence，用户笔记／收藏／状态／集合不变 |
| 页面与证据 | 三篇真实 PDF 的 PDF.js 与原文 evidence 跳转 | 通过 | 页面真实渲染、引用高亮覆盖原文区域，浏览器无 pageerror；个人工作台也独立打开验证 |

最终实际网络场景为 `frontend/tests/real-papers.spec.ts`，使用临时数据库，未将测试用 BERT/LoRA 导入个人库。最终执行 32.8 秒、整个 Playwright 进程 41.0 秒，1 场景通过；该场景对三篇论文逐一核对官网标题、有序作者、原始年份、摘要、方法、结果及来源定位，并明确检验 BERT 的跨栏分类。默认浏览器回归另有 13 场景通过，真实网络场景默认跳过，需显式启用。

```powershell
$env:RIW_REAL_PAPER_FIXTURES='D:\paper_reader\.local-runtime\research-fixtures'
Set-Location D:\paper_reader\frontend
npx.cmd playwright test tests/real-papers.spec.ts
```

真实运行结果保存在忽略目录 `frontend/test-artifacts/real-paper-validation.json`，包含各论文识别字段、来源、摘要长度、方法／结果原文与重复结果。截图为 `real-attention-link-import.png`、`real-1706.03762-reader.png`、`real-1810.04805-reader.png`、`real-2106.09685-reader.png`、`real-paper-library.png`；实际个人工作台截图为 `local-repaired-attention-metadata.png` 和 `local-repaired-attention-reader.png`。完整后端最终 125 passed（14.92 秒），严格 TypeScript 与生产构建 exit 0。这里验证真实 PDF、真实下载和本地摘录，没有宣称真实远端 LLM 总结／翻译质量已验收。

## 6. 独立工程审查

已对新的 `downloads.py` 与 `metadata.py` 做只读审查，使用 `httpx.MockTransport` 独立复现响应边界；这些调用没有连接应用或写入用户数据库。后端修复后已重跑原复现，并对稳定的解析器、原始 PDF 和三份官方 HTML 做独立核验。

| 范围 | 独立检查结果 | 处置状态 |
|---|---|---|
| arXiv 来源绑定 | abs 请求重定向至公开外域，最终 HTML 缺少 `citation_arxiv_id` 时，其其它 citation 字段曾被标为权威 arXiv 数据；请求论文为 1706.03762，原输出为 `Unrelated Paper`、`Author Other`、2023 | 已修复并独立重跑：即使外域给匹配 ID 也被拒绝；缺 ID 的官方 HTML 走 Atom，得到 fallback 字段 |
| 流式总时限 | 1 KiB trickle stream 每片使模拟时钟前进 1 秒，配置 deadline 5 秒；原实现等 64 KiB 缓冲形成后才检查，消费 64 片／64 秒才报 504 | 已修复并独立重跑：消费第 6 片时发现预算已超过 5 秒并报 504，未再读取剩余 94 片 |
| HTML 空作者 | 匹配 ID、有效 title/year，但 `citation_author` 仅空白时，曾产出 `authors=['']` 并可能阻止 Atom fallback | 已修复并独立重跑：清洗后无有效作者则拒绝 HTML，Atom fallback 返回真实有效作者列表 |
| 其它异常元数据 | Crossref 非法 JSON、顶层数组、`author:null` 均安全返回空结果；Atom 坏 XML、DOCTYPE、ENTITY 均安全返回空结果；HTML 不同 arXiv ID 被拒绝 | 已独立运行；这是局部契约验证，不代表真实 provider 故障已发生 |
| 年份来源 | HTML 使用首次提交 `[v1]`／`citation_date`；Atom 使用 published；已有 arXiv 年份不会被 Crossref 覆盖 | 三份已下载官方 HTML 独立调用 enrichment 全部得到正确标题、完整有序作者及 2017／2018／2021；字段来源均 arxiv、warnings 空 |

稳定后直接读取三份真实 PDF，调用 `parse_pdf` 和 `MockProvider`；仅创建内存 `PaperChunk`，没有导入数据库。下表是本地识别事实，故保留 PDF 作者写法和标题大小写；官网补全的准确性由上表及产品验收另行证明。

| PDF | 修复后本地标题／作者／年 | Abstract 字符数 | 文本块数 | 方法摘录章节 |
|---|---|---|---|---|
| Attention | 完整标题；8 位作者（PDF 写 `Łukasz Kaiser`）；2017 | 1,149 | 544 | `3 Model Architecture` |
| BERT | 两行标题完整合并；4 位作者；2018 | 1,090 | 470 | `3.1 Pre-training BERT` |
| LoRA | `LORA: LOW-RANK ADAPTATION OF LARGE LANGUAGE MODELS`；8 位作者（PDF 写 `Edward Hu`）；2021 | 1,410 | 631 | `4 OUR METHOD` |

三篇 Abstract 均有正文且没有许可段／Equal contribution 混入；每个文本块 bbox 都在其页面范围内。全部 Paper Card citation 的 chunk 都属于当前论文，source_text 均可在该 chunk 原文中验证。用户 Attention PDF 再次 SHA-256 检查仍为原哈希。几何数值合法和 citation 原文相符不替代浏览器视觉定位验收。

额外检查曾发现 Attention 的本地 `main_results` 为空：解析器正确标出了 `6 Results`，但该节直接进入 `6.1 Machine Translation` 等子节，原 provider 只按当前章节名匹配，未继承父节属性。主代理已用通用 numbered heading 层级修复；独立重跑后，Attention 结果为 `6.1 Machine Translation` 的真实 BLEU 比较摘录。三份 PDF 的中文“论文的实验结果是什么？”均能返回当前论文原文引用。

BERT 的另一个真实缺陷是两栏 section 传播交织：第 5 页左栏 `Pre-training data` 被右栏 `4 Experiments` 标题误标为实验，导致摘录分类错误。冻结源码已用通用 body columns／full-width bands 修复内部 section 传播顺序，输出仍保持原块顺序。独立逐块对照 `bert-chunk-baseline.json`，全部 470 个块的 page、content、bbox 与顺序完全相同；预训练段现在属于 `3.1 Pre-training BERT`，左栏 Fine-tuning 和右栏续段属于 `3.2 Fine-tuning BERT`，真实 `11 NLP tasks` 段属于 `4 Experiments`。当前 Results 摘录准确对应原文 `In this section, we present BERT ﬁne-tuning re-`／`sults on 11 NLP tasks.`，未改写连字符、换行或 ligature。

冻结源码的独立专项回归为 `pytest backend/tests/test_pdf_metadata.py backend/tests/test_scientific_sections.py -q`：24 passed、1 条上游 warning（0.66 秒）。再次读取三份原 PDF，全部卡片 citation 可在当前论文 chunk 原文中验证、bbox 合法；Attention 的 544 个块连 section 都与基线完全一致，LoRA 为 631 块且没有 figure／table 的 standalone `Method` 伪章节。用户 Attention 文件仍是原 SHA-256。上述验证覆盖实际样本和明确回归，不证明所有复杂版式均能正确分节，也不以原文一致性自动证明摘要语义。

独立 Chromium context 下，对全部 `/api/**` 请求做内存 routing，完成以下 UI 契约验证，没有请求或修改用户数据库：未保存 draft 第一次重新识别只显示确认，实际 refresh 次数为 0；确认后的 refresh 502 和 save 422 都保留原 draft；确认后成功 refresh 才替换 draft；URL 导入后的成功 collection PUT 使列表显示归属，且仅执行一次导入。曾复现 collection PUT 失败时同时显示“导入完成”和错误、缺少重试入口；主代理修复后已独立重跑：失败显示“论文已保存”与“重试加入集合”，重试后完整成功，仅 1 次 import、2 次 membership PUT。测试用独立 5188 Vite 实例，已关闭该实例。这些 Mock 场景不计作真实下载或真实模型效果验收。

手动编辑保护、刷新不替换用户批注锚点与端到端阅读体验仍以主代理后端／浏览器验证为准。未经运行或复核的实现不记为通过。
