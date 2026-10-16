# Paper Knowledge Intake and Field Memory

## Goal

Turn the first analysis of an imported paper into a source-linked knowledge candidate package that supports reading, later confirmation, and cross-paper field synthesis without presenting model guesses as settled knowledge.

## Context and current gap

The workspace already has deterministic PDF extraction, persistent full-paper intelligence tasks, evidence-linked paper cards, cached model calls, usage reporting, a librarian, and a reader that can locate evidence in the PDF. The existing `PaperCard` already exposes useful fields such as problem, method, results, datasets, metrics, baselines, related methods, and section summaries.

The missing layer is a reusable field model. Extracted datasets, methods, benchmarks, papers, and relationships currently remain inside a paper analysis result. They cannot be compared with existing knowledge, marked as new or conflicting, confirmed by the researcher, or reused as a cross-paper method history. The reader also has no clear distinction between a first-pass candidate and knowledge that has already been accepted.

## Product behavior

Importing a paper with analysis enabled starts one `paper knowledge intake` task. The task combines the existing paper card, evidence extraction, and a new knowledge candidate extraction contract. It does not directly publish model-generated entities into the confirmed field knowledge base.

The task has three layers:

1. **Local source preparation.** Existing PDF parsing provides metadata, sections, paragraphs, page coordinates, captions, tables where available, and references. Deterministic mention detection identifies likely datasets, benchmarks, metrics, tasks, methods, and cited paper identifiers without a model call.
2. **Unified model extraction.** High-value windows from the abstract, introduction, method, data/experimental sections, conclusion, and reference context are sent through the existing cached intelligence harness. One structured result produces the paper card, evidence-backed knowledge candidates, relation candidates, and a reading map. Separate calls for “summary”, “dataset detection”, and “citation analysis” are avoided when the same source windows can serve all three.
3. **Local reconciliation.** Candidate names and normalized identifiers are matched against the local field registry. Each candidate receives `new`, `known`, `alias`, `conflict`, or `unresolved` status. Only confirmed items enter the canonical registry.

The existing import checkbox means “建立知识候选” when enabled. The user can still import without model analysis and later start the same task from the reader or library. A separate deep scientific review remains an explicit follow-up action; it is not part of every first pass.

## Knowledge lifecycle

Paper-level states are:

- `unread`: source is imported and locally parsed; no model candidate package exists.
- `candidates`: a first analysis exists and awaits confirmation.
- `partially_settled`: some candidates are confirmed, while others remain pending or unresolved.
- `settled`: the paper's core candidate package has been reviewed; later changes can still create conflicts.
- `needs_review`: a model result or new paper conflicts with confirmed knowledge, or evidence is insufficient for a safe merge.

Entity and relation states are:

- `candidate`: extracted from a paper but not accepted into the field registry.
- `confirmed`: accepted into the canonical registry with one or more source citations.
- `rejected`: explicitly dismissed by the researcher; it remains visible in the source history and is not offered again for the same evidence.
- `conflict`: differs from confirmed knowledge and requires review.
- `unresolved`: the source mentions something that cannot yet be mapped to a stable entity.

Every candidate and relationship retains paper id, source chunk id, page, section, quoted source text, confidence, extraction run, and the model/prompt version. A candidate without verifiable source evidence cannot become confirmed.

## Unified analysis contract

The first-pass result contains these independent but related views.

### Paper card

- title and one-sentence summary
- research problem and motivation
- core idea and method mechanism
- main results and experimental conditions
- data, tasks, metrics, baselines, and ablations
- assumptions, limitations, and future work
- section-level summaries and prerequisite concepts

The existing evidence-linked `PaperCard` remains the presentation contract for this view.

### Knowledge candidates

Each candidate has:

- `entity_type`: `paper`, `method`, `dataset`, `benchmark`, `task`, `metric`, `concept`, or `venue`
- `name` and normalized name
- aliases found in the paper
- concise description grounded in the paper
- role in this paper, such as `proposed`, `used`, `baseline`, `cited`, or `compared`
- evidence references and confidence
- reconciliation status and optional conflict details

Datasets and benchmarks are separate entity types even when they share a name. A dataset record can include task, split, scale, license/availability when explicitly stated, and evaluation role. A benchmark record can include the canonical task and the set of metrics or datasets only when the source supports them.

### Relation candidates

Relations use a controlled vocabulary:

- `builds_on`
- `extends`
- `compares_with`
- `replaces`
- `uses_dataset`
- `evaluated_on`
- `inspired_by`
- `contrasts_with`
- `requires_concept`

