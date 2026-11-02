# NL2Repo table selection boundaries

## Confirmed failure

The original NL2Repo paper is `paper-4357e2df19b64b3b`. On PDF page 9, Table 3 was detected as its caption and header without the data rows. Table 4 also omitted most rows and incorrectly borrowed Table 3's bottom rule.

The PDF extractor combines 72 cell lines into a single long text block. The previous 160-character table-block limit discarded it. Drawing components joined only within 34 PDF points, which could not connect the sparse header and bottom rules of these tables.

## Changes

- Recognize repeated horizontally separated cells inside large PDF text blocks.
- Follow contiguous table rows, stopping at other captions, headings, and ordinary prose. Support captions below tables and keep adjacent columns separate.
- Associate sparse rules with the complete row extent instead of header-only drawing connectivity.
- Use the already padded table bounds directly for question screenshots. Avoid a second screen-space padding that included the neighboring caption. Figure padding is unchanged.
- Make the Playwright frontend explicitly load `vite.config.ts`, so an ignored stale JavaScript config cannot silently proxy tests to the daily library.

## Verification

- The new long-table regression failed before the recognition change. The screenshot-dimension regression failed before removal of double padding. Both pass with the fix.
- Current backend visual-region, paper-answer-context, and reading-paragraph suites: 38 passed, with one existing Starlette deprecation warning.
- Current complete explain-chat browser suite: 13 passed in 51.5 seconds, using a freshly started disposable backend on 8010 and an explicitly configured frontend on 5177. Library IDs and counts confirmed that both test ports used the disposable database.
- Production frontend build passed earlier in this task, with the existing chunk-size warning.
- Real NL2Repo PDF was imported into a fresh disposable library. Hovering the final rows and clicking the table question action produced complete outgoing screenshots and text. The explain endpoint was mocked: this verifies selection, crop, and context, not a real model answer. No browser page errors occurred.
- Table 3 bounds: `[65.59400177001953, 72.20761108398438, 547.40771484375, 285.10260009765625]`. All 12 model rows including Qwen3-thinking are included; Table 4 caption is excluded.
- Table 4 bounds: `[125.60087585449219, 286.1645812988281, 483.08013916015625, 579.3555297851562]`. Both category panels and their final rows are included; the preceding table rule and following prose are excluded.
- Both outgoing browser crops were visually inspected: `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-table3-browser.jpg` and `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-table4-browser.jpg`.

## Test isolation incident and cleanup

An early test frontend loaded the stale ignored `vite.config.js`, which hardcoded the live backend on 8000. Sixteen generated question-layout papers and two NL2Repo regression copies were accidentally imported there. These early browser runs are not counted as isolated verification.

Before cleanup, the live SQLite database was backed up with its backup API to `C:/Users/15039/AppData/Local/Temp/lira-before-table-test-cleanup-20261030T050811Z.db`. Cleanup matched the exact 18 generated IDs, expected titles, creation-time window, and absence of notes, translations, knowledge, collection memberships, or real intelligence tasks. All other paper rows were checked byte-for-byte at the SQL value level, including the original NL2Repo record. Foreign-key integrity was unchanged. The live library returned from 102 to 84 papers. Original and test PDF files were preserved.

The 18 test reading events and their IDs were also removed from the daily activity aggregate; other activity counts were unchanged. Cleanup reports are `C:/Users/15039/AppData/Local/Temp/lira-table-test-cleanup-20261030T050811Z.json` and `C:/Users/15039/AppData/Local/Temp/lira-table-test-activity-cleanup.json`.

## Runtime boundary

The user backend on port 8000 and frontend on 5173 were preserved. The backend still holds older imported modules. Updated recognition takes effect after its next normal restart; no paper reimport or AI reanalysis is required. An earlier controlled restart was rejected by automatic approval with only `blocked by policy`. No alternative restart, hot patch, or termination of the user services was attempted.
