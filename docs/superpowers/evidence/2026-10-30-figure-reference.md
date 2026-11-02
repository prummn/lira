# Body reference incorrectly detected as Figure 5

## Reproduction and cause

NL2Repo-Bench PDF page 12 begins a body paragraph with `Figure 5 quantifies these phenomena.` The actual Figure 5 and its caption are on page 13. The visual detector matched the leading figure number as a caption, then associated a distant bottom rule from Table 6 with it. Its union covered the intervening section heading and body paragraphs.

The reading-paragraph classifier separately used only the leading figure number to classify captions. It therefore also treated the body reference as a caption.

## Fix

- A figure candidate must have graphic extent in both dimensions; a single horizontal table rule cannot create a figure.
- Other captions and intervening ordinary prose block the association between a candidate caption and a distant graphic. Axis labels inside or immediately outside the graphic remain eligible.
- Reading paragraphs use verified visual captions, explicit caption delimiters, or smaller caption typography. A body reference alone does not mark prose as a caption. Multi-line source text is normalized before matching.
- Stored source chunks, evidence coordinates, translations, and the original PDF are unchanged. No model call is needed for this correction.

## Verification

- Four new visual-region cases failed before the fix: a table rule mistaken for a figure, distant association across prose with and without a real caption, and a reference immediately following a real caption.
- The paragraph-kind regression failed before its fix. A wrapped-caption variant also exposed and verified normalization of line breaks.
- Visual regions, reading paragraphs, boundary review, and paper-answer context: 59 tests passed, with one existing Starlette deprecation warning.
- Real PDF inspection confirms page 12 contains only Table 5 and Table 6 visual regions. Exactly one Figure 5 remains, on page 13. All nine real figures and eight real tables are preserved. The body reference is prose and the actual caption remains a caption.
- Browser verification used the disposable database on 8010 and frontend on 5177, after checking matching library identities. At viewport widths 1440 and 780, hovering the body reference produced a paragraph translation action without a Figure 5 action or overlay. The actual Figure 5 action on page 13 still opened the question dialog. Refresh, reopening the reader, and repeating the body hover passed. No page errors occurred.
- Screenshots were visually inspected: `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-body-reference-1440.png` and `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-body-reference-780.png`.
- Browser report: `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-figure-reference-browser.json`. Region report: `C:/Users/15039/AppData/Local/Temp/lira-nl2repo-figure-reference-regions.json`.
- The live library stayed at 84 papers. Disposable imports were confined to the test library.

## Runtime boundary

The user services on ports 8000 and 5173 were preserved. The existing backend process still holds older imported modules; the changes take effect after its next normal restart, without reimport or AI reanalysis. The earlier automatic restart rejection remains in force and was not bypassed.
