# ReAct knowledge intake regression

Date: 2026-10-16

Source: arXiv `2210.03629`, imported through `POST /api/papers/import-url` from `https://arxiv.org/pdf/2210.03629`.

The real PDF imported successfully as `ReAct: Synergizing Reasoning and Acting in Language Models` with 33 pages and 579 stored source chunks. The full staged run performed six extraction windows and persisted cache entries for the extraction/reduction stages. With `xhigh` reasoning, the final synthesis request exceeded the bounded regression wait; the task remained recoverable and the source/card data were retained. A bounded direct analysis using the same configured provider at medium reasoning completed in 71 seconds and produced source-linked candidates.

The resulting candidate package contained six entities and seven relations. The entities included `ReAct`, `HotpotQA`, `Fever`, `ALFWorld`, `WebShop`, and `absolute success rate`. The relations included `ReAct evaluated_on HotpotQA`, `ReAct evaluated_on Fever`, `ReAct evaluated_on ALFWorld`, `ReAct evaluated_on WebShop`, and comparison/contrast edges for imitation learning, chain-of-thought reasoning, and reinforcement learning methods. Every returned entity had one stored evidence item and the relation package retained exact chunk/page evidence.

One `HotpotQA` candidate was confirmed through `POST /api/knowledge/candidates/{id}/confirm`; it appeared in `GET /api/knowledge/entities?entity_type=dataset` as an active canonical entity. The Introduction paragraph was then sent to `POST /api/papers/{id}/knowledge/paragraph`; the additive endpoint returned `202` in 48 seconds and retained the current paper package, confirming paragraph recognition does not replace the reader position or prior candidates.

This run exposed a product-level tuning point: long papers with high reasoning can spend several minutes in reduction and synthesis. The worker keeps progress, cache, and previous knowledge intact; the next tuning pass should expose a bounded “deep analysis” choice or use a lower reasoning profile for first-pass intake while retaining the explicit deep review path.

## Bounded first-pass regression (2026-10-16)

The staged harness now caps the first-pass synthesis and review stages at `high` when a profile is configured as `xhigh`, reuses extract/reduce caches, and falls back to one bounded `medium` synthesis attempt after a retryable high-effort timeout. A synthesis response that omits its knowledge arrays triggers one evidence-pool-only `paper_knowledge_intake_v1` call; an explicit empty array remains an evidence-based model decision. The call does not reread the PDF. Science review now preserves the already validated knowledge package while changing card fields.

ReAct was queued through the normal `/api/intelligence/tasks` endpoint after the change. The task completed with `22/22` steps, `partial=false`, `18` cache hits, and no new extraction calls. The stored package contains `18` source-linked candidates and `10` source-linked relations. Candidate evidence points to the original PDF pages; confirming `HotPotQA` added it to the benchmark entity directory. Relation confirmation correctly remains gated until both endpoint entities are confirmed.
