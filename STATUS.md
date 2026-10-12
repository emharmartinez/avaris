# Status

- **Phase:** Phase 2 done (injuries + odds removal), PR #5 on branch `phase-2-odds-injuries`. Phase 1 merged (PR #2)
- **Pivot (2026-10-12):** Avaris is now an analytics model, not a betting model; The Odds API is dropped (ADR-014)
- **Plan:** `docs/plans/avaris-nba-analytics-model-build-plan.md`
- **Next:** merge PR #5, then Phase 3 (features + models)
- **Important!** The 2026-27 season starts in late October 2026. Live predictions need Phases 1-5 done, including the final refit through 2025-26.

## Phase 2 results (2026-10-12)

- **Injury reports: done-when passes.** `avaris ingest injuries` fetched 4,680 reports for 2021-22 to 2025-26 (7 slots missing on the CDN). `avaris ingest status --check`: every regular-season game has a report between tip-off - 12 h and tip-off - 60; unmatched player rows 0.01-0.8% per season (players with no stats rows in any season)
- **Odds removal: done.** Odds client, `CreditGuard`, slot planner, backfill, status and de-vig deleted with their tests and the `avaris odds` CLI group. Migration 4 dropped `odds_events`, `odds_snapshots` and `api_usage` from the real DB (they were empty); `avaris ingest status --check` still passes after it
- **Gates:** ruff clean, pyright 0 errors, pytest 130 passed (e2e included)
- **Data quirks found:** a wrapped injury reason ("(Nasal Fracture, Face Mask)") parses as a player row (merged back); games can be absent from a report when neither team lists a player

## Phase 2 smoke tests (2026-10-12)

1. **Injury reports: pass**
   - `nba-injury-report` 0.1.0 is on PyPI (AGPL, Python >= 3.12, pymupdf). Its parser reads reports from 2021-22, 2023-24, 2024-25 and 2025-26 cleanly, e.g. `Injury-Report_2022-01-15_05PM.pdf`: 123 rows, all with a team and a known status.
   - **URL formats:** hourly `Injury-Report_YYYY-MM-DD_HHPM.pdf` (the file is the HH:30 ET report) until about 2025-12-20, then every 15 minutes as `..._HH_MMPM.pdf`. The package's own fetcher only knows the hourly format, so Avaris fetches the PDFs itself and uses the package only to parse.
   - A missing report returns 403. Rows for teams that have not submitted have no player ("NOT YET SUBMITTED").

## Phase 1 results (2026-10-12)

- **Smoke tests:** stats.nba.com works from the sandbox with the full browser header set (minimal headers hang). `scheduleleaguev2` carries tip-off times for finished seasons back to 2012-13.
- **Ingest:** 520 requests for 2012-13 to 2026-27; reruns touch only the current season (39 requests).
- **`avaris ingest status --check`:** all checks pass
  - Regular-season games: 1,230 per season, except 2012-13 (1,229, cancelled BOS-IND), 2019-20 (1,059) and 2020-21 (1,080)
  - Every game has a `season_type`; every game from 2020-21 on has a tip-off (one 2015-16 preseason game has none)
  - 172 bubble games tagged neutral, 0 untagged; every non-preseason venue is in the arena CSVs
  - Every final game has 2 team-log rows; rosters for 30 teams per season
- **Data quirks found:** the cancelled 2013 BOS-IND game is listed in the team log with no result (dropped); `isNeutral` is only set from 2024-25 (ADR-010)
