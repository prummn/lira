# Research notes that explain mechanisms

> **For agentic workers:** Execute inline with executing-plans. Preserve the existing workspace and published revisions.

**Goal:** Help a researcher recover the working intuition behind a collection, while retaining the original evidence and attractive reading UI.

**Architecture:** Keep the three-call pipeline. The reading stage produces an evidence-grounded teaching plan, the writer uses it to explain mechanisms, and the editor makes necessary factual and teaching corrections while preserving successful prose. Recipe fingerprints include the three prompt files, so a writing change creates a new finite task without editing the user's direction or deleting old essays.

**Tech stack:** FastAPI, SQLAlchemy/SQLite, official Codex connection, React/TypeScript, Playwright.

## Content contract

`teaching` contains `reader_questions` (specific questions readers should be able to answer) and `explanations`. Each explanation has `question`, `steps: [{text, source_ids}]`, and optional `example: {kind: illustrative|reported, text, source_ids}`. At least one explanation is needed; examples remain optional because not every topic needs a fictional scene. All step references must point to matched evidence. Reported examples require evidence; illustrative examples carry evidence for the underlying mechanism and are described as imagined scenarios in prose. These structural checks establish provenance, not semantic truth or literary quality.

The writer prioritizes problem → concrete execution → design judgment, choosing sections to suit the material. Length follows understanding gains, usually 1800–3200 Chinese characters. No fixed future-work section, aphorism quota, or repetitive caveat pattern. The final editor protects good explanations, checks mechanism details and evidence, and retains only limitations that materially change the interpretation.

## Tasks

- [x] Add failing backend tests for teaching references, reported versus illustrative examples, handoff through persisted checkpoints, and recipe changes preserving previous versions.
- [x] Implement `verify_teaching` and recipe fingerprinting in `research_materials.py`; call validation from the worker. Update the fixture writer to return a valid teaching plan.
- [x] Rewrite `research_synthesis.txt`, `research_draft.txt`, and `research_review.txt` around the agreed research-note priorities.
- [x] Check citation behavior in app and export. Preserve inline source buttons; export references must repeat their visible citation number alongside paper/page and quotation. Test the downloaded Markdown content in `background-research.spec.ts`.
- [x] Run focused backend tests and frontend build/browser tests. Restart the local service and generate a second Memory essay with the existing official profile, quota checks and foreground priority intact.
- [x] Read the actual second essay against original MemGPT function execution and Generative Agents reflection/planning passages. Check factual grounding, concrete intuition gains, repeated argument removal, and whether review damaged the draft. Preserve both versions. The second essay still inherited the old ending; a second iteration removed the full old prose from the writer's input and produced version3. All three versions remain available.
- [x] Restore the 180-second idle setting, verify real browser citations/version switching/export, and record evidence in `docs/superpowers/evidence/2026-10-24-research-note-teaching.md`.

## Verification

Backend: `backend/.venv/Scripts/python.exe -m pytest tests/test_background_research.py tests/test_research_policy.py -q` from backend, then full backend suite once changes stabilize. Frontend: `npm run build` and `npx playwright test tests/background-research.spec.ts --reporter=line` from frontend. Real essay review is manual and evidence-based; phrase counts are not treated as writing quality tests.
