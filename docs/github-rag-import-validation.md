# GitHub RAG 论文清单真实导入验证

验证日期：2026-10-07。本次从真实 GitHub 清单获取论文，通过正在运行的应用逐篇执行链接导入，并检查官方书目信息、PDF 阅读和引用定位。

## 来源与完整范围

仓库：[awesome-rag/awesome-rag](https://github.com/awesome-rag/awesome-rag)。冻结提交：`cca6aa9ad7f62288eafbb99de908ca7917f36347`。

完整处理以下三份清单中的 **17 篇**，按文件顺序、文件内顺序依次导入；不把整个仓库称为已测完：

- [2023/benchmark.md](https://github.com/awesome-rag/awesome-rag/blob/cca6aa9ad7f62288eafbb99de908ca7917f36347/2023/benchmark.md)：4 篇。
- [2024/benchmark.md](https://github.com/awesome-rag/awesome-rag/blob/cca6aa9ad7f62288eafbb99de908ca7917f36347/2024/benchmark.md)：4 篇。
- [2024/survey.md](https://github.com/awesome-rag/awesome-rag/blob/cca6aa9ad7f62288eafbb99de908ca7917f36347/2024/survey.md)：9 篇。

应用中新增集合 **「RAG · 真实论文导入测试」**。原有 Attention 与演示数据保留；当前库共 28 篇，其中本次真实论文 17 篇。

## 实测结果

第一轮 **15/17 成功下载**，两篇返回 504。其中 **8 篇缺少摘要**，CRUD-RAG v2 的作者名单错误地使用最新版，15 人变成 10 人。成功下载本身不能作为识别正确的证明。

修复、重试后 **17/17 均通过原始清单链接导入**，共 **414 页、9,136 个原文块、3,478 条可回查引用**。没有通过手动编辑标题/作者制造通过结果，也没有用本地上传替代最终成功的链接导入。

| 顺序 | 论文 | 实际 PDF 版本 | 页数 | 作者数 | 最终导入 |
|---|---|---:|---:|---:|---|
| 1 | [Benchmarking Large Language Models in Retrieval-Augmented Generation](https://arxiv.org/abs/2309.01431) | v2 | 9 | 4 | 通过 |
| 2 | [RECALL](https://arxiv.org/abs/2311.08147) | v1 | 12 | 8 | 通过 |
| 3 | [ARES](https://arxiv.org/abs/2311.09476) | v2 | 17 | 4 | 通过 |
| 4 | [Ragas](https://arxiv.org/abs/2309.15217) | v2 | 8 | 4 | 通过 |
| 5 | [CRUD-RAG](https://arxiv.org/abs/2401.17043v2) | v2 | 28 | 15 | 通过，作者已修正 |
| 6 | [FeB4RAG](https://arxiv.org/abs/2402.11891) | v1 | 22 | 4 | 通过 |
| 7 | [CodeRAG-Bench](https://arxiv.org/abs/2406.14497) | v2 | 16 | 7 | 通过 |
| 8 | [Long$^2$RAG](https://arxiv.org/abs/2410.23000) | v3 | 21 | 6 | 通过 |
| 9 | [Retrieval-Augmented Generation for AI-Generated Content: A Survey](https://arxiv.org/abs/2402.19473) | v6 | 22 | 10 | 通过 |
| 10 | [A Survey on Retrieval-Augmented Text Generation for Large Language Models](https://arxiv.org/abs/2404.10981) | v2 | 37 | 2 | 通过 |
| 11 | [RAG and RAU](https://arxiv.org/abs/2404.19543) | v2 | 30 | 2 | 修复总时限后通过 |
| 12 | [A Survey on RAG Meeting LLMs](https://arxiv.org/abs/2405.06211) | v3 | 18 | 8 | 重试通过 |
| 13 | [Evaluation of Retrieval-Augmented Generation: A Survey](https://arxiv.org/abs/2405.07437) | v2 | 21 | 6 | 通过 |
| 14 | [Retrieval-Augmented Generation for Natural Language Processing: A Survey](https://arxiv.org/abs/2407.13193) | v4 | 67 | 11 | 通过 |
| 15 | [Graph Retrieval-Augmented Generation: A Survey](https://arxiv.org/abs/2408.08921) | v2 | 41 | 8 | 通过 |
| 16 | [Retrieval Augmented Generation (RAG) and Beyond](https://arxiv.org/abs/2409.14924) | v1 | 27 | 6 | 通过 |
| 17 | [A Comprehensive Survey of Retrieval-Augmented Generation (RAG)](https://arxiv.org/abs/2410.12837) | 文稿未标注 | 18 | 3 | 通过 |

版本来自实际 PDF 的 arXiv 标记；最后一篇没有标记，保留未知，不推断版本。标题、有序作者和年份由独立 HTML 读取器与对应版本的官方 citation metadata 比较，17 篇全部一致。年份使用首次提交年，不能把它当作正式发表年。官方书目标题与 PDF 自身标题可能略有差异；摘要和引用始终来自实际 PDF。

## 发现的问题与修复

1. **RGB 摘要标题旁边有示意图，标题被误判为图表内容。** 显式 Abstract 标签独立识别，不受另一栏图中文字影响；加粗的编号发现段落继续属于原 Results 章节。
2. **IEEE 行内摘要、较小字号摘要及 ACM 无标题摘要漏识别。** 支持 `Abstract—…`、`Abstract. …`；ACM 以 CCS/关键词/引用格式等前置信息作为边界，逐行定位，排除署名、地址、版权及图注。使用真实版式快照和合成边界用例验证，不按论文标题特判。
3. **长综述的参考文献改变正文字号估计。** 从开头页面估计正文，避免后半篇大量小号参考文献主导字号；37 页和 41 页 ACM 综述恢复摘要。
4. **不同版本的书目信息混用。** 下载 v2 时获取 v2 官方信息，保留规范 arXiv ID，并持久保存观察到的 `arxiv_version`。新增迁移 `0006_arxiv_revision`；原文件缺失时刷新仍使用已知版本。手动换论文编号会清除旧版本。指定版本不可用时，Crossref 不能用正式发表版的标题/作者覆盖原版本。
5. **模板占位书目被当作真实信息。** 清除非手工来源的占位 DOI 和“Make sure to enter…”会议文字；无法确认的发表信息保持未知。作者识别排除机构、图中文字和换行后的机构片段；复杂署名无法可靠识别时不拼凑作者名单。
6. **大 PDF 在慢速连接下触发固定 60 秒总时限。** RAG and RAU 约 8.6 MB，多次在 60 秒中断。PDF 下载总时限调整为 180 秒，保留逐段计时、单次网络超时、50 MB 上限、重定向/DNS/IP/TLS 校验；元数据请求预算不变。修复后原始链接 **137.2 秒**成功，取得最新 v2；v1/v2 的诊断尝试没有保存为额外文献。
7. **本地“主结果”摘录错选相关工作和示例问答。** 排除已知相关工作上下文，实验章节优先于泛化评测介绍；示意图中的问题和裸 Result 标签下的示例答案不充作主结果。FeB4RAG 的青霉素问答示例已移出主结果字段。

## 验证证据和数据保护

- 后端：`backend/.venv/Scripts/python.exe -m pytest backend/tests -q`，**153 passed（16.95 秒）**。新增用例先观察失败，再实施修复；覆盖真实版式、版本绑定、模板信息、慢速下载、原文件缺失和旧库迁移。
- 前端：严格 TypeScript 与 Vite build **exit 0（18.02 秒）**。默认 Playwright 套件 **13 passed、1 skipped（31.3 秒）**，真实 Attention/BERT/LoRA 网络场景默认跳过，不计作本次真实 RAG 的验证。
- 实际应用：17 篇逐一渲染 PDF，点击首条及末条证据，检查页码和定位 overlay；浏览器没有 pageerror。两次实际重复下载（Ragas PDF 直链、CRUD v2 abs 链接）均返回 **409**，没有新增记录。
- 独立审计：所有引用的 source_text 都能在对应 chunk 中匹配，页码和 bbox 与当前原文一致；全部原文坐标位于有效页面范围。引用可定位只证明原文来源，不证明语义分类或推断正确。
- 备份：导入前、修复前、迁移前分别通过 SQLite backup API 保存一致快照。元数据刷新保持原文块 ID、文字、页码、坐标和现有机器引用 ID；随后明确重新生成本地机器分析，会替换机器引用，不替换用户笔记。
- 原有 Attention 的所有原字段与试验前快照一致。原始用户 `test_papers/` 文件未改动，未加入版本控制。

现场材料保存在忽略目录 `.local-runtime/rag-trial/`：GitHub 清单快照、manifest、官方 HTML、PDF/SHA、每次导入结果、数据库备份、刷新前后状态、`final-audit.json`、`final-ui-audit.json`、17 张最终阅读器截图及集合截图。源码保留六组裁剪的真实布局快照作为离线回归，不提交整篇 PDF 或个人数据库。

本机可复核：`backend/.venv/Scripts/python.exe -X utf8 .local-runtime/rag-trial/verify.py --cached`，以及 `node .local-runtime/rag-trial/verify-ui.mjs`。两者均要求本次现场材料与运行中的应用；Git 仓库中的 pytest 版式回归不依赖网络。

## 仍需改进的智能分析

导入和阅读检查通过，不代表论文理解已达到科研助手的质量。本次默认 **MockProvider / extractive**，没有启用远程模型，也没有把本地摘录称作模型理解。

17 篇中方法字段仅 4 篇有本地摘录，主结果字段 12 篇有摘录。专有方法名缺少通用章节词时会留空；有些实验摘录仍是评测流程或实验设置，例如 Ragas、CRUD-RAG，不能直接视为主要结论。完整方法理解、结论提炼和跨论文综合仍需改进语义分析，并逐条复核证据。

本批链接全部来自 arXiv，不能据此宣称所有出版社、ACL/OpenReview 页面或 DOI 着陆页都能自动下载。此次也不覆盖扫描 OCR、所有旋转版式或 50 MB 以上文件。
