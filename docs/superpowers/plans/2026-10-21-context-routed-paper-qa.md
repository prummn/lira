# Context-Routed Paper Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper Q&A behave like a capable reading partner: retain the selected page or passage as the anchor, retrieve related evidence across the paper when the question requires it, and produce a natural answer that separates evidence from inference without weakening citation validation.

**Architecture:** Add a bounded, deterministic context router in the explanation service. It will score paper chunks against the user question and anchor, add related sections for mechanism/relationship questions, and expose a single staged expansion hook to the provider. Replace the terse visual prompt with a response contract that asks for a direct answer, evidence-backed facts, clearly marked inferences, and unresolved points; the existing backend citation verifier remains authoritative. Keep the API response compatible unless optional structured fields are needed by the UI.

**Tech Stack:** FastAPI, SQLAlchemy models, Python provider harness, pytest, existing React/Playwright tests.

---

### Task 1: Capture the real failure mode with routing tests

**Files:**
- Modify: `backend/tests/test_paper_card.py`
- Test: `backend/tests/test_paper_card.py`

- [ ] **Step 1: Write the failing test** for a visual mechanism question whose page anchor is §2.3 but whose answer requires a later §2.4 chunk. Assert the provider receives both sections before generation and the response scope is `related`.
- [ ] **Step 2: Run the focused test** with `backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_paper_card.py::<new_test>`; verify it fails because current auto scope only sends the selected section.
- [ ] **Step 3: Write the failing test** for a provider answer that declares an evidence gap and verify the router expands once instead of treating the first plausible answer as final.
- [ ] **Step 4: Run the focused test** and verify the failure is in the current response contract, not in fixture setup.

### Task 2: Implement bounded cross-section context routing

**Files:**
- Modify: `backend/app/services/explanation.py`
- Modify: `backend/app/api/papers.py`
- Modify: `backend/app/providers/base.py`
- Test: `backend/tests/test_paper_card.py`

- [ ] **Step 1: Add a question-aware router** that preserves the selected paragraph and page, scores chunks using normalized English terms, section labels, and high-signal mechanism words, and adds at most a bounded number of related chunks.
- [ ] **Step 2: Treat questions containing mechanism/relationship cues such as “什么时候、如何、为什么、关系、流程、机制、function、output、parameter、user” as cross-section candidates; keep figure-only questions visual-first.
- [ ] **Step 3: Return `paragraph`, `section`, `related`, or `full` scope labels and keep the selected evidence first for citation provenance.
- [ ] **Step 4: Use the router for both text and visual questions; image-only pages remain valid with an empty text list.
- [ ] **Step 5: Run routing tests and the existing explanation suite; all must pass.

### Task 3: Improve the answer contract without dropping evidence checks

**Files:**
- Modify: `prompts/paper_ask.txt`
- Modify: `prompts/paper_ask_visual.txt`
- Modify: `backend/app/providers/openai_compatible.py`
- Modify: `backend/app/api/papers.py`
- Test: `backend/tests/test_remote_provider.py`
- Test: `backend/tests/test_paper_card.py`

- [ ] **Step 1: Define a natural answer schema** with `answer`, `facts`, `inferences`, `unknowns`, `citations`, and `needs_more_context`; keep `answer` required and allow empty lists for optional sections.
- [ ] **Step 2: Update the prompt to request a direct narrative first, then compact evidence distinctions; explicitly prohibit invented function names, output channels, and paper claims.
- [ ] **Step 3: Validate optional sections and preserve verified citations; if optional fields are malformed, keep the answer only when its citations remain valid.
- [ ] **Step 4: Add one bounded follow-up expansion when `needs_more_context=true` or when the model explicitly marks a key unknown; never loop more than once.
- [ ] **Step 5: Run provider and API regression tests.

### Task 4: Surface answer provenance clearly in the reader

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/ExplainPanel.tsx`
- Modify: `frontend/src/components/research-answer.css` or `frontend/src/components/explain-panel.css`
- Modify: `frontend/tests/explain-chat.spec.ts`

- [ ] **Step 1: Add optional response fields to the TypeScript type without changing existing saved conversations.
- [ ] **Step 2: Render facts, inferences, and unknowns as quiet expandable evidence sections below the direct answer; do not add a toolbar or multiple fixed question buttons.
- [ ] **Step 3: Add a Playwright assertion that a natural answer remains the first visible block and provenance details are available on demand.
- [ ] **Step 4: Run the focused browser tests and production build.

### Task 5: Real-paper regression and verification

**Files:**
- Create: `docs/superpowers/evidence/2026-10-21-context-routed-memgpt.md`
- No production files beyond the tasks above.

- [ ] **Step 1: Use the stored MemGPT paper and ask the same question about function arguments versus normal user-visible text.
- [ ] **Step 2: Record the selected page, routed sections, answer scope, citations, and whether the response distinguishes paper fact from inference.
- [ ] **Step 3: Run the full backend suite, focused Playwright suite, and frontend build.
- [ ] **Step 4: Only report completion after all commands pass and the live service health check succeeds.
