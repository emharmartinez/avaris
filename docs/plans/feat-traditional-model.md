# Plan: Traditional model tab (pregame and live)

- **Date:** 2026-10-14 ·
- **Task:** a rule-based (no machine learning) NBA model in its own dashboard tab, covering moneyline, spread and over/under, pregame and live
- **Status:** Ready for implementation
- **Complexity**: `L`
- **Estimate Points**: `8`

---

## 1. Goals

- A second model, separate from the ML ladder, built only from fixed formulas: Elo, season-to-date efficiency ratings, home court and back-to-back rules
- Each game shows a fair moneyline (win probability), a spread (margin) and a total, with 80% intervals
- Live games update from the current score, period and clock; finals show the result next to the pregame numbers

**Success criteria:**

- `GET /api/traditional?date=` returns every game of the day with `pregame` numbers, and `live` numbers for in-progress games
- A "Traditional" tab lists the games with Moneyline, Spread and Total columns, a status badge (upcoming, live with period and clock, final) and polls while a game is live
- pytest, ruff, pyright, lint, typecheck, Vitest, build and Playwright E2E pass

---

## 2. Context

- `features` (`src/avaris/db.py:168`) is point-in-time at `decision_ts`: `elo_margin` (home court included), season-to-date `*_ortg_std`, `*_drtg_std`, `*_pace_std` (migration 6), `*_gp`, `league_total`, `league_pace`, `home_court`, `no_fans`, `*_b2b`. Building on it keeps the model leakage-safe
- No live score, period or clock is ingested; `games.status` is only as fresh as the last schedule ingest (`src/avaris/ingest/nba_schedule.py:14`)
- `stats.nba.com/stats/scoreboardv3?GameDate=&LeagueID=00` answers with the existing browser headers: `gameStatus` (1/2/3), `period`, `gameClock` (ISO duration such as `PT05M23.00S` while live, empty when final), `regulationPeriods`, `homeTeam.score`, `awayTeam.score`. `cdn.nba.com` liveData returns 403 in and out of the sandbox
- `StatsClient.get_json(final=False)` overwrites one gz file per params under `live/` (no growth)
- `create_app` injects `clock` and `runners` (`src/avaris/api/main.py:62`); tests and the E2E fixture server run the real app with a frozen clock
- Web: the Edge tab is the pattern (thin `page.tsx` with Suspense, `*-route.tsx` reading query params, a view, pure logic in `lib/*.ts`); nav is `NAV` in `web/src/components/app-sidebar.tsx`

**Key files:**

| File | Why it matters |
| :--- | :--- |
| `src/avaris/traditional/pregame.py` | pregame rules (new) |
| `src/avaris/traditional/live.py` | clock parsing and the in-game update (new) |
| `src/avaris/ingest/scoreboard.py` | scoreboardv3 fetch and parse (new) |
| `src/avaris/api/routes/traditional.py` | `GET /api/traditional` (new) |
| `src/avaris/api/main.py` | router and `live_scoreboard` injection |
| `web/src/lib/traditional.ts` | fair odds and labels (new) |
| `web/src/components/traditional/*` | route and view (new) |
| `web/src/app/traditional/page.tsx` | page (new) |

---

## 3. Decisions

