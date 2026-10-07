# Recover the observed real-paper failures

The user authorized direct, scientific fixes after the expanded trial ended with four transport failures, one incomplete reduction, and a partial card. Continue the approved local-first architecture and single worker in the existing workspace.

## Observed causes and chosen approach

The adapter collapses HTTP transport exceptions and streamed termination into message-only errors. The harness immediately fails a stage on any provider error. The reduction validator correctly rejects missing parent citations, but the harness cannot correct the rejected group. Synthesis correctly rejects malformed result fields and section mismatches, but leaves those entries missing without an attempted repair.

Keep the validators strict. Add typed, safe transport failures and bounded stage recovery. Correct a failed reduction group using its original facts and evidence, with short fact aliases and explicit local rejection reasons. Correct rejected card slots once as a batch; preserve accepted slots and verify every replacement against the original evidence. Never attach missing citations by assumption or declare a dropped entry repaired.

Alternatives considered: repeating the whole paper wastes successful stages and gives no targeted feedback; accepting missing citations or mechanically unioning parent citations can hide lost scientific propositions. Targeted corrections address the reproduced contract failures while retaining original evidence and successful caches.

## Limits and accounting

Transient requests get at most two retries per stage, with bounded, cancellable backoff and Retry-After capped at 30 seconds. Authentication, invalid requests, malformed outputs and exhausted output budgets do not enter the transport retry path. One content correction per failed reduction group and one batched card correction are allowed. All extra remote calls share a six-call budget per paper. Record every failed attempt, preserving unknown usage as unknown, and report resolved versus remaining rejections separately.

Exact extraction requests remain unchanged to reuse existing successes. Corrected reduction/card stages get distinct request-exact cache keys. A rejected synthesis may remain cached only when its correction yields a fully validated final card; a repeat still runs local validation and reuses the correction. Cancellation and original-source fingerprint checks remain mandatory.

## Acceptance

First reproduce transport interruption, exhausted retries, cancellation during backoff, missing reduction lineage, successful targeted card repair, and rejected foreign/null/duplicate replacements with isolated tests. Then run the complete backend/browser/build checks. Restart the sole backend only between tasks. Retry Adaptive-RAG and the four transport failures using the existing staged caches, then CRAG's partial card. Compare scientific claims and original PDF locations, retain previous cards until a validated replacement commits, and record actual final outcomes and usage without claiming external availability is guaranteed.