Each relation has source and target candidate references, a short explanation, source evidence, confidence, and reconciliation status. A citation in a reference list alone is not enough to assert a semantic method relation; the introduction, related work, method, or experiment text must provide the supporting sentence.

### Reading map

The result records where a candidate was found and what remains uncertain:

- section and page for each extracted group
- recommended first reading sections
- unresolved terms or references
- missing data/benchmark descriptions
- questions that can be answered by opening the cited source

## Reader interaction

The bilingual/original reader keeps the main document uninterrupted. The research side panel gets a new `Knowledge` view for the current paper.

During the first reading, the panel shows candidate groups with compact status chips:

- `新发现`
- `已有知识`
- `别名匹配`
- `冲突`
- `待确认`

Each candidate has three actions: confirm, edit then confirm, and reject. Batch actions are available by group (`方法`, `数据集`, `Benchmark`, `关系`) so a researcher can confirm a clean set without approving every row individually. Every row has a single “查看原文” action that jumps to the exact evidence. The panel never forces a mode switch away from the current translation or PDF position.

When the same paper is opened again, the default view is a compact knowledge review:

- confirmed items are collapsed into a source-linked inventory;
- newly detected items are expanded;
- conflicts and unresolved candidates stay expanded;
- unchanged candidates are hidden behind “查看已沉淀内容”.

Selecting a paragraph in the PDF offers `识别本段`. This performs a small incremental extraction using the paragraph and bounded surrounding context, reconciles it against the same registry, and adds candidates to the current paper without replacing earlier confirmed knowledge. It is the manual path for an important Introduction paragraph or a dataset section that the first pass missed.

## Field knowledge views

The field knowledge page will use the confirmed registry as its source:

- **Method evolution:** a timeline/graph of confirmed method entities and source-linked relations, with relation confidence and unresolved edges visibly separated.
- **Dataset and Benchmark catalog:** canonical name, aliases, task, metrics, papers using it, and gaps in the local description.
- **Paper comparison:** problem, method family, datasets, metrics, baselines, results, and limitations drawn from source-linked confirmed records.
- **Candidate inbox:** new, conflicting, and unresolved items grouped by paper, with batch confirmation and evidence jumps.

The graph is a projection of confirmed records. Candidate edges can be previewed in the paper's knowledge panel but do not silently change the field graph.

## Token and execution strategy

- Keep deterministic extraction outside the model.
- Reuse the existing window packer and model-call cache keyed by paper source digest, operation, model profile, and prompt version.
- Ask the model for card fields, entities, relations, and reading-map output in one structured contract per window/reduction stage.
- Use the existing bounded reduction for long papers; do not send the full PDF again to produce the knowledge delta.
- Reconciliation, alias matching, duplicate detection, and evidence validation run locally.
- Incremental paragraph extraction is opt-in and cached by source chunk plus registry revision.
- A failed candidate task leaves the local paper parse and any prior confirmed knowledge intact. A partial task publishes only validated candidate groups and shows its coverage.

## Error and trust rules

- Model output is validated against the structured schema before persistence.
- All claims and relations must point to stored source evidence; unverifiable text is retained only in the failed task report.
- Low-confidence or conflicting results remain candidates and never overwrite confirmed records.
- Deleting a paper removes its paper-local candidate links but preserves a confirmed entity only if another source still supports it; otherwise the entity becomes unsupported and is marked for review rather than silently deleted.
- Provider failures show the existing retry/partial state and never block PDF reading, notes, translation, or local search.

## Acceptance criteria

1. An analyzed import produces one paper card plus source-linked method, dataset/benchmark, and relation candidates in the same persistent task.
2. A paper imported without analysis remains locally readable and can later create the same candidate package.
3. Candidates clearly show known/new/alias/conflict/unresolved status against the local registry.
4. Confirming a candidate makes it available to cross-paper search, dataset catalog, method evolution, and librarian retrieval; rejecting it does not remove the original evidence.
5. Reopening an analyzed paper shows a compact settled view and highlights only new/conflicting/unresolved items.
6. `识别本段` can add candidates without replacing existing paper analysis or moving the reader away from its current paragraph/translation state.
7. Cached repeated analysis makes zero additional provider calls when source, model profile, and prompt version are unchanged.
8. Tests cover schema validation, evidence requirements, candidate reconciliation, confirmation/rejection, conflict handling, incremental extraction, task failure retention, and the reader's first-pass versus settled UI.
