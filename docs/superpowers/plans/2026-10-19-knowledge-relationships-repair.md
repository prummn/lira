# Knowledge relationships repair

Goal: make real bibliographic links visible and keep the method map readable as the library grows.

The user's existing authorization covers implementation and visual decisions. Preserve stored confirmations, rejections, notes and unrelated work. No model call or reanalysis is needed to recover a reference explicitly present in the PDF.

Design: derive paper citations from the reference section, independently of semantic method relations. Match strong identifiers or complete distinctive titles, reconstruct references split across chunks/pages, return source excerpts and deterministic IDs. Project at read time so old imports and reverse import order work without migrating or overwriting data. Deduplicate against stored edges.

The method view focuses on one core method and its actual neighborhood. Switching methods retains their paper-local roles. Group parallel relations into one readable edge; selecting an edge reveals the separate meanings and evidence. Place comparisons/prior methods on the left, components/evaluation on the right, with adaptive height and horizontal scrolling on narrow screens. Show bibliographic references separately, with source-page access; never infer technical descent from a citation. Use the application's warm surfaces and restrained ink colors.

- [x] Add failing API tests for split references, identifiers, false positives, import order and scope.
- [x] Implement reference projection and graph integration, preserving stored provenance.
- [x] Add browser regressions for crowded maps, scoped relations, reference evidence and footer SVG sizes.
- [x] Replace fixed layout with the focused adaptive map and scoped styles.
- [x] Run targeted backend/browser tests and production build.
- [x] Restart the idle backend and verify Reflexion → ReAct on the actual library, including screenshots at desktop and narrow widths.

Root-cause evidence: production has 38 paper nodes but only 9 demo citation edges. Reflexion's reference [30] spans chunks 243–244 on page 11. Existing semantic relations record comparison and Actor reuse. Footer icons measure 432–475 px because `.knowledge-map-canvas svg` applies graph dimensions to Lucide icons. The old graph places 45 deduplicated nodes in a fixed 980×540 viewBox.
