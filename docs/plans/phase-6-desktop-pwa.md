# Plan: Phase 6 — Desktop PWA

- **Date:** 2026-10-12 ·
- **Task:** Next.js static-export PWA in `web/` served by FastAPI: Today, Game, Teams, Performance, Backtests and Injuries pages, a Refresh button, a drift flag, Playwright E2E
- **Status:** Done (2026-10-12)
- **Complexity**: `L`
- **Estimate Points**: `8`

---

## 1. Goals

- Show every game's prediction, its drivers, team strength, injury impact, live performance and backtests in an installable desktop PWA that talks only to the local API.
- Carry the Phase 5 security posture into the browser (#13).

**Success criteria:** the Phase 6 done-when in `avaris-nba-analytics-model-build-plan.md`: lint, typecheck, unit tests, Playwright E2E and build pass; every page renders with real data in Chrome; the app installs and opens in its own window.

---

## 2. Context

- API (`src/avaris/api/`, Phase 5, ADR-018): `create_app(settings, con, daily_on_startup, clock, runners)`. Routes: `/api/health`, `/api/predictions/today`, `/api/predictions?date=`, `/api/games/{id}`, `/api/teams`, `/api/teams/{id}?season=`, `/api/performance?season=`, `/api/backtests`, `/api/backtests/{name}`, `/api/backtests/{name}/charts/{chart}`, `/api/injuries?date=`, `POST /api/jobs/{daily,score,train}`, `/api/jobs`, `/api/jobs/{id}`.
- `TrustedHostMiddleware` allows loopback hosts only. Job posts with a non-loopback `Origin` or `Sec-Fetch-Site: cross-site` get 403 (`deps.not_cross_site`).
- Timestamps are UTC ISO strings with `Z`; `game_date_et` is a plain date. Unknown teams (non-NBA preseason opponents, #11) have `abbreviation: null`, `name: null`.
- `drivers` per target: `{base, families: {family: value}, scale: "log_odds"|"points", top: [{family, value}] x3}`. `injuries` per side: `{full_strength, lost, lost_share, players: [{player_id, name, status, value, lost}]}`, or `null` (preseason).
- Backtest reports: `artifacts/reports/<name>/report.md`, SVG charts, `predictions.csv.gz` with `game_id, season, season_type, y, pred, sigma, target, model, availability, ...`.
- Next.js 16.4 (`web/node_modules/next/dist/docs/`):
  - With `output: 'export'`, a static page that calls `useSearchParams` must sit inside `<Suspense>`, or the build fails.
  - `app/manifest.ts` is a special route handler, prerendered at build time.
  - Tailwind v4 is processed by the `@tailwindcss/turbopack` loader in `next.config.ts` `turbopack.rules` (no PostCSS config).
  - `next/font/google` fetches at build time; it is not used (local-only, offline builds).
- Playwright Chromium builds 1234 and 1248 are already in `~/.cache/ms-playwright`.

**Key files:**

| File | Why it matters |
| :--- | :------------- |
| `src/avaris/api/main.py` | app factory: static mount, CORS |
| `src/avaris/api/routes/performance.py` | live metrics; gains the drift block |
| `src/avaris/config.py` | `ServerSettings` gains `dev_cors`, `web_dir`, `drift_reference` |
| `src/avaris/cli.py` | `serve --dev` |
| `tests/fixtures/live.py` | synthetic league rounds D1/D2 used by the E2E server |
| `web/` | the PWA |

---

## 3. Decisions

| Decision | Choice | Why |
| :------- | :----- | :-- |
| Static routing | `trailingSlash: true`; FastAPI mounts `StaticFiles(web/out, html=True)` at `/` after the API routers, only if the directory exists; unknown `/api/*` paths return a JSON 404 | export emits `game/index.html`, which plain `StaticFiles` serves; API typos must not return HTML |
| Detail views | query params: `/game/?id=`, `/teams/?id=`, `/backtests/?name=`, `/injuries/?date=`, `/?date=` | no `generateStaticParams` needed |
| Dev CORS | `CORSMiddleware` with `allow_origin_regex` for loopback origins (`localhost`, `127.0.0.1`, `[::1]`, any port), methods GET/POST, header `content-type`, only when `server.dev_cors` is true (`avaris serve --dev`) | #13: dev only and loopback only, so it cannot reopen cross-site job posts |
| Markdown | `react-markdown` + `remark-gfm`, no `rehype-raw` (raw HTML rendered as text) | #13 |
| Charts in reports | `<img src="/api/backtests/{name}/charts/{chart}">` | served with `default-src 'none'`; an `<img>` never runs SVG script |
| Drift flag | per scope (regular, preseason, postseason), the live mean log loss, `margin` MAE and `total` MAE over `n` scored games is compared with `n`-game means resampled (2,000 draws, fixed seed) from the reference backtest's per-game errors (`model == "model"`, `availability == "report"`, same season types). Worse than the `1 - 0.05/3` quantile = drift (one-sided, Bonferroni; ~5% false alarms per scope). Reference: `server.drift_reference`, default `evaluation_2021-22_2024-25` | the report's own CI is for a ~5,000-game mean and would flag any small live sample; the report-mode evaluation matches live availability and is not the holdout |
| Today's date | `/api/health` gains `today` (ET date by the app clock) | the Injuries page and the frozen-clock E2E need the server's date |
| Data fetching | TanStack Query, client components only; `NEXT_PUBLIC_API_BASE` (empty in prod) | static export rules |
| UI kit | shadcn/ui (Card, Table, Badge, Tabs, Button, Select, Skeleton, Sidebar, Chart) on Tailwind v4; Recharts via the shadcn chart | build plan |
| Service worker | hand-written `public/sw.js`: cache-first for `/_next/static/*` and icons, network-first with cache fallback for navigations (keyed by path), never touches `/api/*`; cache name stamped with the build id by `scripts/stamp-sw.mjs`; registered in production builds only | an app shell that opens offline, with data always live |
| Icons | generated PNGs (192, 512, maskable 512) checked in | install criteria |
| E2E server | `tests/fixtures/web_server.py`: builds the synthetic league, trains before D1, finalizes and scores D1, writes D2 provisionals, writes a small backtest report, then serves `create_app` (the same app as `avaris serve`) with a frozen clock and an offline `daily` runner via uvicorn on port 8765 | deviation from "against `avaris serve`": the fixture league is in 2021, so the clock must be frozen |
| Test split | Vitest projects: `node` for `src/**/*.test.ts`, `jsdom` for `src/**/*.test.tsx`; msw for API mocks in component tests | CLAUDE.md |
| CI | add a `web` job: `npm ci`, lint, typecheck, unit tests, build | gates must be green in CI too; E2E stays local (needs uv + Chromium) |

---

## 4. Assumptions

| Assumption | Basis | Impact if false |
| :--------- | :---- | :-------------- |
| Chrome on Windows reaches `localhost:8000` in WSL | WSL2 localhost forwarding | the real-data check needs the WSL IP; it is not a loopback host, so the API refuses it |
| Installing the PWA can only be confirmed in a real browser | Chrome install UI | the install check is a ui-verifier or user step |
| shadcn CLI 4.x works with Next 16.4 and Tailwind v4 | current versions | hand-add the components |

---

## 5. Allowed Changes

**Files to create:**

| File | Contents |
| :--- | :------- |
| `src/avaris/api/drift.py` | `reference_errors`, `drift` |
| `tests/unit/test_drift.py`, `tests/integration/test_api_web.py` | drift, static serving, CORS, health `today` |
| `tests/fixtures/web_server.py` | E2E server |
| `web/**` | the PWA, its tests, Playwright config and specs |

**Files to modify:**

| File | Change | Anchor |
| :--- | :----- | :----- |
| `src/avaris/api/main.py` | CORS, `/api` 404, static mount, health `today` | `create_app` |
| `src/avaris/api/routes/performance.py` | `drift` in the response | `performance` |
| `src/avaris/config.py` | `ServerSettings.dev_cors`, `web_dir`, `drift_reference` | `ServerSettings` |
| `src/avaris/cli.py` | `serve --dev` | `serve_command` |
| `.github/workflows/ci.yml` | web job | `jobs` |
| `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `STATUS.md`, `ADR.md`, build plan | docs | |

**Files to delete:** none.

**Dependencies:**

| Package | Version | Why |
| :------ | :------ | :-- |
| `@tanstack/react-query` | latest 5.x | data fetching |
| `react-markdown`, `remark-gfm` | latest | backtest reports |
| `recharts` (via shadcn chart) | shadcn's pin | charts |
| shadcn/ui deps (radix, cva, clsx, tailwind-merge, lucide-react) | shadcn's pins | UI kit |
| dev: `vitest`, `@vitejs/plugin-react`, `vite-tsconfig-paths`, `jsdom`, `@testing-library/react`, `@testing-library/dom`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, `@playwright/test` | latest | tests |

**Schema changes:** none.

---

## 6. Implementation Plan

1. Python, TDD: `ServerSettings` fields; `create_app` CORS behind `dev_cors`; `/api/{path:path}` JSON 404; static mount; health `today`; `drift.py` and the `drift` block in `/api/performance`; `serve --dev`.
2. `tests/fixtures/web_server.py`, smoke-checked with curl.
3. Web foundation: dependencies, shadcn init and components, Vitest projects, `src/lib/{api,types,format,query}.ts` with node tests, app shell (sidebar, QueryClientProvider), manifest, icons, `sw.js` and its registration, Playwright config whose `webServer` runs `web_server.py` against the built `out/`.
4. Pages, each with logic in `src/lib/*.ts` (node tests), components with jsdom tests, and a Playwright spec: Today (+ Refresh flow), Game, Teams, Performance (+ drift), Backtests (markdown + `<img>` charts), Injuries.
5. CI web job; docs; reviews (code-reviewer, security-auditor); real-data check in Chrome with `avaris serve` on the real DB; install check.

**Testing approach:** TDD for the Python changes and `web/src/lib`; component tests for rendering and interaction; Playwright for every page and the Refresh flow. Styling is test-after.

---

## 7. Scope

**In scope:** the six pages, Refresh, PWA install, static serving, dev CORS, drift flag, #13.
**Out of scope:** #11 (non-NBA opponents, shown as "Team <id>"), #12, season simulation, player projections, dark-mode polish beyond the shadcn defaults, triggering `score` or `train` from the UI.

---

## 8. Acceptance Criteria

- [x] `npm run lint && npm run typecheck && npm run test && npm run build` and `npm run test:e2e` pass
- [x] `uv run ruff check && uv run pyright && uv run pytest` pass
- [x] Tests cover the CORS allow-list (loopback allowed, foreign origin refused, no CORS headers when off) and the markdown renderer (raw HTML shown as text) (#13)
- [x] The Performance page shows the drift flag
- [ ] Every page renders with real data in Chrome from `avaris serve`
- [ ] The app installs from Chrome and opens in its own window

---

## 9. Definition of Done

- [x] All gates green locally and in CI
- [x] Code review and security audit findings fixed or filed as issues
- [x] CHANGELOG, README, STATUS, ADR, CLAUDE.md and the build plan updated

## 10. Risks and Open Questions

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| Service worker serves a stale shell after an update | old UI after a rebuild | cache name stamped per build; network-first navigations; `skipWaiting` + `clients.claim` |
| The `daily` job on Refresh runs 1-2 min with network | the UI looks stuck | poll the job, show its log line and a spinner, disable the button while it runs |
| Synthetic fixture lacks some shapes (null injuries, unknown teams) | untested UI branches | component tests with msw cover them |
