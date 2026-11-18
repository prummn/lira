# Selected-passage question recovery

## Observed failure

The saved question “给我通俗的讲讲这个方向” in the Agentic Reasoning survey (page 26) failed before reaching a model: “选区不能在当前原文块中验证，请重新选择原文”. Its selected text contained PDF.js spacing such as `Mem- α` and `[ 24 ]`; stored extraction contained `Mem-α` and `[24]`. The frontend supplied the page header as a fallback chunk when its exact string comparison failed. A dehyphenation rule then removed the query's meaningful hyphen, preventing recovery. ASCII tokenization also discarded Greek letters.

## Changes

- Match rendered whitespace differences while retaining punctuation and Unicode letters; return the original source span rather than a fabricated quotation.
- Prefer this matching before line-wrap dehyphenation and existing font/layout recovery. Restrict recovery to the selected page and adjacent pages.
- Allow page plus selected text when no single chunk contains the selection. Stop substituting a page-header chunk in the frontend.
- Recover outdated chunk hints within the current paper; continue rejecting chunk IDs owned by another paper.
- Restore the saved page, source selection and translated excerpt when retrying an archived conversation. Preserve conversation identity.

## Verification

- Confirmed red/green reproduction using the actual selected text, including invalid altered Greek letters, names and numbers.
- Backend combined suite: **232 passed** (`test_selection_layout`, `test_paper_card`, `test_api`, `test_paper_answer_context`, `test_answer_evidence_recovery`, `test_conversations`, `test_remote_provider`). A final focused rerun: **24 passed**, one existing Starlette deprecation warning.
- Browser regression selection: **8 passed**, covering selection matching, original and translated passage questions, persisted question context, retry and hidden requests. These tests used the isolated test backend.
- Read-only replay of six retained historical failed text selections: **6/6 source matches**. This does not mean six fresh model answers were generated.
- TypeScript and production build succeeded; the production service was restarted with the changes.
- `git diff --check` passed (line-ending normalization warnings only).

## Actual model request and archive

The original question was retried through the running production endpoint. It passed source validation but the official provider returned HTTP 503 with `code=rate_limit`. A fresh quota query reported 0% short-window usage and 100% weekly usage; the reported weekly reset is **2026-11-10 10:13:42 +08:00**. This is a provider limit, separate from source recovery.

One further real request used the user's previously authorized SpacetimeAI profile, bound only inside an independent verification process. It ran the production `_explain_response` and `run_question` code, took **214.4 seconds**, returned nine citations and saved a completed answer in the original conversation `chat-c588ed2180af421189f10cf6e4a6411d` (turn `turn-9d9280c0c24442d193d459eb4089b84a`). The answer explains autonomous memory organization and reinforcement learning for memory management with a concrete research-assistant example. Response latency remains high; this test does not establish provider-wide reliability.

A fresh browser session opened the live reader, selected this question from reading history, fetched the persisted conversation through HTTP and checked that the saved answer was rendered. No browser page errors occurred. The original selected passage and page 26 were visible alongside the question. Local screenshot: `.local-runtime/selection-recovery-real-answer.png` (not a tracked repository asset).

No global model profile, automatic fallback preference, colleague's credentials, paper content or queued research/translation work was changed for this verification. Existing failed turns remain in the history for traceability.
