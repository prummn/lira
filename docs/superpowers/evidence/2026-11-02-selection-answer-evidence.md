# Selection answer: distinguish citation formatting from absent evidence

## Reproduction

The saved SWE-smith page-3 question compares its environment-first collection
strategy with SWE-bench's task-first strategy. The saved selection and first
model input both contained the original comparison paragraph.

A real official-account replay produced a 664-character substantive answer and
seven citations. Six quotations matched immediately; the seventh joined two
literal excerpts from section C.2 with ` ... `. The old all-or-nothing validator
rejected that quotation and replaced the entire answer with the fixed
insufficient-evidence response. The API then unnecessarily expanded retrieval.
The expanded real call succeeded with 732 characters and eight verified sources.
Historical raw output was not retained, so its exact quotation failure cannot be
reconstructed; the same false-refusal mechanism was reproduced with the actual
saved question, selection and current official connection.

## Change

- Text and visual questions can recover explicit elisions only when every
  substantial excerpt matches in order within the same supplied source. The
  evidence becomes the complete contiguous original span, including omitted
  text; it is independently checked against the immutable original chunk.
- Fabricated, reversed, tiny, cross-block and unsent excerpts remain rejected.
  Analysis and knowledge extraction retain their original strict contract.
- Invalid answer formats or unverified citations produce a technical provider
  error instead of claiming the paper lacks evidence. Actual model refusals
  preserve their specific explanation and context-expansion signal.
- The prompt requests short contiguous quotations and separates missing details
  from inability to answer the central question.

## Verification and deployment

- New regressions first failed: **10 failed, 1 passed** on the old behavior.
- Provider, official transport and recovery batch: **194 passed**.
- Paper-card, conversation, selection-layout and answer-context batch: **60 passed**.
- Final recovery suite, including added unsent/cross-source bounds: **13 passed**
  (overlaps the provider batch).
- Replaying the captured first answer with the fix preserves all **7 citations**
  in one pass; every evidence span is literal original text. No extra model
  request is needed to repair the reproduced formatting problem.
- Independent targeted review found no actionable issues and verified the real
  recovered evidence against the supplied sources.
- The formal backend was restarted after background generations drained. The
  existing active pretranslation job was resumed and research settings restored
  exactly. No new library papers or conversations were added.
- The original false-refusal turn was backed up locally, then replaced with the
  successful real regenerated answer in the same conversation. An API read
  confirmed the persisted 732-character answer and eight sources.
- Live browser opened that existing conversation through the reader's history:
  the restored answer rendered, all eight evidence cards appeared, no false
  insufficient-evidence banner remained, and no generation request was sent.
- Read-only SQLite verification: integrity `ok`, 46 papers, 5 personal notes;
  personal-note digest unchanged.

Local inputs, captured model outputs, replay responses, original-turn backup and
deployment snapshots are under `.local-runtime/swe-smith-question/` (excluded
from releases). Test logs are `.local-runtime/swe-question-*.log`.
