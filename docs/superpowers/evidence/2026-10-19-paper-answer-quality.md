# Paper answer quality verification — 2026-10-19

The reported question was: “这篇论文的附录部分还有什么值得读的地方吗？” The previous answer lacked an important negative result and rendered disconnected claim labels with repeated full-title links. A lexical-retrieval fixture containing 181 blocks reproduced omission of a weakly matched WebShop subsection before the complete-context change.

## Automated verification

- Backend: `.venv/Scripts/python.exe -m pytest tests/test_librarian.py tests/test_paper_answer_context.py tests/test_reading_paragraphs.py -q` from `backend`: **101 passed**. Includes scope isolation, immutable long-block slices, fact/background provenance, duplicate references, cache invalidation, oversized fallback, actual imported two-column PDF order, and combined source budget including notes.
- Browser: `npm run test:e2e -- tests/research-answer.spec.ts tests/intelligence.spec.ts tests/explain-chat.spec.ts` from `frontend`, with backend venv Scripts on PATH: **33 passed**. Disposable database and model fixtures; no paid requests. Covers readable Markdown/tables/math, source disclosure/PDF jumps, unsafe markup handling, history/tab retention, IME, retry, cancellation, stale results and in-flight draft edits.
- Production: `npm run build` passed. Vite still reports a main chunk larger than 500 kB; the Markdown pipeline increases its size. Scoped `git diff --check` passed.
- Independent code review: initial findings concerned interleaved columns and checking the full-context cap before appending typed extras. Both were corrected and the two regressions independently passed.

## Real provider and actual application

The real imported Reflexion paper contains 352 stored blocks, 59,030 extracted characters and 19 PDF pages. The exact question was asked through the configured ChatGPT Codex connection (`gpt-5.6-sol`), scoped to that paper, with current location page 9 and empty history.

The final run supplied all 352 blocks plus three typed context sources. It reported full stored-text coverage, completed in 63.4 seconds and used 63,398 input + 4,197 output = **67,595 reported tokens**, one remote answer call and one cached planner call. Earlier trials used 68,598 and 67,484 reported tokens. The three live answer calls therefore reported **203,677 tokens** in total; subsequent UI checks used application cache and reported zero additional model calls.

The final answer covered appendices A–D and explicitly recovered B.1's WebShop failure: 100 environments, terminated after four trials without improvement. It provided a reading priority table, model-dependence discussion, ALFWorld trajectory, programming prompts and related ablations, and an audit of reasoning examples. Spot checks confirmed WebShop conditions, the 0.26 starchat-beta result, the additional-model table and the 0.60/0.52/0.60/0.68 Rust ablation values against cited stored sources.

The running application was restarted. A production browser session submitted the question, received the cached real answer, verified 352/352 chunks and non-partial coverage, expanded a compact reference, jumped to page 12, and retained the conversation. No browser JavaScript errors or horizontal body overflow were observed at 1440×1000 and 1080×800. Screenshots and raw local trial records are ignored runtime artifacts under `.local-runtime/paper-answer-review/`, including `reflexion-answer-desktop.png`, `reflexion-answer-narrow.png` and `reflexion-sources-desktop.png`.

## Limits of this evidence

Full coverage here means all **stored extracted text**, not inspection of all figure pixels or proof of perfect PDF extraction. Larger documents and multi-paper questions continue to use bounded retrieval and report partial coverage. Model background knowledge is permitted as background; paper-specific assertions still require supplied originals.

An intermediate trial imprecisely presented body pages 8–9 as an appendix C discussion. The prompt now explicitly requires section/page attribution and distinguishes body results used to explain appendix material. The final real answer instead says “建议把它与正文 4.3 的消融一起读” and “正文报告” before those empirical results. The 88 librarian/context regressions passed again after that prompt change.

Source authentication confirms the existence of cited text, not logical entailment or scientific correctness. These trials establish improved coverage and usability, not universal answer correctness or parity with ChatGPT web. The model's interpretations, reading advice and causal explanations still require research judgment.
