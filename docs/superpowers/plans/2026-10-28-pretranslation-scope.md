# 后台预译正文范围优化实施计划

> **For agentic workers:** Execute this plan task-by-task with the repository's TDD and verification workflows.

**Goal:** 让“后台预译全文”只处理首次附录或参考文献标题之前的正文与图表说明，并清楚显示被跳过的后续内容；手动选择的段落保持不受限制。

**Architecture:** 在翻译队列服务中增加纯确定性的 section 边界扫描，同时检查阅读视图已过滤掉的原文标题块，先找到第一个附录或参考文献标题，再截断 full job 的段落集合。任务快照保存范围统计和跳过原因，序列化到后台任务与阅读器；selected job 继续按用户明确的 paragraph IDs 工作。前端只消费统计字段并展示“正文范围 / 已跳过”提示，不改变现有翻译调度。

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, React, TypeScript, Playwright, pytest。

---

### Task 1: Define and test the section cutoff classifier

**Files:**
- Modify: `backend/app/services/translation_queue.py`
- Test: `backend/tests/test_translation_queue.py`

- [x] **Step 1: Write failing tests** for numbered and multilingual appendix/reference headings, inline section names that are not headings, and papers with no cutoff heading. The expected full set must stop before the first cutoff while selected mode remains unchanged.

- [x] **Step 2: Run the focused tests** with `python -m pytest backend/tests/test_translation_queue.py -q`; confirm the new cutoff tests fail because the current implementation only filters references.

- [x] **Step 3: Implement a deterministic helper** that normalizes a paragraph section label, recognizes `Appendix`, `Appendices`, `Supplementary`, `References`, `Bibliography`, `参考文献`, and common numbered/lettered prefixes, and returns the first cutoff index. Apply it only when `mode == 'full'`; retain prose/caption filtering and leave selected mode unchanged.

- [x] **Step 4: Run the focused queue tests** and confirm all pass, including existing boundary-review and priority tests.

### Task 2: Persist and expose skipped-range statistics

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/migrations/versions/0018_translation_scope.py`
- Modify: `backend/app/services/translation_queue.py`
- Existing per-paper and monitor APIs serialize dictionaries directly; no schema class change is needed.
- Test: `backend/tests/test_translation_queue.py`
- Test: `backend/tests/test_migrations.py`

- [x] **Step 1: Add failing persistence tests** asserting a full job records eligible paragraph count, skipped paragraph count, and a stable skip reason, while selected jobs report zero skipped paragraphs.

- [x] **Step 2: Run the migration and queue tests** to verify the new fields are absent/failing before implementation.

- [x] **Step 3: Add nullable/default-safe job fields and migration** so existing databases upgrade without rewriting existing jobs. Populate the fields at enqueue time and include them in both per-paper job serialization and global monitor summaries.

- [x] **Step 4: Run migration, queue, and persistence tests** and confirm old databases and existing active jobs remain readable.

### Task 3: Make the reader and background monitor explain the scope

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/TranslationQueueProgress.tsx`
- Modify: `frontend/src/pages/BackgroundTasksPage.tsx`
- Modify: `frontend/src/components/TranslationPanel.tsx`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/translation-reading.spec.ts`
- Test: `frontend/tests/background-tasks.spec.ts`

- [x] **Step 1: Add failing browser assertions** that a full job shows a scope label and skipped count, while a selected job does not claim that appendix/reference content was skipped.

- [x] **Step 2: Run the focused Playwright tests** to confirm the assertions fail against the current response shape/UI.

- [x] **Step 3: Extend the shared job type and render a compact scope line**, for example “正文范围 · 已跳过 32 段附录/参考文献”; use the existing muted progress styling and keep the progress bar focused on eligible work.

- [x] **Step 4: Run translation-reading and background-task Playwright suites** at the normal single-worker configuration.

### Task 4: Verify the complete change

**Files:**
- Modify: `docs/USER_GUIDE.md`
- Modify: `README.md`

- [x] **Step 1: Document that background full pretranslation ends before the first appendix/reference section, while explicit selected translation remains available.**

- [x] **Step 2: Run `python -m pytest backend/tests -q`, `npm run build`, and the focused Playwright suites.**

- [x] **Step 3: Run `git diff --check` and inspect the migration/model/API diff for accidental changes to credentials, stored PDFs, or existing translation text.**


验证记录见 `docs/superpowers/evidence/2026-10-28-pretranslation-scope.md`。
