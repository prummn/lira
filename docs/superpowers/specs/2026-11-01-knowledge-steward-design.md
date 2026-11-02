# Research knowledge steward

The user authorized autonomous assessment and improvement while away. This design
uses the actual seven-paper Agent collection, rather than a synthetic keyword demo.

Observed: 108 objects, 73 relations (28 unresolved, 19 awaiting confirmation),
one failed paper with no graph. Benchmark sources are excluded by the method-only
endpoint rules. Six venues are absent, including two explicit ICLR PDF headers.
Only three proposed methods appear because benchmark contributions are omitted.

## Decisions

1. Repair predicate-specific endpoint types without relabelling benchmarks as
methods. Preserve human decisions and original evidence.
2. Add a paper-level AI curation pass to the existing serial maintenance queue.
It sees bounded original body text, existing objects/edges and canonical identities,
and can confirm supported extractions, supplement omissions, and link unambiguous
aliases. Every action retains literal source citations, a decision reason, an
input fingerprint and an undo snapshot. Human edits/rejections win. Unsupported
or ambiguous changes remain a small exception queue, never a mass confirm-all.
3. Curation is independent of successful full-card generation. An unanalysed or
failed paper remains eligible for source-grounded knowledge extraction.
4. Keep existing foreground priority, quota thresholds, hourly call limits and
single subscription request channel. Persist each paper checkpoint. Fingerprints
prevent repeating the same paper merely because a scheduled interval elapsed.
5. Verify publication metadata locally first, then bounded scholarly lookups with
strict identity matching and provenance. Never invent a publication venue.
6. Present contribution networks for methods and benchmarks, one searchable object
directory, readable comparisons and collapsed relation detail. Name the worker
AI 知识整理, explain its work and surface automatic changes before exceptions.

Alternatives considered: extra keyword rules cannot judge semantic support;
unrestricted graph rewriting cannot preserve provenance or human decisions.
Evidence-backed model actions inside the existing scheduler address both.

## Acceptance

Reproduce and repair the real benchmark endpoint fault; measure actual backlog and
coverage before/after using a disposable database copy; run real model trials and
separate model output quality from local mock tests; verify UI in an isolated
browser workspace; never insert test papers into the personal library. Preserve
existing data and pending restart restrictions.
