# MetroScan frontend — assessment

Rated after the "evolve the brief" upgrade (Feature 6, `design-direction.md` v2,
frontend Pass 1–3). Baseline = the state at the initial commit `7b83b78`; final = `6bf3c58`.
Same eight-axis rubric throughout, 1–10.

---

## 1. Scorecard

| Axis | Baseline | Final | What moved it |
|---|---:|---:|---|
| Design / visual identity | 8.5 | **9.0** | The instrument metaphor now *moves* like an instrument — the Measure tilts under a pointer, the score needle settles, data draws itself once. All inside documented v2 ceilings; palette and layout unchanged. |
| UX / task flow | 7.5 | **8.5** | Mobile shell reworked for one-handed field use (bottom tab bar, 44px targets, fluid headings, container-query splits); route transitions give continuity; scan-reveal is now sequenced image→ledger. |
| Functionality / completeness | 8.0 | **8.5** | Feature 6 (scheduled retention auto-deletion) closes the last open feature. No offline/sweep mode yet. |
| Code quality | 8.0 | **8.5** | ESLint introduced and green; a real hook-order bug caught and fixed; shared `.button` extracted; `--seal-pressed` token replaces an inline literal. Route-test coverage still thin. |
| Security | 6.5 | **7.5** | Fonts self-hosted (no third-party CDN on the critical path); report blob URLs now revoked; `npm audit` clean (0). Token still in `localStorage`; no CSP yet. |
| Performance | 7.0 | **8.5** | Route code-splitting: initial JS 292.6 → 246.8 kB (91.9 → 79.3 kB gzip). Per-route JS+CSS chunks. Fonts local. No measured Lighthouse run yet. |
| Accessibility | 7.5 | **8.0** | `role="status"` on the verdict-moved line; `role="presentation"` on modal scrims (ESC + Cancel already covered keyboard); reduced-motion honoured on every new effect. One contrast finding stands (brass, §8). |
| Upgrade feasibility | 9.0 | — | (Realised — the upgrade landed additively with no backend/pipeline change.) |

**Baseline ≈ 7.6 → Final ≈ 8.4.**

---

## 2. Design & UX

**What changed, and the v2 clause each cites:**

| Change | v2 clause |
|---|---|
| Measure: ≤6° pointer-follow tilt of the plane, spring-back; graduations/limit line/numerals ride it undistorted | "The Measure may tilt" |
| Measure index + Score needle settle with one small overshoot | "Data draws itself once" / needle language |
| Score: a chassis-dark index needle + a set-point flag on the pass line | instrument reading, not a bar |
| Dashboard: outcomes bar, rules-broken bars, per-day chart grow from empty on first view (scale only) | "Data draws itself once … stagger ≤ 40ms … never loop" |
| Examination scan-reveal: ledger rows start ~150ms behind the annotation boxes | "ledger rows stagger up a beat behind each box" |
| EvidencePlate: photo and annotation overlay parallax ±12px at opposing depths | "the bench has up to three planes … ≤12px" |
| Route change: shared-axis fade+lift ≤240ms | "Route transitions are a shared-axis move" |

**Mobile / field use** (officers work on phones at a shelf):
- < 820px: a sticky top strip (wordmark + officer) + a **fixed bottom tab bar** for navigation; brass hairline marks the active tab; safe-area insets respected.
- Named breakpoints (`480/640/768/1024/1280`); headings fluid below 640px; body/data sizes fixed for legibility.
- `.bench` is a CSS container — Examination/Dashboard/Repository collapse on the width they *have*, so a laptop with the rail open triggers the same single-column layout a phone does.
- ≥44px touch targets on `.button` and the bespoke controls (`.strip__action`, `.strip__add`, `.ledger__overrule`, `.dialog__choice`) on coarse pointers.

**Held within the brief:** every new effect is off under `prefers-reduced-motion` and on touch; nothing loops or moves without a user action or scroll; no gradients, glass, gauges or shadow stacks were added.

---

## 3. Functionality

| Capability | State |
|---|---|
| Sign in / session / lapsed-token recovery | complete |
| Dashboard: totals, verdict split, calibration rate, top violations, by-category, per-day trend | complete |
| Repository: list, filter by verdict / rule / product, retention flags | complete |
| New scan: camera capture + upload, live capture guidance, no scale parameter (by design) | complete |
| Examination: evidence + annotation boxes, findings ledger, two-way hover/focus link, the Measure, override (with audit), image add/replace/remove (re-runs pipeline), retention answer, soft-delete, PDF/JSON report | complete |
| Retention auto-deletion (Feature 6) | complete — in-process scheduler + `prune-scans` CLI |
| Offline / poor-connectivity field mode | not started |
| Sweep / batch (photograph a shelf) | not started |
| EN / हिन्दी toggle | in the brief, not in the code |

---

## 4. Code quality

