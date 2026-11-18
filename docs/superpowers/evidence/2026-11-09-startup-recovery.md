# White screen on reopening

## Diagnosis

The reported address was correct. The live frontend HTML, entry module, backend health and paper-list endpoints returned HTTP 200. A warm Chromium session rendered the shell in 890 ms, so the screenshot alone did not establish a persistent server failure.

An isolated Vite instance on port 5189 with a fresh dependency cache reproduced the startup gap: it accepted connections after 74 ms, but the browser reached DOMContentLoaded after 18.963 seconds and rendered the shell after 19.555 seconds. Initial loading involved 133 resources and 8.93 MB. Dependency optimization delayed entry/framework requests. The original HTML had an empty root and the launcher checked only HTML/API responses, leaving the screen blank until the complete application graph loaded.

During validation, PowerShell 7 and Windows PowerShell also produced different source fingerprints for identical files. Their default culture sorts order names such as `knowledge.py` and `knowledge_maintenance.py` differently. This could incorrectly reject reuse when switching between the desktop launcher and developer shell. Source and build inventories now use ordinal ordering.

## Changes

- Daily launch builds the frontend before opening a browser, then serves compiled files using Vite preview and the existing API proxy. Source and output fingerprints permit reuse only of a matching, intact build. Development hot reload remains available through `npm run dev`.
- Running-instance fingerprints now include frontend source/public files and the startup entry. Readiness fetches the built JavaScript entry, preloaded modules and stylesheet, rejecting missing assets or SPA HTML fallback responses.
- The HTML contains a dependency-free startup view. Successful React commit dismisses it; loading/render errors expose retry. An error boundary handles React rendering failure. A slow backend request retains the normal navigation/loading UI.
- Local health checks allow five seconds rather than treating a busy one-second response as a dead service. The command launcher prints the actual script's address rather than an unconditional fixed-port message.

## Verification

- Before the HTML/React changes, the delayed-entry, failed-entry and render-error browser regressions failed with no visible recovery screen. Afterward, all four startup cases passed. Startup plus existing workspace-shell tests passed together: **7 passed**, using the isolated test backend.
- Frontend TypeScript/production build passed. The existing large-chunk warning remains; this change does not claim complete application code splitting.
- Build reuse/invalidation and asset-readiness tests passed; malformed records, changed source/output, missing assets and HTML fallback are rejected.
- Startup/stop process-identity and cleanup simulations passed in PowerShell 7 and Windows PowerShell. Cross-shell source, frontend-source and output fingerprints matched after ordinal ordering was applied.
- The real instance was restarted with the normal launch script, preserving the database and queued work. A subsequent restart reused its build without running Vite build again.
- Three fresh browser contexts against the compiled live frontend rendered the shell in **580, 209 and 176 ms**; all 50 paper rows became available in **4894, 3572 and 2982 ms**. These are local measurements, not a guaranteed latency bound. No page errors occurred; the survey's first PDF canvas rendered successfully.
- A built-entry network failure displayed the retry action; unblocking it and clicking retry restored the shell and all 50 papers.
- Final launch used Windows PowerShell (the same engine as the command launcher); subsequent PowerShell 7 launch reused the running instance and confirmed a valid build. A fresh browser after this final restart rendered the shell in 403 ms and all 50 papers in 3977 ms, with no page errors.
- Targeted startup-view screenshot: `.local-runtime/startup-loading.png`; live-library screenshot: `.local-runtime/startup-library.png`. Both remain outside Git.

## Scope

This addresses a reproduced cold-start white-screen path and adds failure recovery. It cannot establish the exact browser-side event behind the original screenshot, whose console/network trace was unavailable. User research data, provider profiles and queue policies were not edited. Previous translation-queue changes remain separate in the working tree.
