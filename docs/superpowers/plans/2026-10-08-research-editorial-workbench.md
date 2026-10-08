# Research Editorial Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved research-editorial-workbench visual baseline across the React UI and rewrite the README around real user workflows and product boundaries.

**Architecture:** Keep the existing page and data architecture. Rework the shared visual tokens and page composition in place, add a focused-paper detail state to the library, and preserve current intelligence, PDF, metadata, and navigation contracts. Use the existing Playwright fixture backend for behavior checks and add only UI contracts that verify user-visible states and transitions.

**Tech Stack:** React 18, TypeScript, Vite, lucide-react, CSS custom properties, Playwright, FastAPI fixture backend.

---

### Task 1: Add failing UI contracts for the approved information hierarchy

**Files:**
- Create: `frontend/tests/editorial-workbench.spec.ts`
- Read: `frontend/tests/workspace.spec.ts`

- [ ] **Step 1: Write the failing tests**

Add a Playwright test that opens the library and asserts the new semantic landmarks exist: `.library-toolbar`, `.paper-table`, `.library-selection-detail` is hidden before a row is focused, and focusing a paper title exposes that detail with “打开阅读器”. Add a second test that enters the librarian and confirms the scope label and composer remain visible after a source navigation round trip.

```ts
test('library focuses a paper and exposes next actions without dashboard chrome', async ({page}) => {
  await page.goto('/')
  await expect(page.locator('.library-toolbar')).toBeVisible()
  await expect(page.locator('.paper-table')).toBeVisible()
  await expect(page.locator('.library-selection-detail')).toHaveCount(0)
  await page.locator('.paper-name > button').first().click()
  await expect(page.locator('.library-selection-detail')).toBeVisible()
  await expect(page.getByRole('button', {name: '打开阅读器', exact: true})).toBeVisible()
})
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm --prefix frontend run test:e2e -- editorial-workbench.spec.ts`