| Decision | Choice | Why |
| :--- | :--- | :--- |
| What "moneyline, spread, over/under" means | The model's own fair lines: fair American odds from P(home win), the margin as a spread, the total; no odds are fetched (ADR-014) | Typed-odds comparison already lives in Edge |
| Inputs | The latest `features` row per game | Point-in-time by construction, same leakage guarantee as the ML model |
| Margin | `(1 - w) * elo_margin + w * eff_margin`, `w = 0.5 * g / (g + 10)`, `g = min(home_gp, away_gp)` | Elo carries the early season; ratings take up to half as games accrue |
| Efficiency | `L = 100 * league_total / (2 * league_pace)`; points per 100 = own `ortg_std` + opp `drtg_std` - `L`; pace = `home_pace_std + away_pace_std - league_pace`; `eff_margin = pace * (home - away) / 100 + 2.5 * home_court * (0.5 if no_fans else 1)` | Classic additive ratings model, no fit |
| Total | `(1 - s) * league_total + s * eff_total`, `s = g / (g + 10)` | Regressed to the league until ratings have games |
| Rest | -1.5 points to a team on a back-to-back | Common handicapping rule |
| Injuries | Left out of v1 | `lost_report` is in game-score units; a points conversion would need a fit (issue) |
| Win probability | `Phi(margin / sigma_margin)` | One distribution for all three markets |
| Sigmas | Fixed: residual std on 2015-16 to 2019-20 regular season, rounded to 0.5 | Tuning window only; 2025-26 untouched |
| Live margin | `lead + mu_pre * r`, `sigma = sigma_pre * sqrt(max(r, 0.5 / 48))`, `r = minutes left / 48` | Stern's Brownian-motion model |
| Live total | `points so far + rate * minutes left`, rate = `(1 - v) * total_pre / 48 + v * live rate`, `v = elapsed / (elapsed + 24)` | Half weight on the observed rate at halftime |
| Live source | `scoreboardv3` through `StatsClient` (`final=False`), held in an in-memory 30 s TTL cache on `app.state`; never written to DuckDB | Single-writer rule untouched; one request covers all games |
| When to fetch | Only for today's date (ET) with a game tipped off and not final in `games`; failures return `live_error` and pregame still shows | No requests outside game windows |
| Live status | From the scoreboard when present, else `games.status` | The schedule ingest lags |
| Evaluation | One-off report on the tuning window vs Elo, recorded in ADR-024; not added to the ladder | Informational, constants stay a priori |

---

## 4. Assumptions

| Assumption | Basis | Impact if false |
| :--- | :--- | :--- |
| Live `gameClock` is `PTmmMss.ssS` | Known scoreboardv3 format; not seen live this session | Parser accepts `PT..M..S`, `MM:SS` and empty; capture a live fixture later |
| scoreboardv3 updates during games | Used by nba.com | Live view lags; pregame unaffected |
| `features` has a row for every scheduled game the daily run has seen | Predictions exist for provisional games | Games without features show no pregame numbers |

---

## 5. Allowed Changes

**New:** `src/avaris/traditional/{__init__,pregame,live}.py`, `src/avaris/ingest/scoreboard.py`, `src/avaris/api/routes/traditional.py`, unit and integration tests, a recorded scoreboard fixture under `tests/fixtures/`, `web/src/app/traditional/page.tsx`, `web/src/components/traditional/*`, `web/src/lib/traditional.ts` and tests, an E2E spec

**Modified:** `src/avaris/api/main.py`, `tests/fixtures/web_server.py`, `web/src/components/app-sidebar.tsx`, `web/src/lib/{api,types}.ts`, `web/src/hooks/use-api.ts`, `web/public/sw.js`, `web/e2e/pages.spec.ts`, `scripts/traditional_check.py`, docs (ADR, STATUS, CHANGELOG, README)

**Not touched:** the ML pipeline, models, features, migrations, Edge

---

## 6. API contract

```
GET /api/traditional?date=YYYY-MM-DD   (date omitted: today ET)
{
  date, is_today, live_error: string|null, live_at: ts|null,
  games: [{
    game_id, season_type, tip_off_utc, home: Team, away: Team,
    status: "scheduled"|"in_progress"|"final",
    score: {home_pts, away_pts} | null,
    pregame: {p_home_win, margin: Interval, total: Interval,
              inputs: {elo_margin, eff_margin|null, eff_total|null, league_total,
                       weight, home_gp, away_gp, home_b2b, away_b2b}} | null,
    live: {period, clock, minutes_left, label, p_home_win, margin: Interval,
           total: Interval} | null
  }]
}
```

---

## 7. Steps

1. Pure `pregame.py` and `live.py` with unit tests (TDD)
2. `scoreboard.py` parse with a recorded fixture
3. Route, `create_app(live_scoreboard=...)`, TTL cache, API tests
4. Sigmas from the tuning window, ADR-024
5. Web lib, hooks, view, nav, Vitest, E2E
6. Docs, review, commit

---

## 8. Out of scope

Injury adjustment, the ESPN rest list, an Edge "model source" toggle, persisting live snapshots, evaluating the live model

---

## 9. Risks

- stats.nba.com may block bursts: the 30 s TTL keeps it to about 2 requests a minute while the tab is open on a live day
- Live-model calibration is unmeasured (no stored in-game history)
