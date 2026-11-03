# Spare capacity for research

**Goal:** Keep optional research and knowledge curation moving during reading,
using spare account capacity without losing interactive priority or checkpoints.

**Architecture:** A bounded worker pool claims independent topic stages and paper
audits. Admission uses the existing shared profile gate: foreground requests
win the next slot; reading reserves one slot when effective concurrency exceeds
one; idle work can borrow every slot. Model calls run concurrently, while curation
checkpoints and graph writes serialize and reload current state.

**Tech stack:** Python threads, SQLAlchemy/SQLite, existing provider capacity gate.

- [x] Reproduce reading blockade and missing reserve in isolated regression tests.
- [x] Add reader-aware shared admission, preserving in-flight scheduled results.
- [x] Replace serial optional execution with bounded claims; exclude duplicate
  paper audits and concurrent stages in one topic; recover only orphaned work.
- [x] Merge parallel audits' progress under the checkpoint lock; enforce hourly
  reservations atomically, recheck quota and explicit cancellation at admission.
- [x] Update monitor/UI descriptions and scheduling documentation.
- [x] Run scheduler, research, translation, curation tests and frontend build;
  verify the live queue without adding test papers. Temporarily restrict new
  calls while draining before restart, then restore the original hourly budget.

## Verification and live rollout

- Backend: 260 focused tests passed; after the final independent-cancellation
  changes, 67 tests covering optional concurrency, background research and the
  research agenda passed. Provider/account tests also passed. The quota-control
  test now verifies that policy updates wake both worker pools, replacing the
  removed serial-loop event. All test stores were isolated from the live library.
- Frontend: 19 Playwright checks passed across the task monitor, background
  research and knowledge maintenance; the production build passed.
- Reviewer findings addressed: never run database-backed cancellation checks
  under the provider admission condition; reject old responses after a rapid
  cancel/retry; keep maintenance and investigation cancellation independent.
- Metadata HTTP releases the checkpoint mutex and SQLite writer. Parallel
  curation rebases progress, canonical entities, errors and usage before saving.
- Hidden example papers are excluded, including pending issues in old batches.
  Browser scope tests now import disposable PDFs rather than depend on examples
  being eligible for automatic curation.
- Live quota testing exposed an early official period reset that the local
  budget ledger missed. Reset detection now requires both a near-zero usage
  reading and a substantial extension of the official reset timestamp.
- After draining in-flight requests, restarted through the standard scripts,
  restored the original 36 calls/hour and resumed the temporarily paused batch.
- Live official capacity reached 4 / 4. The multi-paper monitor, batch-detail
  navigation and 430px viewport worked without page errors or horizontal overflow.
  Actual progress was preserved; no test papers were added to the live library.
- Some real curation calls still reported upstream or source-citation validation
  errors. Concurrency verification does not establish that every curation result
  succeeded; those failures remain visible and existing knowledge is retained.