Expected: FAIL because the current library has no `.library-toolbar` or focused-paper detail.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add frontend/tests/editorial-workbench.spec.ts
git commit -m "test: define research editorial library landmarks"
```

### Task 2: Establish the visual system and shell behavior

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/intelligence.css`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Shared.tsx`
- Test: `frontend/tests/editorial-workbench.spec.ts`

- [ ] **Step 1: Add the approved visual tokens and motion rules**

Replace the current primary accent and surface hierarchy with the approved warm editorial palette: cream content surface, charcoal navigation, muted orange action/evidence color, and neutral status colors. Add `prefers-reduced-motion` overrides, a 160–220ms transition token, `.page-transition`, `.focus-ring`, `.sr-only`, and shared styles for restrained toast, modal, empty, loading, and error states.

- [ ] **Step 2: Make shell navigation and page headings object-first**

Update `App.tsx` so navigation labels remain visible and explicit, the topbar shows a plain breadcrumb and search affordance, and page changes apply the transition class without hiding content. Preserve the existing keyboard shortcut and reader origin behavior.

- [ ] **Step 3: Simplify shared state components**

Update `Shared.tsx` to use semantic status regions, keep empty states to one primary action, and give modal backdrops a visible focus path while preserving current props and test selectors.

- [ ] **Step 4: Run the focused test and production build**

Run: `npm --prefix frontend run test:e2e -- editorial-workbench.spec.ts`

Run: `npm --prefix frontend run build`

Expected: the shell assertions pass; the focused-paper assertion remains red until Task 3.

- [ ] **Step 5: Commit the shell polish**

```powershell
git add frontend/src/styles.css frontend/src/intelligence.css frontend/src/App.tsx frontend/src/components/Shared.tsx
git commit -m "style: establish editorial workbench visual system"
```

### Task 3: Recompose the library around the paper table

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/components/AnalysisBadge.tsx`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/editorial-workbench.spec.ts`

- [ ] **Step 1: Add focused-paper state and the semantic toolbar**

Add `focusedPaperId` state, set it when a title or row is activated, clear it when filters change, and render `.library-toolbar` with search, AI state, reading status, favorites, sorting, and import actions. Keep batch selection independent from row focus.

- [ ] **Step 2: Replace dashboard statistics with useful library facts**

Remove the dominant four-column KPI strip. Render a compact facts line containing total papers, completed analysis, pending analysis, and local-only papers. Use the existing intelligence status data so the facts stay accurate.

- [ ] **Step 3: Render the focused-paper detail and next actions**

When a paper is focused, render `.library-selection-detail` below the table with title, authors, venue/year, metadata confidence, analysis coverage, missing fields, “打开阅读器”, “查看论文卡片”, and “重新分析”. Each action must reuse current callbacks and never invent backend state.

- [ ] **Step 4: Make analysis state text-first**

Update `AnalysisBadge` and related CSS so every state includes short text plus a dot or spinner. Preserve current locale keys and add only missing plain-language labels such as “仅原文”, “需重试”, and “部分完成”. Avoid pill-only styling.

- [ ] **Step 5: Run the focused test to verify it passes**

Run: `npm --prefix frontend run test:e2e -- editorial-workbench.spec.ts`

Expected: library toolbar, paper table, focused detail, and next-action assertions pass.

- [ ] **Step 6: Commit the library composition**

```powershell
git add frontend/src/pages/LibraryPage.tsx frontend/src/components/AnalysisBadge.tsx frontend/src/styles.css frontend/src/locales/zh-CN.json frontend/src/locales/en-US.json frontend/tests/editorial-workbench.spec.ts
git commit -m "feat: recompose library as editorial paper table"
```

### Task 4: Refine reader, evidence, and analysis controls

**Files:**
- Modify: `frontend/src/pages/ReaderPage.tsx`
- Modify: `frontend/src/components/Notebook.tsx`
- Modify: `frontend/src/components/PaperCard.tsx`
- Modify: `frontend/src/components/AnalysisControl.tsx`
- Modify: `frontend/src/components/PdfViewer.tsx`
- Modify: `frontend/src/components/pdf-viewer.css`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/workspace.spec.ts`
- Test: `frontend/tests/intelligence.spec.ts`

- [ ] **Step 1: Add reader landmarks without changing data contracts**

Give the reader a stable title line, explicit back action, and `.reader-research-panel` wrapper. Keep PDF as the main reading region and make notebook tabs the only local panel navigation.

- [ ] **Step 2: Rework evidence and card hierarchy**

Use typography and left rules for card sections, show missing fields as plain “未提供内容”, and make evidence links visually consistent with the reader’s orange locator action. Keep every evidence button wired to the existing `jumpEvidence` callback.

- [ ] **Step 3: Make analysis status and coverage compact**

Keep the current phase, coverage, usage, cancellation, retry, published report, and attempt report behavior, but reduce nested containers and label the next available action directly.

- [ ] **Step 4: Add restrained locator feedback**

Preserve PDF coordinates and evidence overlays, but add one short highlight transition and reduced-motion behavior. Do not change PDF extraction or navigation logic.

- [ ] **Step 5: Run existing reader and intelligence contracts**

Run: `npm --prefix frontend run test:e2e -- workspace.spec.ts intelligence.spec.ts`

Expected: evidence location, notes, analysis coverage, cancellation, partial reports, and source navigation remain green.

- [ ] **Step 6: Commit the reader polish**

```powershell
git add frontend/src/pages/ReaderPage.tsx frontend/src/components/Notebook.tsx frontend/src/components/PaperCard.tsx frontend/src/components/AnalysisControl.tsx frontend/src/components/PdfViewer.tsx frontend/src/components/pdf-viewer.css frontend/src/styles.css frontend/tests/workspace.spec.ts frontend/tests/intelligence.spec.ts
git commit -m "style: refine reader evidence and analysis workflow"
```

### Task 5: Refine librarian, knowledge, researcher, and settings pages