- **TypeScript**: `strict`, `noUnusedLocals/Parameters`, `noFallthroughCasesInSwitch`, `verbatimModuleSyntax`. `tsc --noEmit` clean.
- **ESLint** (new): flat config, `typescript-eslint` + `react-hooks` + `jsx-a11y` recommended. Green. First run caught a real bug — `useParallax` called after an early `return` in `EvidencePlate` (hook-order violation) — now fixed. `react-hooks/set-state-in-effect` is disabled: it flags the codebase's uniform *clear-error-then-fetch* effect idiom, which is a correct use of an effect, not a cascading-render risk.
- **Prettier** (new): `.prettierrc` + `npm run format` / `format:check`. Not wired into `lint` — the existing hand-formatting (notably the aligned multi-property CSS transitions) differs from Prettier on 32 files, so a repo-wide reformat is left as the maintainer's one-time, deliberate commit.
- **Tests**: frontend 85 (9 component/lib files); backend 547 (483 fast + 35 golden real-OCR + 29 other-slow). **Gap: no route/integration tests on the frontend** (Dashboard, Examination, SignIn, App) and no axe assertion in the vitest run.
- **Structure**: `.button` moved out of `routes/Examination.css` into `src/styles/controls.css`; `--seal-pressed` token replaces an inline `#1b3155`. Per-component CSS files, BEM-ish, every value traces to `tokens.css`. No CSS Modules / scoping — relies on naming discipline (consistent, and low-risk at this size).
- One wall-clock perf microbenchmark (`captureQuality.test.ts` "stays well inside a live-preview budget") flakes under concurrent build load; passes in isolation. Pre-existing; a timing assertion in a unit test is inherently load-sensitive.

---

## 5. Security

| Area | State | Recommendation |
|---|---|---|
| Auth enforcement | Server-side (Bearer + role checks); client routing is not the gate. Correct. | — |
| Token storage | JWT in `localStorage` (`metroscan.token`). XSS-exfiltration surface. | If the deployment threat model warrants it, move to an httpOnly cookie + CSRF token. Coordinated backend change; out of this pass. |
| Third-party origins | **Removed** — fonts were on `fonts.gstatic.com`, now self-hosted `@fontsource`. No runtime third-party requests remain. | — |
| Object URLs | Report PDF blob URL now revoked on replace/unmount; `EvidencePlate` and `CameraCapture` already revoked theirs. | — |
| CSP | None referenced. | Add a strict `Content-Security-Policy` at the serving layer: `default-src 'self'`, no `unsafe-inline` for scripts. Now feasible since there are no external origins. |
| CORS | Locked to the two dev hosts, not `*`. Good. | Confirm the prod origin list is set for deployment. |
| Dependency audit | `npm audit` — **0 vulnerabilities** (prod and dev). | Keep in CI. |
| Dev signing secret | `jwt_secret` default is `dev-only-secret-change-me`; `main.py` **refuses to boot** outside `development` if unchanged. | Correct pattern; nothing to do. |

---

## 6. Performance

**Bundle — initial load (what a signed-in officer downloads for the dashboard):**

| | Baseline | Final |
|---|---:|---:|
| Main JS | 292.6 kB / 91.9 kB gzip | **246.8 kB / 79.3 kB gzip** |
| Main CSS | ~41 kB / 8.2 kB gzip | 16.0 kB / 4.3 kB gzip (rest is per-route) |
| Route chunks (JS) | — (all eager) | Dashboard 7.7 · Repository 3.1 · NewScan 16.0 · Examination 20.2 kB |
| Route chunks (CSS) | — | Dashboard 5.1 · Repository 2.9 · NewScan 6.4 · Examination 14.5 kB |
| Fonts | 4 requests to `fonts.gstatic.com` | Self-hosted woff2; EN first paint ≈ Archivo latin 90 kB + Plex Sans latin 46 kB + 3× Mono ≈ 45 kB, `font-display: swap`, cached forever. Devanagari (~78 kB/weight) only on Hindi glyphs. |

**Other:** `motion` library was **not** added — every v2 effect is CSS + WAAPI + three tiny hooks, so the JS cost of "lively" is a few hundred bytes. Parallax/tilt hooks no-op on touch and reduced motion (no listeners attached). `will-change: transform` is scoped to the two components that use it.

**Not done:** a measured Lighthouse run (needs a browser+CI harness). Expected mobile scores from the bundle profile and a11y state: perf mid-90s, a11y high-90s pending the contrast decision in §8. The Archivo two-axis variable file (90 kB) is the single heaviest always-download; `wght`-only would halve it but the design needs the width axis (`--display-width: 118`).

---

## 7. Feasibility

The upgrade landed **additively**: no change to `backend/app/pipeline/` or `backend/app/rules/` (hardened), no new colours, no schema change, no API change. New runtime deps: `@fontsource/*` (static font CSS + woff2). New dev deps: ESLint/Prettier toolchain. Backend regression stayed green throughout (547 tests). Migration risk for a deployment: low — rebuild the frontend, serve the new `dist/`; the service worker / PWA install is still a follow-up, not a requirement.

