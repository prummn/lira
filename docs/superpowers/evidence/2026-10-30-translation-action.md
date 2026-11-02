# PDF paragraph translation action: visible placement and actual activation

## Root cause

The previous placement patch bounded a guessed control size to the complete PDF page. It did not intersect that page with the visible reading scroller. For NL2Repo-Bench, the introduction paragraph remained partly visible after scrolling, while its action was clipped above the reading area. A compact control at the page edge was also detached from the paragraph. The previous inside-page geometry check did not establish that a user could reach and activate it.

## Change

`PdfParagraphAction.tsx` measures the rendered control and intersects the page, scroller client area, and browser viewport. It prefers a labelled action beside its source, then directly above the source. When the paragraph top is clipped and a compact control is needed, the action stays beside the visible lines. Scroll, resize, and page geometry changes update placement; fully clipped source regions hide their actions. A pointer corridor preserves the hovered source while moving toward its action.

The multi-region regression now checks proximity to the hovered source and physically opens its saved translation, rather than prescribing an above-only placement. New desktop and narrow-window regressions check clipped-source placement, hit testing, mouse movement, and cached translation activation.

## Current verification

- Real NL2Repo-Bench, paper-4357e2df19b64b3b, introduction paragraph paragraph-021632634625a3cc48c1a91c: action initially at x845.92, y828.95, width86, height36, aligned to paragraph right931.92.
- After scrolling750px, paragraph y122.95 remains partly visible in reading area y172..975. Action remains accessible at x939.92, y178, width30, height32.
- Physical mouse movement and click opened the matching saved Chinese translation. No model translation, queue submission, or boundary-review request was issued by this check; no browser script errors.
- Screenshots in .local-runtime: nl2repo-action-attached.png, nl2repo-action-clipped.png, nl2repo-action-opened.png.
- New desktop and narrow regressions failed against the old detached action before implementation and passed after the change.
- Fresh disposable database run of translation-reading.spec.ts and workspace.spec.ts:42 passed; one next-page test encountered ENOSPC while writing browser tracing files at context close. That next-page test was rerun with tracing disabled and output in the system temporary directory:1 passed. All28 translation regressions passed in the fresh run.
- Earlier repeated runs against a reused disposable database produced duplicate-import and duplicate-note failures; rebuilding only the disposable backend removed those failures. Personal library data was not reset.
- npm run build passed (TypeScript and Vite,1965 modules); existing bundle size warning remains.
- git diff --check for the changed tracked implementation/test files passed; line-ending normalization warnings only.

## Operational boundary

The real application was checked through its running frontend on127.0.0.1:5173 and backend on127.0.0.1:8000. Neither live service was restarted. Disposable test services used5177 and8010. The ambient59877 address refused connections during this session. No personal model credentials or library mutations were needed for the live cached-translation check. D: had approximately100MB free when ENOSPC was investigated.
