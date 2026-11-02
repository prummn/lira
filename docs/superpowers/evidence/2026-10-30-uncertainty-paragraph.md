# Inline radical paragraph boundary

## Reproduction

DeepSWE page 12, section 5.5 (Uncertainty quantification), split the paragraph
beginning `Running every task` at the standard-error formula. The translation
stopped at `SE = std(s1, . . . , sR)/`, leaving the remaining discussion as a
different reading unit.

The PDF emits the raised radical as a separate block before the surrounding
multi-line prose block. Its continuation starts `R. This` in the middle of the
same line. Typography incorrectly treated this horizontal offset as paragraph
indentation, preventing the continuation from joining. The radical also appeared
at the start of the derived source text.

## Fix

Adjacent overlapping blocks containing a short raised mathematical operator are
ordered by their observed first lines. A continuation after a math fragment may
override apparent indentation only when the actual last/first lines occupy the
same baseline and have a small horizontal gap. Ordinary paragraph indentation,
column order, diagram labels, and source evidence remain governed by the existing
rules.

The first paragraph now contains all three source anchors in order: prose before
the radical, radical, and `R. This ... not statistically separated.` The following
paragraph beginning `This interval captures only one source of noise` remains
separate. Source chunks, stored coordinates, and existing translations are not
rewritten. The complete derived source gets its own translation identity, so an
old partial translation cannot be presented as the complete result.

## Verification

- Added a regression using the actual five source chunks and 27 observed PDF
  lines from this section. It failed before the fix with three paragraphs instead
  of two. It now verifies full text, radical order, exact source slices, source
  immutability, and the following natural paragraph.
- A separate regression preserves independent diagram labels that share a line.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_reading_paragraphs.py backend/tests/test_reading_boundary_review.py backend/tests/test_translation_queue.py backend/tests/test_translation_cache.py backend/tests/test_selection_layout.py -q`: **131 passed**, one existing Starlette/httpx deprecation warning.
- Compared the derived paragraphs for all 42 library records with available PDFs
  through read-only database access. Forty papers were unchanged. Only this
  DeepSWE paragraph and a matching inline formula continuation on Self-RAG page 19
  changed. Exact source-slice coverage was unchanged for every paper. The Self-RAG
  page was rendered and visually checked against the changed passage.
- Replayed the real DeepSWE source through TestClient in a disposable database.
  A pre-existing partial translation was preserved but not reused. The full
  paragraph was sent in one recorded provider request; a repeated request reused
  its cache. No boundary-model review was required. Zero real API calls and zero
  personal-library writes.
- Browser check uses the running frontend in a separate headless context with
  every API request intercepted. Its data comes from that disposable API replay
  and its PDF bytes from the original file. It verified the three selected source
  regions, a complete fixture translation, desktop and narrow layouts, and
  reading the result again after reload. No requests reached the production API.
  Screenshots: `C:/Users/15039/AppData/Local/Temp/lira-uncertainty-reader.png` and
  `C:/Users/15039/AppData/Local/Temp/lira-uncertainty-reader-narrow.png`.
- `git diff --check -- backend/app/services/reading_paragraphs.py backend/tests/test_reading_paragraphs.py` passed.

## Runtime status

The live backend still returns the old three-unit section. Its process does not
reload source changes. No live service was restarted: the earlier restart action
was rejected by automatic approval with `blocked by policy`, and user confirmation
is still pending. The browser check above establishes the reader behavior with
the new payload; it is not a claim that the live backend has loaded this fix.
