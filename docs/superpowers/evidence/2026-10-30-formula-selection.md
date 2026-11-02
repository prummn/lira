# Formula selection recovery

## Report and cause

The DeepSWE page 12 question about pass@4 failed before reaching the model with
`选区不能在当前原文块中验证，请重新选择原文`.

The PDF.js selection contains a summation sign. MuPDF extraction instead stores
`X` for that glyph in the PDF's TeX math extension font. The document encodes
`/Differences [80 /summationtext 88 /summationdisplay]`; the formula and surrounding
paragraph also occupy seven extraction blocks with different reading orders.
The previous literal selection resolver could not reconcile these differences.

## Change

`selection_source.py` preserves the existing strict resolver, then attempts local
layout recovery within the selected page and its immediate continuations. It
handles split formula fragments and partial paragraph selections, while requiring
prose block boundaries and preventing reuse of consumed source characters. It
rejects changed numbers, comparison operators, and inserted prose.

Math glyph correction uses the PDF's own font encoding, source text, and block
geometry. It changes comparison copies only. Stored source chunks and literal
citation validation remain unchanged; ordinary X characters are preserved.

For recovered math with a vision provider, the explain route supplies a crop of
the actual paragraph as part of the existing question call. The text conversation
identity remains unchanged. Local extractive answers now cite each matched source
block individually rather than citing an entire cross-block selection against its
first block.

## Verification

- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_selection_layout.py backend/tests/test_paper_card.py backend/tests/test_conversations.py backend/tests/test_research_findings.py -q`: **67 passed**, one existing Starlette/httpx deprecation warning.
- The 13 selection regressions cover the published paragraph fixture, modified
  facts/operators, unrelated prose insertion, partial selections, page locality,
  actual generated PDF font encoding, normal X preservation, and local/remote
  conversation follow-ups.
- Read-only recovery against the real PDF resolved all seven source blocks,
  including the font-verified summation glyph, in approximately 0.094 seconds.
- The real saved selection and PDF were replayed through TestClient in a temporary
  database. Initial question and follow-up both returned HTTP 200, remained in the
  same text conversation, and completed. A recording provider received the local
  formula image and all seven source blocks. The crop was visually inspected.
- This replay made zero personal library writes and zero real model API calls.
  It verifies request assembly and persistence, not live model answer quality.
- `git diff --check -- backend/app/api/papers.py` passed.

## Runtime boundary

The existing backend does not reload automatically. No live services were stopped
or restarted in this work. An earlier automatic approval rejected the restart
with only `blocked by policy`; explicit user confirmation is pending before a
normal restart and live verification. The fix is source-ready and is not yet
claimed as active in the running application.
