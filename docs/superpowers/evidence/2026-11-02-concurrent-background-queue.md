# Concurrent background scheduling

The user requested a higher default concurrency and an active, reading-first
background queue. Changes retain saved quota thresholds and all existing source,
configuration, cancellation and citation validation.

## Implementation

- Official account: default 4, editable 1–8. These are local admission settings,
  not an official account concurrency guarantee. Explicit saved limits survive
  upgrades; this installation is updated through the normal settings endpoint.
- All official profiles still share one capacity gate. Idle slots are borrowable;
  foreground requests take precedence at the next release. Lowering a limit does
  not cancel in-flight work. Waiting paragraphs can be promoted dynamically.
- Rate-limit feedback halves effective admission capacity; it recovers one slot
  per minute. The configured limit is preserved. Translation and analysis queues
  retain checkpoints and defer transient failures rather than treating them as
  permanent failures.
- Separate bounded daemon pools serve paragraph translations and paper analyses.
  A dedicated preparation lane prevents long analyses from blocking necessary
  recognition of a newly imported paper. Optional research and network mutations
  retain their serialized lane. Same-paper automatic analysis waits for its own
  pretranslation; different papers can advance independently.
- Stable paragraphs share paper access and exact-source requests deduplicate.
  Boundary review takes exclusive paper access, including direct review calls.
  Selection snapshots are revalidated after waiting and before model generation.
- Live claims prevent duplicate queue ownership, including linked selected/full
  jobs. Abandoned running items recover without restarting. Unexpected exceptions
  get bounded retries and safe messages, preserving completed translations.
- Optional translation call budgets are reserved under a short mutation lock;
  account RPCs run outside it so reader actions remain responsive.
- The background page shows active/effective official capacity and queued calls,
  including temporary reduction after rate limiting.

## Validation

- New regressions were first observed failing on the old behavior; fixes include
  full borrowing, foreground precedence, concurrent same-paper translation,
  deduplication, exclusive review, parallel analysis claims, transient failures,
  pool recovery, live priority changes and obsolete direct-selection rejection.
- Core backend batch: **273 passed**. Supplementary queue/publication/knowledge
  maintenance batch: **42 passed**, including simultaneous successful analysis
  publication with each paper retaining its own evidence and knowledge intake.
  The two batches overlap on queue regressions.
- Browser settings, background monitor and quota controls: **19 passed**,
  including reload persistence and narrow layouts. Frontend production build
  passed; the existing large-bundle warning remains.
- An independent review identified stranded running work, stale direct sources,
  boundary-lock coverage and same-instance restart hazards. Each was addressed;
  targeted regression tests cover the recovery and locking behavior.

Local logs and probe artifacts are under `.local-runtime/concurrency-docs/` and
`.local-runtime/concurrent-*.log`. They are excluded from releases.

## Live deployment and final checks

- Four bounded real official-account requests overlapped: peak generating
  processes **4**, successful results **4/4**, total elapsed **42.143 seconds**.
  This verifies this account at four; it does not establish an official ceiling.
- Deployed the verified backend and resumed the two existing pretranslation jobs.
  Final observed saved progress: SWE-agent **15/91**, SWE-smith **52/67** with
  another paragraph running. No test papers or conversations were inserted.
- Live browser showed **4/4** active official slots and one waiting request.
  Settings showed limit **4**, all eight options, and no horizontal overflow at
  520 pixels. Existing quota thresholds and hourly budget remained unchanged.
- Live profiling exposed optional research loading whole-topic material before
  admission while quota-blocked. Eligibility now precedes that expensive load;
  the final affected backend batch passed **168 tests** in 147.01 seconds.
  This batch overlaps the earlier batches and must not be added as unique tests.
- Read-only final SQLite check: integrity **ok**, **46 papers**, **34,189 chunks**,
  **5 notes**. Personal-note content digest matched the pre-change snapshot.
- Local artifacts: `official-four-result.json`, `live-final-progress.json`,
  `library-after.json`, `live-background.png`, and `live-settings.png` under
  `.local-runtime/concurrency-docs/`.
