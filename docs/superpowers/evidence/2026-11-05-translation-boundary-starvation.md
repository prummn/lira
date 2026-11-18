# Long-paper translation queue recovery

## Reproduced issue

The final paragraph on page 2 of *A Survey of Agentic Reasoning for Large Language Models: Towards Recursively Self-Improving and Collective Agents* remained queued with zero attempts while later paragraphs completed. Selecting it manually only raised its queue priority; it did not start a separate request.

Live identifiers: paper `paper-1a30f5a2031f46d2`, paragraph `paragraph-a5865cd1415bf9d5d340a450`, translation item `translation-item-63ea5bce91724b668f8f1e08f0042c19`.

## Causes and changes

- Boundary review requires exclusive access to a paper. The scheduler previously skipped these candidates while admitting later stable paragraphs from the same paper. It now drains existing work when the next candidate needs review; other papers remain eligible.
- Candidate inspection rebuilt the entire reading projection under the shared mutation lock for each candidate. A scheduling pass now shares its paper projections. Execution still validates current source text and configuration before saving.
- Boundary review continued into unrelated neighbors after the selected paragraph's edges had been resolved. It now stops at that point, while genuine merges still expose their next unresolved edges.

## Verification

- The starvation and repeated-projection regressions failed before the queue changes and passed afterward. The unrelated-neighbor assertion failed before the boundary-review change and passed afterward.
- Final combined run: `tests/test_reading_boundary_review.py tests/test_translation_queue.py tests/test_optional_concurrency.py`: **104 passed**, one existing Starlette deprecation warning, 120.01 seconds.
- Restarted the actual workspace with `scripts/start.ps1 -Restart -NoBrowser`, retaining the database, saved translations and queued work.
- The real official-model request moved the target through checking and translating to completed. Its 934-character source received a complete Chinese translation with `gpt-5.6-sol`, saved as `translation-8fd5c3380e61436398e9`. A fresh reading-paragraphs API request returned this translation and `review_needed: false`.
- Queue completion count advanced from 37 to 38; the following page-3 item entered translating. This verifies continuation, not completion of the remaining 399 paragraphs.
- Prioritization returned HTTP 200 in 2.43 seconds. Research status returned HTTP 200 in 4.18 seconds immediately after restart and 12.301 seconds under concurrent regression-test load; long-paper projection cost remains measurable. This change does not claim constant-time scheduling or a global projection cache.

## Scope

No provider credentials, quota preferences, PDF source, or completed translation was replaced. Repeated-page-header filtering is outside this fix. Frontend code was unchanged.
