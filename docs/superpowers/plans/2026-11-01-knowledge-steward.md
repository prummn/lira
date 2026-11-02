# Knowledge steward implementation plan

**Goal:** Have AI maintain source-grounded research objects and relations with a
small exception queue, measured against the user's actual Agent collection.

**Architecture:** Existing maintenance runs remain the persisted scheduling unit.
One paper is one bounded semantic checkpoint. Model proposals use validated
original quotes and reversible actions; deterministic endpoint repairs and
metadata enrichment precede semantic review.

**Stack:** FastAPI, SQLAlchemy/SQLite, existing model adapters, React/TypeScript.

- [x] Record actual collection audit and benchmark endpoint failing tests; repair
  predicate types in knowledge_identity/knowledge_curation.
- [x] Add failing paper-curation tests: work with no pre-existing findings,
  preserve human rejection, verify literal evidence and aliases, automatically
  confirm valid relations, undo and deduplicate completed paper checkpoints.
- [x] Implement knowledge_steward.py, provider paper-curation mode and maintenance
  integration. Reuse foreground/quota scheduling; test interruption and no-op runs.
- [x] Test and implement publication_metadata.py with local conference header and
  strict public registry identity; attach enrichment to paper checkpoint.
- [x] Implement contribution-aware graph, readable comparison, single directory,
  collapsed edges and AI curation UI; run isolated Playwright and build.
- [x] Replay real collection in a temporary online SQLite backup; run serial real
  model checks; quantify changes and evidence quality. Apply only verified,
  reversible high-confidence real-data corrections after backup.
- [x] Run relevant backend regression, UI build/browser checks, diff review and
  record exact live/deployment boundary. No broad commit or reset of dirty tree.

Production repair saved as kmr-e38eea9917eb4725a6579b5c after a fresh SQLite backup
and source-fingerprint preflight. Live API confirms 111 settled relations, 9 pending,
11 contextual annotations. New worker code is isolated-tested; live restart remains
outside this execution because of the prior approval restriction. Final UI review
passed dense-edge hit targets and contextual directory/dossier presentation.
Final: 432 backend tests, 34 knowledge UI tests, build and scoped diff checks pass.