**Files:**
- Modify: `frontend/src/pages/LibrarianPage.tsx`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/pages/ResearchersPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/intelligence.css`
- Test: `frontend/tests/intelligence.spec.ts`
- Test: `frontend/tests/workspace.spec.ts`

- [ ] **Step 1: Recompose AI 文献员 as a scoped research tool**

Make scope, retrieved-paper count, coverage, and composer visible as one coherent layout. Keep answer claim labels and citation callbacks unchanged. Add visible “打开原文” affordances and preserve conversation when returning from a citation.

- [ ] **Step 2: Reduce dashboard treatment in knowledge and researcher views**

Use plain section headers, compact filters, and evidence-aware relation labels. Keep graph, timeline, comparison, concept, and author data rendering intact.

- [ ] **Step 3: Make settings factual**

Use a compact configuration summary that states actual provider, protocol, model, reasoning effort, timeout, and data path. Keep key handling and current backend values unchanged.

- [ ] **Step 4: Run librarian and knowledge tests**

Run: `npm --prefix frontend run test:e2e -- intelligence.spec.ts workspace.spec.ts`

Expected: scopes, claim labels, source navigation, knowledge tabs, researcher data, and settings remain green.

- [ ] **Step 5: Commit the supporting pages**

```powershell
git add frontend/src/pages/LibrarianPage.tsx frontend/src/pages/KnowledgePage.tsx frontend/src/pages/ResearchersPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/styles.css frontend/src/intelligence.css frontend/tests/intelligence.spec.ts frontend/tests/workspace.spec.ts
git commit -m "style: align research pages with editorial workflow"
```

### Task 6: Rewrite README and user-facing documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

- [ ] **Step 1: Rewrite README around a first successful session**

Lead with what the user can do in ten minutes: start, import a PDF or link, inspect metadata, read, choose analysis, verify evidence, ask across papers, and back up data. Keep model configuration and known boundaries factual.

- [ ] **Step 2: Rewrite the guide’s page descriptions**

Describe every page by its user decision and next action. Document the fixed analysis states, local-only behavior, citation navigation, batch preflight, and librarian scope limits.

- [ ] **Step 3: Update implementation status**

Record the editorial UI pass, preserve the actual backend and intelligence limitations, and remove process history that does not help a user evaluate the product.

- [ ] **Step 4: Check documentation links and wording**

Run: `rg -n "TODO|TBD|解锁|开启旅程|智能洞察|placeholder" README.md docs/USER_GUIDE.md docs/IMPLEMENTATION_STATUS.md`

Expected: no template marketing language or unresolved placeholders remain.

- [ ] **Step 5: Commit the documentation pass**

```powershell
git add README.md docs/USER_GUIDE.md docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: rewrite workspace guidance around real workflows"
```

### Task 7: Full verification and visual review

**Files:**
- Modify: `frontend/test-artifacts/` only for generated screenshots; do not commit generated artifacts unless already tracked.

- [ ] **Step 1: Run the production build**

Run: `npm --prefix frontend run build`

Expected: TypeScript and Vite complete without errors.

- [ ] **Step 2: Run the full browser suite**

Run: `npm --prefix frontend run test:e2e`

Expected: all existing and new UI contracts pass at desktop and narrow widths.

- [ ] **Step 3: Run the backend suite**

Run: `python -m pytest backend/tests -q`

Expected: all backend tests pass; this UI pass must not change intelligence or import contracts.

- [ ] **Step 4: Inspect screenshots and diff**

Review `frontend/test-artifacts/library-light.png`, `frontend/test-artifacts/library-dark-1080.png`, `frontend/test-artifacts/reader-evidence.png`, and the librarian screenshots for clipping, unreadable status text, accidental dashboard repetition, and focus visibility.

- [ ] **Step 5: Run final diff checks**

Run: `git diff --check HEAD~7..HEAD`

Expected: no whitespace errors. Confirm `test_papers/` remains untracked and untouched.
