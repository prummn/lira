# Stored source sections implementation plan

**Goal:** Repair the confirmed old-section input defect before scientific analysis without changing original sources or personal data.

**Execution:** Inline in the existing isolated science-review worktree; existing independent reviewers handle review. The user's autonomous repair authorization applies. Preserve current running/control tasks until terminal.

- [x] Freeze actual v7 Self-RAG publication failure and capture the valid model heading versus old stored label. Cancel only the three not-yet-started affected cases and retain all task outcomes.
- [ ] Add `backend/tests/test_source_sections.py`: real-PDF preparation, source identity/dimension/hash rejection, ambiguity, bibliography/notes/evidence preservation, and actual worker-before-provider recovery. Run `python -m pytest -q tests/test_source_sections.py` and confirm missing behavior fails before implementation.
- [ ] Create `backend/app/services/source_sections.py`: locally prepare unique recoverable section changes and diagnostics; no network or bibliography updates. Integrate after task lease acquisition and outside source transactions in `backend/app/services/intelligence.py`; conditionally check unchanged inputs before atomic persistence, attach diagnostics to progress/final reports. Run focused tests GREEN.
- [ ] Expose concise section-reidentification diagnostics in the existing analysis report and test both locales if product UI changes. Run complete backend, browser and build checks after integration.
- [ ] Independently review mapping, cancellation and preservation boundaries. Fix reproduced defects in the isolated worktree before promotion.
- [ ] Wait for current/control tasks to terminate; freeze outcomes, promote reviewed files, safely reload the only real worker and back up SQLite before one post-reconciliation acceptance run. Do not migrate successful caches across changed source requests.
- [ ] Audit actual published results and derived-section manifests against PDFs, prove raw-source and personal-data preservation exactly, verify actual UI navigation and cache-only reproduction. Record genuine calls, tokens and unresolved scientific scope, then commit only product/tests/docs/prompts locally.
