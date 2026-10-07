# Bounded scientific review of generated paper cards

The recovery trial revealed an additional material defect: Adaptive-RAG's TLDR omitted the FLAN-T5-XL condition even though its main-result field retained it. GPT-3.5's appendix results contradict the resulting generalization. Exact quote matching did not detect the error. Another numerical comparison omitted its baseline row, and a limitations section summary cited a true clause from a different section.

The user authorized autonomous repairs and prioritizes scientific accuracy. This extends the existing recovery design without requiring another design approval. Preserve the running six-paper v5 trial before loading any new harness or prompt fingerprint.

## Chosen approach

Add a bounded final review over the primary overview and locally detected risky statements: empirical numbers/comparisons, exclusive conditions and technical identifiers. Review the one-sentence summary, TLDR, main results and limitations first; include risky method, ablation, claim and section-summary entries within at most two review batches. Remaining items are explicitly outside this review's scope. A second model pass is an imperfect check, not a proof of scientific truth.

Each batch uses at most 12 entries and a fixed source/context budget. Supply unchanged cited excerpts first, then nearby original passages on the cited PDF pages so reviewers can inspect table headings, units, model/dataset labels and comparator rows. Every supplemental passage comes from the existing local original-source catalog and receives a local short ID; no synthetic fact or invented lineage is created. Context omission is reported. No full extraction, reduction or synthesis is repeated merely to review a cached card.

Return an explicit supported/corrected/unsupported decision per requested slot. Supported entries remain exactly as submitted. Corrections may cite only originals included in that batch, must satisfy normal quote/membership/section/cardinality checks, and may not change other slots. Missing/duplicate/invalid decisions cannot establish support. Rejected or deferred items leave a partial card with explicit diagnostics; a service outage cannot discard the other validated entries. Semantic correction counts and reviewed scope are separate from citation authenticity and from the previous formatting-repair count.

Quality calls use exact-request cache identities and the existing cancellation/typed transport recovery path. At most two review calls are baseline stages; transport retries continue sharing the six-extra-attempt limit. Successful corrections are cached and revalidated locally on reuse. No retry of a merely unsupported semantic decision and no repeated paid sampling to obtain a favorable status.

## Alternatives considered

- Stronger synthesis wording alone costs no extra call but the existing prompt already requests conditions and clause-level support; it did not prevent this observed defect.
- Re-read every card item against the whole paper on every attempt increases latency and duplicates evidence. Bounded review of the overview and suspicious statements addresses the observed failures while making its coverage limits visible.

## Acceptance

Use the frozen Adaptive-RAG card and real PDF excerpts as a regression: a corrected short summary must retain its model condition; numerical comparisons must include both relevant rows; section summaries must stay in their cited section. Prove cache-only replay makes no network attempt. Recheck published source membership, quotes and geometry separately from a human semantic audit. Preserve all bibliography, reading state, collections, notes and source chunks.
