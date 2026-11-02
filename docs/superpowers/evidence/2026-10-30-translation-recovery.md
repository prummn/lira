# Translation recovery and invalid cached output

## Confirmed issue

NL2Repo-Bench, paper-4357e2df19b64b3b, page 8, section 4.1 Experimental Settings, paragraph-f047610043e58a3241c58843 had complete English source but persisted the model reply `未提供待翻译的原文。` as a successful translation. The original model transport input for that attempt was not retained, so its upstream cause is unconfirmed. The application accepted nonempty failure prose without validation, reused it in direct/background caches, and provided no regeneration action for saved results.

## Changes

- Shared cache validation rejects empty and standalone missing-source replies, without treating arbitrary prose mentioning missing input as a failure. The same write path protects direct requests and queued work; invalid retries cannot replace a previous good translation.
- Reader payloads omit historical invalid translations and include an actionable error. Queue serialization cannot reintroduce them; retry can repair historical false successes, and startup recovery updates their persisted task states for the global monitor. Original translation rows are retained.
- Saved results expose a restrained Translate again action. It bypasses both local and server caches with force:true, retains readable text while waiting or after failure, and prevents stale background polling from replacing a manual regeneration.

## Verification

- Five regression cases initially failed for direct persistence, forced replacement, background completion, historical reader cache, and historical queue output. They passed after the fix. Startup-monitor regression also failed before its fix.
- Backend translation queue/cache and paragraph/boundary suites: 116 passed, one existing Starlette deprecation warning.
- New browser cases cover regeneration with failure recovery, an actionable historical error, and stale background polling. All passed.
- Full translation-reading suite: 29 passed and 2 initial failures at reload/PDF initialization. Both failing cases passed in a focused rerun, without changing application code. This is not a claim of a clean single-run browser suite.
- Production build passed, with the existing large-chunk warning. git diff --check passed, with existing line-ending warnings.
- Real live API force request used gpt-5.6-sol and replaced the bad NL2Repo result with the complete Chinese translation of the workspace/testing-image/pytest passage. A fresh reader API request returned that saved result.
- Live Chromium check on port 5173 displayed the repaired result and regeneration action; the button was within the viewport at widths 1440 and 780, with no page errors. Screenshot: C:/Users/15039/AppData/Local/Temp/lira-translation-recovered.png.

## Runtime boundary

The frontend changes and repaired paragraph were verified in the running application. The backend process on port 8000 still holds its older imported modules; the new validation/recovery code requires its next normal restart. An earlier controlled backend restart was rejected by automatic approval with only `blocked by policy`. No alternate restart, hot patch, or termination of the user's services was attempted.
