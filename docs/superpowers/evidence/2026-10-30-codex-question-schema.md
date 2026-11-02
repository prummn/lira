# Codex selection question: plain answer rejected as inner JSON

## Confirmed failure

The NL2Repo conversation chat-f826780a204a42209bc69f224a80bbc0 contains two failed attempts at the same upstream pytest suite question. Both failed at the shared JSON decoder, after the transport had already accepted the Codex final message. Question text and selected source were persisted; the failed attempts have null response fields. No original raw response from those two attempts was retained.

A real reproduction with the same saved selection, question, active model gpt-5.6-sol, and configured account returned a complete677-character Chinese explanation as plain text. The old transport constrained only an outer object with a string text property, then asked that string to contain another JSON object. The inner request was not schema constrained. The model satisfied the outer schema with prose; complete_json rejected that prose at position0 and discarded it. This reproduction was a formatting contract failure after successful model generation, rather than an authentication or network failure.

## Change

Codex paper questions now supply the actual answer schema to --output-schema: answer, facts, inferences, unknowns, needs_more_context, citations, and insufficient_evidence. Text and visual questions share the same direct object contract. The response is decoded once; quotation verification still uses the existing local source validator. Other generation workflows retain their prior transport contract.

Official documentation fetched: https://developers.openai.com/codex/noninteractive/ , Create structured outputs with a schema. The documented --output-schema constrains the final response object itself.

## Verification

- Three regression cases failed before the change and passed afterward: text question output schema, visual question output schema, and rejection of an invented citation.
- test_codex_subscription.py, test_remote_provider.py, test_paper_answer_context.py, and test_conversations.py:206passed, one existing Starlette deprecation warning,38.69seconds.
- A real reproduction using the modified modules completed both initial retrieval and full-context expansion, returning a383-character answer and5locally verified citations. Both model returns were JSON objects under the direct schema. It did not modify the archived conversation.
- git diff --check passed for modified tracked provider and test files, with an existing line-ending normalization warning.

## Runtime boundary

The running backend on8000 was still using its previously imported code. Its work status and chat table showed no running or queued model work before a controlled backend-only restart was attempted. Automatic approval rejected that restart with only blocked by policy. No fallback restart or alternate process termination was attempted. The source fix and standalone real-model reproduction are verified; the running application has not loaded the fix. Existing conversations and the frontend service remain intact.
