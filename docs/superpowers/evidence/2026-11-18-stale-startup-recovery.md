# Startup recovery after Windows PID reuse

## Reproduced failure

The normal Windows PowerShell launcher failed in `Get-WorkspaceProcess` when
calling `ToUniversalTime()` on a null `Get-Process.StartTime`.
The persisted November 13 service record referenced a backend PID that no longer
existed and a frontend PID now belonging to `vmnetdhcp.exe`. The replacement
process had a different CIM creation timestamp and an inaccessible StartTime.

## Repair

- Null startup timestamps cannot qualify as workspace processes or children.
- A different CIM creation timestamp proves PID reuse. Cleanup skips the
  replacement process and can remove the stale service record.
- Missing or unverified identity still prevents cleanup; malformed stored
  timestamps are rejected. Cleanup never stops a process merely by port or name.
- The normal launcher reuses a healthy instance with matching source fingerprint;
  otherwise it invokes identity-checked cleanup before starting services again.
  A different project root is still rejected.

## Verification

- Regression first reproduced the null StartTime failure; it now passes.
- All four `scripts/tests/*.tests.ps1` pass in Windows PowerShell.
- PowerShell 7 confirms matching source fingerprints across both shell versions.
- Normal `scripts/start.ps1 -NoBrowser` recovered the actual stale record and
  started the application at `http://127.0.0.1:5173`.
- A second normal launch reused the same running instance.
- Playwright Chromium: backend health and paper list returned HTTP 200;
  52 paper rows rendered, no page errors. Screenshot is stored locally at
  `.local-runtime/startup-recovery.png`.
- No database, PDF, provider configuration or queue edits were made for recovery.
