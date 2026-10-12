# Status

- **Phase:** Phase 1 done (foundation + stats data), on branch `phase-1-foundation`
- **Plan:** `docs/plans/avaris-nba-betting-model-build-plan.md`
- **Next:** Phase 2, odds + injuries. Start with the two smoke tests (2021-22 injury PDF via `nba-injury-report`; Odds API plan tiers and pricing)
- **Important!** The 2026-27 season starts in late October 2026. Live picks need Phases 1-5 done, including the final refit through 2025-26.

## Phase 1 results (2026-10-12)

- **Smoke tests:** stats.nba.com works from the sandbox with the full browser header set (minimal headers hang). `scheduleleaguev2` carries tip-off times for finished seasons back to 2012-13.
- **Ingest:** 520 requests for 2012-13 to 2026-27; reruns touch only the current season (39 requests).
- **`avaris ingest status --check`:** all checks pass
  - Regular-season games: 1,230 per season, except 2012-13 (1,229, cancelled BOS-IND), 2019-20 (1,059) and 2020-21 (1,080)
  - Every game has a `season_type`; every game from 2020-21 on has a tip-off (one 2015-16 preseason game has none)
  - 172 bubble games tagged neutral, 0 untagged; every non-preseason venue is in the arena CSVs
  - Every final game has 2 team-log rows; rosters for 30 teams per season
- **Data quirks found:** the cancelled 2013 BOS-IND game is listed in the team log with no result (dropped); `isNeutral` is only set from 2024-25 (ADR-010)
