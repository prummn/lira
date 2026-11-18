# Startup recovery

Goal: eliminate the verified cold-start white screen without changing library data or queue settings.

Evidence: an isolated Vite server with a new dependency cache accepted HTML immediately but took 19.555 seconds to render the workspace; the browser loaded 133 resources and 8.93 MB before the shell. The launcher checked only HTML and API health.

Implementation and validation:

- [x] Add browser regressions for delayed/failed entry scripts, initial render failure, and slow library requests. Confirm existing behavior fails the relevant cases.
- [x] Keep an inline, dependency-free startup view visible until React mounts. Show a retry action for failed loading or rendering.
- [x] Build frontend assets before daily launch and reuse only a matching, intact build. Include frontend source in running-instance version checks. Keep `npm run dev` available for development.
- [x] Serve the build with Vite preview and the existing backend proxy. Readiness must fetch the actual built entry script, not just HTML. Validate build invalidation, process ownership, preview proxy, TypeScript/build and isolated browser cases.
- [x] Restart the actual instance preserving all data, then measure fresh-browser shell loading and verify library retrieval. Document measured limits.

The user's existing request authorizes fixing startup and verifying reopening. No new approval or model call is required. Existing unrelated translation-queue changes remain intact.
