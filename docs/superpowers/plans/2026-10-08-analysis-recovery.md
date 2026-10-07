# Recover Failed Real-Paper Analyses

**Goal:** Resolve the observed failures through bounded recovery and evidence-checked corrections, then verify the formerly failed real papers.

**Execution:** The user authorized autonomous fixes. Work in the existing `develop` checkout, preserving `test_papers/`, the local database and the single running worker. Transport and harness edits are independent and delegated under dispatching-parallel-agents; no agent calls the real provider or restarts the service.

- [x] Read terminal trial errors and trace adapter, request cache, reduction validator and synthesis validator.
- [x] Record design, retry/correction limits, strict evidence invariants and actual acceptance criteria.
- [x] Transport: add backwards-compatible typed ProviderError metadata, classify transient errors and Retry-After, distinguish incomplete output; prove RED then GREEN in adapter tests.
- [x] Harness: test then implement stage-only retries with cancellation, bounded global recovery budget, accurate attempt usage and cache reuse.
- [x] Reduction: test then implement one failed-group correction using original facts, short aliases and mandatory parent citations; reject remaining missing lineage.
- [x] Card: test then implement one batch of rejected-slot corrections without overwriting validated slots; reject null, duplicate and foreign replacements; distinguish resolved diagnostic history.
- [x] UI: show resolved entries separately from outstanding rejection reasons and verify the behavior.
- [x] Run full backend tests, build and browser regressions; independently review the changes. Backend398 passed, browser31 passed/one opt-in skipped, build passed; independent43 passed and all reproduced findings fixed.
- [x] Back up the local database, safely reload the sole backend, and reattempt the six failed/partial real samples with stage-cache reuse. All six reached terminal states, four completed/two partial;917 original quotes and geometry/claim mappings verified. Independent PDF audits identified scientific defects that require the separate v6 review plan rather than relaxed validation.
- [ ] Document actual outcomes, usage and unresolved conditions; verify personal-data preservation and commit locally without credentials, runtime data or a push.
