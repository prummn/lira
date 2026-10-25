# 知识网络维护助手验收 · 2026-10-25

## 交付范围

- `BackgroundResearchWorker` 复用现有唯一后台线程，维护任务与专题文章、线索任务共享阅读优先、前台队列、官方额度、小时调用上限和单并发门控。
- 维护批次保存本地确定性体检结果；模型只接收有界的可疑邻域，并以结构化 JSON 返回建议。
- 高置信度的论文内重建、证据定位修复、关系恢复可以自动应用；语义合并、拆分、关系改写和新增对象仍需明确审阅。
- 每次变更保存 `KnowledgeChange` 前后快照，支持撤销；批次支持暂停、重试和 `partial` 断点续跑，使用 `processed_issue_ids` 避免重复模型调用。
- 知识页新增“网络维护”工作台：问题队列、风险筛选、证据定位、自动修复、忽略和撤销；专题研究设置可配置维护开关、间隔、每轮调用上限和范围。

## 回归证据

```text
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_knowledge_maintenance.py backend/tests/test_knowledge_maintenance_api.py backend/tests/test_background_research.py -q
34 passed

npm --prefix frontend run build
passed

npx playwright test tests/knowledge-maintenance.spec.ts tests/background-research.spec.ts
3 passed
```

整库后端回归在本机 Windows 环境中完成 779 项通过；一次 `CodexSubscriptionProvider` 溢出夹具在整库并行压力下触发临时目录清理竞态，单独重跑该参数化测试通过。它没有产生产品逻辑失败，仍保留为环境层面的后续清理项。

## 真实库只读体检

对 `backend/paper_reader.db` 先执行现有 Alembic 迁移，再调用 `prepare_run(scope_type="library", allow_external=False, force=True)`。这一步只创建维护批次和问题记录，没有应用任何知识变更，也没有发起模型调用。

- 批次：`kmr-d62dcf6e79394493a99cf2a1`
- 范围：全库 40 篇论文
- 状态：`queued`
- 确定性问题：5 条，均为关系端点悬空或待重建
- 可自动修复：5 条
- 需要审阅：0 条
- 严重冲突：0 条
- 外部检索：关闭

这次真实体检还发现并修复了两个只会在现有库数据上暴露的问题：`intelligence_analyzed_at` 等时间字段必须按 ISO 字符串参与指纹计算；SQLite 会话关闭自动 flush 被禁用时，批次计数必须先显式 flush。修复后重新体检成功。

## 当前边界

该批次仍保持 `queued`，等待新的服务进程按额度和阅读状态执行模型邻域检查。真实库中的 5 条建议尚未自动应用；首次上线应先在维护工作台检查证据，或在备份副本上验证自动修复与撤销，再决定是否处理 live 数据。
