# arXiv download timeout — 2026-10-19

Reported URL: `https://arxiv.org/abs/2304.03442?utm_source=chatgpt.com`.

The tracking query is correctly discarded when resolving the PDF URL. The PDF
is 11,947,867 bytes and contains 22 pages. Direct transfers measured roughly
30–40 KB/s; the original downloader returned HTTP 504 at 180.31 seconds.
The machine has a system proxy, but the download transport ignored it.
A 1 MiB range took about 26–30 seconds directly and 0.96 seconds via the proxy.

The transport now reads system/environment proxy settings and honors bypasses.
Every redirect still validates public addresses and pins the selected IP. Proxy
tunnels use a context scoped to the original hostname, with certificate and
hostname verification enabled; the proxy's own TLS uses its separate context.
This handles httpcore's CONNECT path ignoring the direct SNI extension.
The overall PDF limit is now ten minutes, while individual reads retain their
15-second timeout and downloaded PDFs remain limited to 50 MiB.

Verification:

- Acquisition and metadata import tests: **65 passed**. Regressions cover the
  exact URL, slow progress versus the overall limit, proxy/bypass selection,
  pinned CONNECT targets and distinct origin/proxy TLS hostnames.
- Workflow and PDF metadata tests: **58 passed**. Both runs reported the existing
  Starlette/httpx deprecation warning.
- The real URL was imported through the running frontend API with analysis
  disabled: HTTP 201, title **Generative Agents: Interactive Simulacra of Human
  Behavior**, 22 pages. Before proxy support that operation took 335.36 seconds.
- The fixed downloader retrieved the complete PDF in **6.26 seconds**. SHA-256
  matched the imported original:
  `1b31e77fb24d25d7598f2c49e955d12a28b95a6dabad34acdac40f44bfb7a139`.
- After restarting the backend, importing the exact URL through port 5173 took
  **7.91 seconds** and correctly returned HTTP 409 for the existing paper.
  Fetching that paper's PDF through the API reproduced the same hash. The 409
  confirms download and duplicate checking, rather than a second fresh import.
- Scoped `git diff --check` passed. No paid model requests were made.

Timings describe this machine and network during verification, not a service
guarantee. Raw verification records are ignored files under `.local-runtime/`.