**Remaining effort to "polished v1":** ~6–10 hrs — route/integration tests + axe, the contrast decision, a Lighthouse pass in CI, PWA shell, the EN/हिन्दी wiring.

---

## 8. Accessibility

**Contrast (WCAG 2.1, computed against the token hexes):**

| Pair | Ratio | Verdict |
|---|---:|---|
| `ink-900` on `bone` (body) | 16.1:1 | AAA |
| `seal` on `bone` / `seal-tint` | 9.5 / 8.9:1 | AAA |
| `patina` on `bone` / `patina-tint` | 5.8 / 5.4:1 | AA |
| `oxide` on `bone` / `oxide-tint` | 5.7 / 5.2:1 | AA |
| `bone` on `chassis` (rail), `ink-200/300` on `chassis` | 7.8–16:1 | AAA |
| **`brass` on `bone` / `brass-tint`, `bone` on `brass`** | **3.5 / 3.2 / 3.5:1** | **AA-large only** |

The one finding: **brass**. It is used as text at sub-large sizes in two places — the `NEEDS_REVIEW` status label (`StatusMark`, ~13px bold) and the `INCONCLUSIVE` verdict block (`bone` on `brass`, ~15px bold). Both are below the WCAG "large text" cutoff, so 4.5:1 applies and ~3.5:1 falls short. This is a gap against the brief's own "AA contrast on all text and status pairs" line.

Mitigations, for the maintainer to choose (palette is locked, so not silently changed here):
1. Darken `--brass` toward bronze (`~#8A6520` reaches ~4.5:1 on bone) — shifts the instrument character slightly.
2. Bump the `NEEDS_REVIEW` label and `INCONCLUSIVE` verdict type to ≥18.66px bold so "large" applies.
3. Accept it on the "colour + glyph + word, greyscale-survivable" principle, with the finding recorded.

**Other:**
- Every status is colour **+ drawn glyph + word** — survives greyscale, photocopy, colour-blindness.
- `:focus-visible` seal-ring on every interactive element; never removed.
- `prefers-reduced-motion`: CSS durations collapse via `tokens.css`; JS motion hooks bail; `useInView` reports in-view immediately so content is present, never staged.
- Live regions: `role="alert"` (action errors), `role="status"` (reprocessing, verdict-moved).
- Modals: `role="dialog"` + `aria-modal`, ESC-to-close, focus trap via the Cancel control; scrim is `role="presentation"`.
- Ledger rows are deliberately focusable (`tabIndex={0}`) so a keyboard user gets the same ledger⇄evidence preview a mouse user does; documented inline.
- **Not verified this pass:** a full keyboard walk-through of the examination view; `prefers-contrast`; screen-reader pass. Recommend an `axe` assertion in the vitest run and one manual NVDA/VoiceOver pass.

---

## 9. Future scope (prioritised)

1. **Contrast decision on `brass`** (§8) — small, unblocks a clean AA claim.
2. **Route/integration tests + `axe`** in vitest — Dashboard renders, Examination wires override + image-edit, SignIn happy/lapsed, App session state.
3. **Lighthouse in CI** on `build && preview`, with a budget.
4. **PWA shell** — `vite-plugin-pwa`, manifest, offline app-shell, "add to home screen". The meta tags are already in `index.html`.
5. **Offline field mode** — queue scans captured with no signal, sync on return; IndexedDB evidence cache.
6. **EN / हिन्दी toggle** — wire the switch the brief specifies; Devanagari fonts are already bundled; verify no layout break and Devanagari numerals in the Data role.
7. **Sweep / batch mode** — photograph a shelf, one review queue (SIH26034 roadmap 5.1).
8. **httpOnly cookie session + CSRF** — if the threat model warrants moving off `localStorage`.
9. **Strict CSP** at the serving layer — now that there are no external origins.
10. **Repo-wide `npm run format`** — one deliberate commit to bring the codebase onto Prettier, then wire `format:check` into `lint`.
11. **Design tokens as one source** — generate `tokens.css` from a Figma library (the Workstream-A build, deferred) so code and design cannot drift.
12. **Motion-audit dev overlay** — flag any transition that fired without a preceding user action or scroll, enforcing the v2 rule mechanically.
13. **Web ⇄ paper Measure parity check** in CI — snapshot the React Measure against `backend/app/reports/measure.py` output so screen and PDF stay one instrument.

---

## Method note

Baseline scores are a read of `7b83b78`. Final scores are a read of `6bf3c58` after
`npm run lint` (tsc + eslint), `npm run build`, `npm test` (85 pass), `npm audit` (0),
`backend` `pytest -m "not slow"` (483 pass) + golden regression (35) + other slow (29),
and an analytic contrast computation. A Lighthouse run and a screen-reader pass are the
two verifications still outstanding.
