# Zero reserve means no local reserve

The user configured both the short-window stopping reserve and long-window reserve to zero. With reported short-window remaining at 100% and long-window remaining at 0%, the scheduler still stopped a queued full translation with `quota_reserve`. Both the backend and quota dialog compared `remaining <= reserve`, so zero was treated as a pause boundary despite the setting's documented meaning of keeping no reserve.

The shared policy now applies the reserve comparison only when the configured reserve is positive. Zero disables that window's local reserve check. Positive reserves, optional research's separate start threshold, known/fresh quota validation, foreground priority and actual provider rate-limit handling keep their existing semantics. This is a configuration-semantics fix, without a new probe mode or changed account/profile settings.

The quota dialog now labels zero as no reserve rather than saying the pause line has been reached. Its explanation and short-window help text describe zero explicitly.

Verification:

- Before the fix, four new policy cases and both manual/automatic full-translation queue cases failed at the local gate.
- After the fix: `tests/test_research_policy.py tests/test_translation_queue.py tests/test_background_research.py` — **125 passed**, one existing Starlette deprecation warning.
- `tests/quota-controls.spec.ts` — **2 passed**, using the isolated test backend. This includes a displayed exhausted weekly window with both reserves zero, and existing save/reload/failure behavior.
- `git diff --check` passed with line-ending normalization warnings only.

Runtime verification is separate from these controlled zero-balance cases: the official weekly reset was scheduled for 2026-11-10 10:13:43 +08:00, close to the deployment time. A subsequently available weekly balance cannot by itself prove the zero-balance behavior; that behavior is covered by the regression cases above.

The production build passed and the service restarted successfully. A new live browser session verified both zero-reserve labels in the deployed dialog. After deployment the official weekly quota had refreshed to 100% remaining. The original Agent Lightning job resumed without being resubmitted: a fresh status response showed **1/165 completed**, no quota-reserve reason and `in_flight: true`; official capacity was **4/4 active**. This establishes continuation of the existing queue, not completion of the paper or live acceptance while the reported weekly balance was zero.
