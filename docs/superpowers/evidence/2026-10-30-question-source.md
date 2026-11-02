# Selected passage attached to the question

## Problem and change

Explanation conversations already persisted selected_text, translated_text, page, and chunk identifiers. The transcript rendered only the natural-language question and answer; the selected passage was hidden in the composer context. As a result, questions such as 为什么这么说 had no visible referent when revisiting the archive.

QuestionSource now renders the saved passage directly above each user question, including pending and archived turns. It shows the page and a source-location action. Text is initially limited to three lines; actual overflow measurement enables expansion at the current width. Translated selections retain their Chinese excerpt and can expand to show the corresponding English source. ScientificText preserves math rendering and text safety.

useConversation exposes the selected archive context so transcript quotes follow the saved conversation rather than the current reader selection. Existing conversation records require no migration or model calls. The source-location action uses the saved English quotation and page for text questions and the saved bounding box for visual questions.

## Verification

- Three focused regressions failed before implementation because no question-source element existed. They passed after implementation: pending-to-completed display, persistence in a fresh browser context, and Chinese excerpt with original English.
- Full explain-chat.spec.ts and conversation-persistence.spec.ts run:18 passed in1.4minutes. Includes background completion, navigation, browser reload, fresh browser context, retries, visual follow-ups, narrow geometry, and independent conversation scrolling. Tests use the disposable backend and loopback provider, without personal credentials.
- npm run build passed: TypeScript and Vite,1966modules. Existing bundle size warning remains.
- The real NL2Repo archive containing 为什么这么说 was opened through the running application. The displayed excerpt exactly matched its persisted selected_text. Its answer remained unchanged, and the source-location button returned to page2 with the source overlay visible.
- Live desktop1440x1000 and narrow720x760 screenshots inspected: .local-runtime/question-source-desktop.png and .local-runtime/question-source-narrow.png. The narrow quote stayed within the viewport. Zero model submissions and browser script errors during the archive check.
- No backend schema, personal archive content, or running application services were changed. Temporary test services used8010and5177. Test output went to the system temporary directory to avoid filling D:.
