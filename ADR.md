# Architecture Decision Records

One entry per binding decision. Newest first. Status is `accepted`, `superseded` or `proposed`.

## ADR-025: ESPN's injury list stands in before a team's first game of the season

- **Date:** 2026-10-20 · **Status:** accepted · widens ADR-022's list to season openers, display only
- **Decision:**
  - A non-preseason game where either team has not yet played this season (`home_gp = 0` or `away_gp = 0`, both teams NBA) gets a `rest` row from ESPN's list, built exactly as in preseason (latest snapshot fetched in `[tip - 36 h, decision_ts]`, the same out rule, last season's rate).
  - **Never applied:** `apply_rest` keeps the model's `p_home_win`, margin and total, all `k` are 0, `raw_*` are null and the block's note says so. Model features, `feature_hash` and every prediction value are byte-identical with or without ESPN data (tested). Openers have no preseason box score, so `lost_actual` is NaN and the rest fit never reads them.
  - **Fetch:** `daily` also requests the list when such a game tips off within 36 h and has no final prediction (no earlier non-preseason game for one of its teams this season). Still one request per run.
  - **Display:** per side, the NBA strength lost when known, else ESPN's list: the Today card's injuries line, the Injuries tab (the NBA report entries stay; the side shows "X Game Score lost (ESPN)") and the game page ("ESPN injury list" section). A side with a report in force but no impact and no list reads "unknown before first game", not "no report".
  - **Traditional model:** its injury term already falls back to ESPN when `lost_report` is unknown (ADR-024), so on openers it now counts the list too, with no usual for either side.
- **Why:** user request. On opening night 2026-10-20 the NBA report of 18:00 UTC was ingested, but availability is missing before a team's first game (ADR-015: the player set is built from this season's appearances), so every side showed "no report". ESPN's list needs no player set.
- **Not done:** no ESPN fallback when no NBA report is in force at `decision_ts` for a team that has played.

## ADR-024: A rule-based Traditional model, pregame and live, in its own tab

- **Date:** 2026-10-14 · **Status:** accepted · narrows ADR-014 (fair lines from a second model; still no odds)
- **Decision:**
  - A second model with no machine learning (`src/avaris/traditional/`), shown in the Traditional tab (`/traditional/?date=`) and served by `GET /api/traditional?date=`. It never feeds features, the ML models, Performance or the evaluation ladder.
  - **Pregame**, from each game's latest `features` row (point-in-time at `decision_ts`, ADR-015):
    - Efficiency: league rating `L = 100 * league_total / (2 * league_pace)`; points per 100 = own `ortg_std` + opponent `drtg_std` - `L`; pace = `home_pace_std + away_pace_std - league_pace`; `eff_margin` adds 2.5 points of home court (halved without fans, 0 on a neutral site)
    - Margin: `(1 - w) * elo_margin + w * eff_margin`, `w = 0.5 * g / (g + 10)`, `g` = fewer games played of the two teams this season; -1.5 points to a team on a back-to-back
    - Total: `(1 - s) * league_total + s * eff_total`, `s = g / (g + 10)`
    - Win: `Phi(margin / 12.5)`; total σ 19.5. The two σ are the residual std on the 2015-16 to 2019-20 regular season (12.65, 19.26), rounded to 0.5; every other constant is a fixed rule
    - Preseason and the first game of a season (`g = 0`) are Elo and the league total only
    - **Injuries (amended 2026-10-14, #29):** margin `+= 0.15 * (away_excess - home_excess)`, in Game Score points (`rate x minutes`, as `*_lost_report`). `excess = lost_report - lost_usual`, where `lost_usual` is the team's 10-game half-life mean of `lost_report` over its earlier decisions with a report this season (NaN, counted as 0, until one is known): absences the team usually has are already in its Elo and ratings, so only the change counts, and a team missing less than usual gains. In preseason, which has no NBA report, and before a team's first game of the season, where the report cannot be valued (ADR-025), `excess` is the value ESPN lists out (ADR-022, read from the prediction's `rest` block), with no usual. No term unless both teams are known, and no report term when no report was in force at `decision_ts` (`report_ts` null: before 2021-22, or a morning before the day's first report), since `lost_report` then reads 0. The total is unchanged (ADR-022 found no usable total signal). The card's inputs line shows the points and the source
    - **Why 0.15:** a fixed rule, not fitted. A star (about 20 Game Score) newly out costs about 3 points, in line with common rules of thumb (2 to 5 points for an all-star); ADR-022's preseason fit (0.108 on actual absences) is the same order. Over 2021-22 to 2024-25 the excess difference has std 18.7 (26.0 without the usual), so a typical shift is about 2.8 points
  - **Live** (Stern's Brownian motion): with `r` = minutes left / 48, margin `= lead + μ_pre * r`, σ `= σ_pre * sqrt(max(minutes left, 0.5) / 48)`; total `= points so far + rate * minutes left`, rate `= (1 - v) * total_pre / 48 + v * points per minute so far`, `v = played / (played + 24)`. Overtime periods are 5 minutes; a tie at the buzzer counts one more 5-minute period.
  - **Live source:** `stats.nba.com/stats/scoreboardv3?GameDate=&LeagueID=00` through `StatsClient` (`final=False`, so `<paths.cache_dir>/live/scoreboardv3/` keeps the latest copy per date). Fetched by the API process only for the slate day (the ET date, rolling over at 4 am ET so late tips stay live past midnight) when a game has tipped off or is `in_progress` and not final in `games`; held in memory for 30 s; never written to DuckDB. A failed fetch returns `live_error` and the pregame lines. The scoreboard's status and score win over `games` (the schedule ingest lags). `cdn.nba.com` liveData returns 403. Superseded as the primary source by ESPN (below); kept as the fallback.
  - **ESPN live source (amended 2026-10-14, #30):** live scores come from ESPN's `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` first, and from `scoreboardv3` only when ESPN fails or has no games. On 2026-10-14 `scoreboardv3` ran 4 to 5 minutes behind the game (a final shown as 0:05 left for 6 minutes); ESPN was current.
    - ESPN has no NBA game ids, so both feeds are matched to `games` by `(home_team_id, away_team_id)` (one pairing a day); ESPN teams by display name, as for its injury list (ADR-022). A club outside the NBA gets live lines only from the fallback.
    - Status: `completed` is final, `state == "in"` is live, anything else (postponed included) is scheduled. Labels are built in the NBA's wording from the period and status (`3rd Qtr`, `Halftime`, `End of 2OT`, `Final/OT`); the clock is ESPN's seconds left.
    - Same timeout and retry; the in-memory cache is 5 s and the browser polls every 10 s while a game is live (was 30 s each, up to about 60 s behind the feed; now about 10 s); the latest response per date is kept under `<paths.cache_dir>/live/espn/`; never written to DuckDB. stats.nba.com is no longer called while ESPN answers.
  - Lines are shown as fair prices: a moneyline from the win probability (decimal by default, American on the toggle), the margin as a spread, the total; finals are graded against the pregame line. Nothing is compared with bookmaker odds (Edge does that, ADR-020).
  - **Over/under chance (amended 2026-10-14):** each card has a total line, starting at the pregame total and editable. The Total row shows P(over) and P(under) of that line for the pregame and the live total, read in integer bands as on the Edge tab (a whole-number line shows its push chance), and a final's total is graded against it. As with ADR-020, the line is typed in the browser only: never fetched, sent to the API or stored, and it resets on reload.
- **Why:** user request: a separate, non-ML model covering moneyline, spread and over/under, live games included.
- **Check (not used to choose; regular season):**

  | Window | Games | Log loss (Elo) | Margin MAE (Elo) | Total MAE (league avg) | 80% coverage margin / total |
  | :-- | --: | --: | --: | --: | --: |
  | 2015-16 to 2019-20 | 5,979 | 0.6112 (0.6167) | 9.88 (9.92) | 15.09 (15.79) | 0.81 / 0.81 |
  | 2020-21 to 2024-25 | 6,000 | 0.6195 (0.6389) | 10.77 (10.99) | 15.31 (15.70) | 0.77 / 0.81 |
  | 2021-22 to 2024-25, injury term | 4,920 | 0.6144 (0.6375) | 10.68 (10.94) | 15.36 (15.71) | 0.77 / 0.80 |
  | 2021-22 to 2024-25, no injury term | 4,920 | 0.6248 (0.6375) | 10.84 (10.94) | 15.36 (15.71) | 0.77 / 0.80 |

  - The ML model on the tuning window: 0.6099 log loss, 9.76 margin MAE, 14.59 total MAE (Phase 3). 2025-26 was not read.
  - The injury term changes nothing before 2021-22 (no reports, so `lost_report` and `lost_usual` are 0); the 2020-21 to 2024-25 row includes it (was 0.6281 / 10.90 without). Reproduce with `uv run python scripts/traditional_check.py <db>`.
- **Consequences:**
  - On a live day an open Traditional tab makes at most 2 scoreboard fetches a minute (each up to 2 HTTP attempts per feed, the fallback only after ESPN fails); other days make none. The live client has its own throttle, so a Refresh during a live night can briefly exceed 1 request/s (#31).
  - The live model is not evaluated (no in-game history is stored).
  - A Traditional line can disagree with the ML model's; they are separate by design.
  - `features` gains `home_lost_usual` and `away_lost_usual` (a new migration); they are not in `MODEL_FEATURES`, so `feature_hash` and the ML models are unchanged.
  - Injury reports later than `decision_ts` (late scratches) and unmatched report names (#38) are not counted. In preseason, a game decided before any ESPN snapshot gets no injury term, as in ADR-022.

## ADR-023: Preseason win probability is read off the margin model

- **Date:** 2026-10-14 · **Status:** accepted · amends ADR-022 (the win's `k_win` shift) and ADR-016 (the preseason `home_win` output is no longer the classifier's)
- **Decision:**
  - Preseason games only: `p_home_win = P(margin > 0)` under the kept `margin` rung's N(μ, σ), σ from the preseason bucket (`models/predictor.py::win_probability`, applied in `daily`). Regular season, play-in and playoffs keep the `home_win` classifier.
  - When the ESPN rest adjustment moves the margin (ADR-022), the win is read off the adjusted margin; `raw_p_home_win` is the one from the model's margin. `k_win` is retired: `rest-fit` no longer fits it and stores `0`; `use_win` now records that the win moves with the margin (`= use_margin`); columns kept, no migration. Its `home_win` gate row only reports what following the margin does; the win has no gate of its own, so the win and the margin always agree. The rest block keeps `k.win = 0` and adds `win_from_margin`.
  - Preseason win drivers are the margin drivers (scale `points`). The API adds `driver_scale` per target, and the card labels them "home win, from margin, points".
  - `avaris preseason-win-check` writes the comparison on the tuning window only (`docs/reports/preseason-win-check-2015-16-to-2019-20.md`).
- **Why (#20):** the classifier is logistic, so `is_preseason` can only shift its intercept; it is as confident in preseason as in the regular season. The margin LightGBM learns how much less preseason features say. Walk-forward on the tuning window, one refit per season, 366 preseason games (2015-16 to 2018-19; 2019-20 is missing, #25):

  | Candidate | Log loss | Brier | ECE |
  | :-- | --: | --: | --: |
  | Classifier (status quo) | 0.6671 | 0.2376 | 0.048 |
  | Margin-derived | 0.6475 | 0.2301 | 0.042 |

  - Paired log loss difference -0.0196, 95% CI [-0.0390, -0.0001]; better in all four seasons. The regular season keeps the classifier (Phase 3 weekly walk-forward, 5,979 games: 0.6099 vs 0.6128 from the margin).
  - Rejected, on the Phase 3 weekly walk-forward predictions: per-bucket (preseason) Platt scaling of the classifier, forward-chained by season within the window, scored 0.6623 on 2016-17 to 2018-19 against 0.6437 for the raw classifier and 0.6318 from the margin. Reading the margin as integer bands with no 0 band (as the Edge tab does) scored the same as plain Φ(μ/σ) (0.64725 vs 0.64727).
  - Following the rest-adjusted margin, with the ADR-022 fit's k = 0.108: tuning window 0.6851 -> 0.6650 log loss (331 games with box scores); 2020-21 to 2024-25 0.6937 -> 0.6857 (313 games, a check only, not used to choose).
- **Consequences:**
  - Already-final preseason predictions keep the classifier's probability (ADR-018), so live 2026-27 preseason log loss mixes both rules.
  - The win and the margin on a preseason card now agree on who is favored.
  - Phase 4 reports and the drift reference still score preseason `home_win` with the classifier (#26).
  - `apply_rest` ignores the stored `k_win` and `use_win`: the win follows the margin whenever the margin is adjusted, so older fits need no rerun. A rerun of `avaris rest-fit` (server stopped) only makes the stored row read the new way.
  - New preseason rows no longer store the classifier's probability (#26 covers scoring it).

## ADR-022: Preseason predictions are rest-adjusted from ESPN's injury list

- **Date:** 2026-10-13 · **Status:** accepted, win rule amended by ADR-023 · amends ADR-004 ("predicted at full strength") and narrows ADR-002
- **Decision:**
  - Preseason games only (`season_type = 'preseason'`, both teams NBA; season openers show the list without adjusting, ADR-025). The model gets no new inputs and is not retrained; a rule after the model shifts its outputs: `margin -= k_margin * (home_lost - away_lost)`, `total -= k_total * (home_lost + away_lost)`, `logit(p_home_win) -= k_win * (home_lost - away_lost)`. σ is unchanged, so the 80% interval moves with μ.
  - `lost` is the value (`rate x minutes`, last season's rate) of the players ESPN lists out in the latest snapshot fetched in `[tip - 36 h, decision_ts]`. Out = status `Out`, or a future-tense note ("won't play", "won't suit up", "ruled out", "will rest", "will miss", "is out") posted within 36 h before tip-off whose named weekdays include the game's.
    - **Amended 2026-10-14:** more future-tense phrasings count ("isn't expected to play/face", "unlikely to suit up", "is not playing", "is doubtful", "is inactive", "will be unavailable", "won't travel"); doubtful counts as out, as on the NBA report (`REPORT_ABSENCE`). A note that rules a player out for a span ("will miss at least two weeks", "re-evaluated in two weeks", "four to six weeks" = the shorter) counts from its posting time to the end of that span, past the 36 h window and whatever weekday it names; one for the preseason or the season ("will miss the preseason", "season-ending", "won't be ready for the start of the season") counts until July 1 after the season it names (else the season it was posted in), and not at all when it names an earlier season. A note with both takes the earlier end. Negated or hedged spans ("won't miss", "isn't expected to miss", "could miss") and affirmatives ("is playing", "will play in the preseason", "should be ready for the start of the season") do not count, nor does one game ("the preseason finale/contest/matchup", "the season opener"). Recaps ("did not play", "was unavailable for") still do not count. On the 11 preseason games with a snapshot so far, this adds 5 players (Larsson, Smith, White, Williams, Claxton), +21% lost value.
  - **Source:** `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`, one request per `daily` run and only when a preseason game tips off within 36 h and has no final prediction. The list has no history; an unchanged list adds a row to `espn_injury_fetches` pointing at the stored snapshot, so reruns rewrite nothing. A failed fetch is a warning; the model prediction stands.
  - **Fit:** `avaris rest-fit` walks forward the production rungs (one refit per season) over 2015-16 to 2024-25. On 2015-16 to 2019-20, each k is fitted against who actually sat out: players in the team's preseason box scores who were on its regular-season roster last season or this one and missed the game (`preseason_player_games`, never `player_games`). Least squares without intercept for margin and total; logistic regression with `logit(pred)` as offset for the win. Each k is switched on only if it beats the raw model on 2020-21 to 2024-25 (margin MAE, total MAE, log loss). 2025-26 is never read.
  - Predictions keep the model's values in `raw_p_home_win`, `raw_margin_mu`, `raw_total_mu` and a `rest` JSON block (out list per side, lost value, k applied, `snapshot_ts`, a note when nothing was applied). The card, game page and Edge tab label adjusted values "Rest-adjusted (ESPN)" and show the raw ones.
- **Why:** user decision. NBA injury reports do not exist for preseason days (every CDN slot returns 403), and teams rest starters; on 2026-10-13 the model gave NYK 62% at TOR with Brunson, Towns and Anunoby resting.
- **Consequences:**
  - Non-preseason features, `MODEL_FEATURES`, `feature_hash` and prediction rows are byte-identical with or without this data (tested).
  - The 2020-21 to 2024-25 window decides only on/off for each k, never its value: a narrow exception to ADR-002's "frozen for 2020-21+".
  - k is fitted on actual absences but applied to ESPN's list, which misses late rest calls: live gains are smaller than the backtest.
  - No scheduler: a preseason final is adjusted only if a refresh ran between tip - 36 h and tip - 60 min; otherwise its `rest` block says "no ESPN snapshot before decision time", for good (ADR-018).
  - Scored preseason predictions are the adjusted ones; `raw_*` allows scoring the model alone. Non-NBA opponents get no adjustment (#11); the win model's preseason overconfidence is #20.
- **Fit report (2026-10-13):** 24,980 preseason player-games (2014-15 to 2024-25); 331 NBA-v-NBA preseason games with box scores in the fit window, 313 in the gate window.

  | Output | k | Gate metric | Raw | Adjusted | Enabled |
  | :-- | --: | :-- | --: | --: | :-- |
  | margin | 0.108 per Game Score point | MAE | 12.217 | 12.148 | yes |
  | total | -0.080 | MAE | 13.484 | 13.940 | no |
  | home_win | 0.025 | log loss | 0.707 | 0.721 | no |

  - Only the margin is adjusted. The win probability stays the model's: its preseason log loss (0.707) is already worse than a coin flip, and the shift made it worse (#20). The total has no usable rest signal.
  - Example: NYK at TOR on 2026-10-13, ESPN's list as if fetched before decision time: NYK lose 52.5 (Brunson 19.8, Anunoby 16.7, Towns 16.0), TOR 3.3, so the TOR margin moves from -0.7 to +4.6. That game was already final, so it stays unadjusted.

## ADR-021: The server stops itself when the app is closed, or from the app's Stop button

- **Date:** 2026-10-13 · **Status:** accepted
- **Decision:** `avaris serve` stops after `[server] idle_shutdown_min` (default 5, `0` = never; `serve --idle-min`) without any request. The open app polls `/api/health` every 60 s, also when minimized (`refetchIntervalInBackground`), so only a closed app goes quiet. A running job counts as activity and restarts the countdown. `POST /api/server/stop` (the header's power button, after an inline confirm) stops it at once; it is refused while a job runs (`409`), cross-site (`403`, the job guard) and when the app was not started by `serve` (`503`). Both set uvicorn's `should_exit`, so in-flight responses finish and the lifespan shutdown runs. The launcher's `-Stop` kills the pid in `data/serve.pid` only while it is still an `avaris serve`, since a self-stopped server leaves the file behind.
- **Why:** user decision: closing the app should not leave the server running.
- **Consequences:** a server started by hand from a terminal also stops when idle; pass `--idle-min 0` to keep it. Requests from another site (Origin or Sec-Fetch-Site) do not reset the countdown. Stopping takes the job lock for good, so no job can start between the decision and the exit (`409` "the server is stopping"). If Chrome freezes or discards a long-hidden app window, polling stops and the server may stop under it; the page then says the server is down and the user starts it again from the launcher. Raise `idle_shutdown_min` if that happens.

## ADR-020: An edge calculator compares odds the user types in with the model, in the browser only

- **Date:** 2026-10-13 · **Status:** accepted · narrows ADR-014
- **Decision:** the PWA gains an Edge tab (`/edge/?date=&game=`). The user picks a predicted game and types moneyline, spread and total odds (American or decimal). The page shows the model probability, the implied probability (vig removed proportionally when both prices are in, raw `1/odds` otherwise), edge in percentage points, EV per 100 staked and the model's fair price. Margin and total N(μ, σ) are read as integer scores in unit bands, so a whole-number line has a push probability (stake returned). A game cannot end tied, so the spread drops the margin = 0 band and rescales: -0.5, pk and +0.5 are the same bet and a pick'em never pushes. The odds format (decimal by default since 2026-10-14, or American) can be toggled without rounding what was typed. All maths runs in `web/src/lib/edge.ts`; nothing is fetched, stored or sent to the API.
- **Why:** user decision. A quick way to read the model against a price without bringing back odds ingestion.
- **Consequences:** ADR-014 still holds for the pipeline: no odds client, odds tables, market blend, staking, bet or spend tracking, and evaluation stays on proper scoring rules. The calculator is not evaluated and does not feed features or models.

## ADR-019: The PWA is a static export served by the API; drift is judged against resampled n-game means

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `web/` is a Next.js 16 static export (`output: 'export'`, `trailingSlash: true`). `avaris serve` mounts `web/out` at `/` after the API routes; unknown `/api/*` paths are JSON 404s, unknown pages get `404.html`. Detail views use query params (`/game/?id=`), so no `generateStaticParams`. Fonts are system stacks, so builds never touch the network.
  - CORS is off by default. `avaris serve --dev` allows only loopback origins (`localhost`, `127.0.0.1`, `[::1]`, any port; anchored regex), GET and POST, header `content-type`, for `next dev` on another port; any page on another loopback port can then read the API. Job posts keep the Phase 5 cross-site guard, and the host check runs before CORS.
  - Every response carries `frame-ancestors 'none'`, `X-Frame-Options: DENY` and `nosniff`, so no page can frame the app and clickjack Refresh (headers come from FastAPI; a static export cannot set them).
  - Backtest reports render with `react-markdown` + `remark-gfm` and no raw HTML; links other than http(s) and anchors are dropped. Charts load through `<img>` (served with `default-src 'none'`).
  - A hand-written service worker caches the app shell: hashed `/_next/static` assets and icons cache-first, pages network-first (one entry per path) with a cached fallback, `/api` never cached. `npm run build` stamps the build id into its cache name, so a new build replaces the old cache. It registers in production builds only.
  - **Drift:** per scope, the live mean log loss, `margin` MAE and `total` MAE over `n` scored games are flagged when worse than the `1 - 0.05/3` quantile of 2,000 means of `n` games resampled (fixed seed) from the reference backtest's per-game errors: kept model, `availability = report`, same season types. One-sided (better than the reference is not drift) with a Bonferroni split over the three metrics: about 5% false alarms per scope at one look; looking daily over a season still raises the odds of one false flag. Reference: `[server] drift_reference` (a report name), default `evaluation_2021-22_2024-25` (not the holdout); a missing or unreadable reference drops only the drift block.
  - `/api/health` reports the app clock (`now`, `today`), so the UI's dates and countdowns follow the server.
  - Playwright runs against `tests/fixtures/web_server.py`: the app `avaris serve` builds (`create_app`), on the synthetic league, with the clock frozen at 2021-11-27 17:00 UTC and `daily` forced offline. Deviation from "E2E against `avaris serve`": the fixture league's games are in 2021.
- **Why:** one local process and no Node runtime; the browser can only reach the API from the app's own origin. A report's bootstrap CI describes a mean over ~5,000 games and would flag almost any 30-game live sample; resampling at the live `n` asks the right question.
- **Consequences:** `npm run build` must run before `serve` shows the app (the API works without it). E2E does not cover the real clock or network refresh. The drift range ignores era shifts between the reference seasons and now.

## ADR-018: Live predictions are provisional until tip-off - 60 min, final once, and never from a model that saw the game

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `avaris daily` runs refresh → features → predict with the current production models → retrain when stale → predict again → score. It predicts this season's games dated on or before today (ET) that have no final prediction.
  - A prediction is final once `now >= tip_off - 60 min`, from the injury reports stored at that moment, and provisional before. `predictions` keeps one row per game: a provisional row is replaced only when a value changed, a final row is never replaced.
  - A game is predicted only if every target's run has `through <= game_date_et` (the model never trained on it). Missed games are therefore finalized before a retrain, which cuts off at today.
  - Retrain when a target has no production model, or its newest run (production or held candidate) has `through` `retrain_every_days` or more before today. A held candidate is a warning on every run until it is promoted or fixed; predictions keep using production.
  - A failed source refresh (network, a blocked or malformed response) is a warning; `daily` continues on stored data.
  - `avaris serve` owns the one read-write DuckDB connection; requests and jobs use cursors. Jobs run one at a time in a background thread (`409` when busy) and are recorded in `jobs`; jobs left running by a stopped server are marked failed at startup. CLI `daily`, `score` and `train` post a job when the database is locked.
  - Model artifacts are pickles: `model_sha256` in `meta.json` is verified before `joblib.load` (#6); an unhashed artifact is refused until a manual promote seals it. It catches corrupt, partial or swapped files; it is not tamper-proof, since anything that can write `model.joblib` can rewrite `meta.json`.
  - The API binds to 127.0.0.1 with no authentication (single user). It accepts only loopback `Host` headers (DNS rebinding) and refuses job posts a browser sends from another site (`Origin` or `Sec-Fetch-Site`).
- **Why:** a final prediction must be reproducible and honest: frozen at the decision time, from a model that had not seen the result. One current row per game keeps reruns idempotent. DuckDB allows one writer process.
- **Consequences:** an injury report for the decision slot that lands after a game was finalized is ignored for that game (the stored `report_ts` shows what was used). Games of finished seasons are never predicted live; the backtest covers them. A long job holds the lock; the UI shows its status.

## ADR-017: Evaluation against Elo and two naive baselines with paired bootstrap CIs; holdout scored once by the CLI

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `avaris evaluate` runs the weekly walk-forward of each target's kept rung, the Elo rung, `naive_home` (mean of the target over the last 1,230 training games) and `naive_net` (one-feature logistic or least-squares fit on the season-to-date net rating difference; `total` on the season-to-date expected total). Season-to-date ratings are stored in `features` (migration 6) but are not model features, so the feature hash is unchanged.
  - Every metric gets a 95% percentile bootstrap CI over games (1,000 replicates). One draw of game indices per replicate is shared by all models, so the difference to Elo is a paired CI. "Does not beat Elo" means worse, or better with a paired CI that includes 0.
  - `--availability report` uses the decision-report availability for the test block only; training, OOF calibration and σ stay on who actually played, as in production.
  - Drivers are contributions on the link scale (log-odds for `home_win`): LightGBM `pred_contrib`, `coef × scaled value` for linear rungs with missing-value indicators folded into their feature. Every evaluation prediction checks `base + contributions = raw model output`.
  - The holdout is scored only by `avaris evaluate --holdout`: both availability modes, a finished season, and a marker in `docs/reports/holdout_used.json` (tracked in git) written before scoring. `backtest`, `tune` and plain `evaluate` refuse any window reaching the holdout season.
- **Why:** the plan's bar is Elo plus two naive baselines with confidence intervals; a paired CI makes "beats Elo" a statement rather than an impression. A guard in code keeps ADR-002's "used once" from depending on discipline.
- **Consequences:** ECE's bootstrap interval is biased upward and can sit above the point estimate. `naive_home`'s near-zero ECE is the trivial calibration of a constant predictor. Deleting the marker and the holdout report reopens the holdout; don't.

## ADR-016: Kept rung and calibration per target chosen on the tuning window

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** each target's rung and, for `home_win`, its calibration (`isotonic` or `none`) are chosen by the weekly walk-forward on 2015-16 to 2019-20 (regular-season log loss or MAE) and frozen in `config.toml` with the Optuna hyperparameters. Isotonic calibration is off for `home_win`.
- **Why:** isotonic regression fitted on 3 seasons of out-of-fold predictions raised walk-forward log loss by 0.003 (logistic) to 0.008 (LightGBM); logistic regression is already well calibrated. The plan said isotonic for every classifier; this keeps it as an option instead.
- **Consequences:** rung comparisons for `home_win` are raw against raw Elo. Phase 4 still checks calibration with reliability diagrams and ECE; isotonic can be turned back on per target.

## ADR-015: Point-in-time features from one event loop; availability in two modes

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - A game's result counts as known at tip-off + 3 h. `features/build.py` runs one chronological loop: result events update Elo, team form, league averages, schedule history and player rates; decision events (`decision_ts`) snapshot them. Results at the same instant apply first. The same loop fills `team_ratings`.
  - `decision_ts` uses only reports in `[tip - 12 h, tip - 60 min]` (`REPORT_WINDOW`, shared with the injury check). Reports also list later days, so entries are matched by game date.
  - Preseason games get decision events only: they never feed Elo, form, availability or rest and travel history, and are predicted at full strength (availability missing).
  - Availability is stored twice: `lost_actual_*` (set players who did not play, post-hoc by design) and `lost_report_*` (players listed Out or Doubtful count 1, Questionable 0.5, on the decision report's entries for the game's own date; 0 when there is no report). The model sees neutral `home_lost`/`away_lost`, filled by an availability mode: `actual` for training and walk-forward, `report` for live and the Phase 4 re-run.
  - A team's player set is the players whose latest appearance this season was for it, minus 10+ straight misses, plus every player listed for the team on the decision report (rated at last season's rate if he has not played this season). Availability is missing before a team's first game of the season. Rosters are not used: finished-season rosters are end-of-season snapshots.
  - Travel and time-zone shift are 0 after a gap of more than 7 days (bubble, openers); unknown venues give null. `home_court` is 0 at neutral sites; 2020-21 gets a `no_fans` flag and half the Elo home advantage. Elo skips the Cup final.
  - Feature hash = `FEATURE_VERSION` + model feature list; artifacts with another hash are refused.
- **Why:** one loop makes as-of semantics hold by construction and keeps features, ratings and availability consistent; the leakage test checks it at timestamp granularity.
- **Consequences:** changing feature semantics requires bumping `FEATURE_VERSION`, retuning and a manual promote. From 2021-22 listed long-term absentees stay in the set, so `lost_*` runs higher than in earlier seasons.
- **Era shift, measured in Phase 4 (issue #7):** mean `lost_actual` per regular-season team-game is 11-18 for 2012-13 to 2019-20, 22 in 2020-21 and 31-36 from 2021-22 (`full_strength` rises from 84-102 to 120-125). `lost_report` captures 82-85% of `lost_actual`. The availability rule is not changed: picking a rule from 2021-25 results would tune on scored seasons, and any change needs a feature version bump and a retune. Reopen only with a rule chosen without the scored seasons.

## ADR-014: Avaris is an analytics model; The Odds API is dropped

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** Avaris predicts every game's home win probability, margin and total (N(μ, σ), 80% interval) and shows drivers, team ratings and injury impact. No odds, market blend, bets, staking or spend tracking. The odds client, `CreditGuard`, slot planner, backfill and de-vig code are deleted; migration 4 drops `odds_events`, `odds_snapshots` and `api_usage`. No scheduler: `avaris daily` is idempotent and runs on `serve` startup and from the UI Refresh button. `settle` becomes `score`.
- **Why:** user decision. The historical odds backfill was paid-only and the goal is now accurate, calibrated predictions, not beating the market.
- **Consequences:** evaluation uses log loss, Brier, MAE, RMSE, calibration and interval coverage against Elo and two naive baselines, not CLV. Nothing shows absolute quality against the market; a free historical-lines benchmark is a follow-up. Supersedes ADR-005, 006, 008, 011 and 013.

## ADR-013: Odds stored per game and snapshot in decimal; the API key never leaves the request

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** request `oddsFormat=decimal`. `odds_snapshots` holds every pregame outcome of the day's matched games per fetched snapshot, keyed by game, snapshot time, book, market and side, with `kind` = close (actual snapshot in [tip − 45, tip)), else decision, else open, else other. Events match games by both teams (either way round) and `commence_time` within 2 hours; moneyline and spread sides follow the stored game's home team. The key is passed only as the `apiKey` query parameter: cache paths are built from request fields, the ledger drops it, errors are scrubbed and raised `from None`, and httpx request logging is silenced.
- **Why:** de-vig works on decimal prices; neutral-site events can list the other team as home; the key must not leak into files or logs.
- **Consequences:** the American price for display is converted in the betting layer. Test fixtures are hand-built in the documented shape until the first paid run records real responses.

## ADR-012: Injury PDFs are fetched by Avaris and parsed with `nba-injury-report`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** fetch `ak-static.cms.nba.com/referee/injury/` PDFs with a cached httpx client and parse them with `nba_injury_report.report._process_pdf` (pinned `==0.1.0`). `report_ts` comes from the PDF header. Per game day, fetch the report each game's `decision_ts` resolves to plus the 1:30 pm ET report, stepping back a slot when one is missing (403). Players match by normalized name: team-season, first initial + last name, season, then any season.
- **Why:** the package's own fetcher only knows the hourly URL format (`_05PM`, the 5:30 pm report). From 2025-12-22 reports are every 15 minutes as `_05_30PM`. Fetching every report would be about 20k requests.
- **Consequences:** a parser change upstream needs a version bump and the fixture tests. Players with no stats rows at all keep a null `player_id`.

## ADR-011: Snapshot slots are tip-time bands, shared by the backfill and live

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** `ingest/odds_slots.py` plans each game day as 1 opening snapshot (09:00 ET), 1 decision snapshot per tip-time band (matinee before 17:00 ET, early before 21:30, late) at the band's earliest `decision_ts`, and closing snapshots placed 2 min before a tip and covering tips within 35 min (45 min less the 10-minute historical snapshot gap). The backfill covers every game; live caps closing slots at `live_max_close_slots`.
- **Why:** a snapshot after a game's `decision_ts` would leak; fixed clock slots miss matinee games entirely. The backfill must make the same decisions as live.
- **Consequences:** matinee days cost one extra decision snapshot. A typical day is 1 open + 2 decision + 3-4 close snapshots, about 30-36k credits per season as planned.

## ADR-010: Neutral site = schedule flag or a venue that is not the home team's arena

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `neutral_site` is true when the schedule's `isNeutral` is set or the venue is not one of the home team's arenas in `src/avaris/data/arenas.csv`. Alternate home arenas (Spurs in Austin and the Alamodome, Bucks at Panther Arena, Raptors in Tampa 2020-21) are listed as home arenas. `neutral_venues.csv` holds coordinates for the bubble, international and Cup venues.
- **Why:** `isNeutral` is only populated from 2024-25; the 2019-20 bubble and older London, Mexico City and Paris games carry no flag.
- **Consequences:** `avaris ingest status` fails if a non-preseason game is played at a venue missing from both CSVs.

## ADR-009: Thin httpx client for stats.nba.com instead of `nba_api`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** call `scheduleleaguev2`, `leaguegamelog` and `commonteamroster` directly with httpx, a full browser header set, a ~1 req/s throttle, tenacity retries and a gzip raw cache (`data/cache/final/` immutable for finished seasons, `live/` for the in-progress season, never read back).
- **Why:** stats.nba.com hangs without the full header set; httpx calls can be mocked with respx (the planned test stack), while `nba_api` uses requests; the raw cache needs the response JSON anyway.
- **Consequences:** endpoint parameters live in `ingest/endpoints.py`. Header changes on NBA's side are fixed in one place.

## ADR-008: Paper-trading gate before real stakes

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** the first 4 weeks of 2026-27 are paper bets. Real stakes start only if live CLV is positive and ROI sits inside the backtest's bootstrap interval.
- **Why:** one holdout season is thin evidence of edge.
- **Consequences:** `bets` carries a paper/real flag; Performance shows both.

## ADR-007: Jobs run in a background thread under one process-wide lock

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `POST /api/jobs/*` returns a `job_id`, runs in a background thread, one job at a time (`409` otherwise), status via `GET /api/jobs/{job_id}`, rows in a `jobs` table.
- **Why:** DuckDB has one writer; `train` is long-running and must not block the API.

## ADR-006: Closing lines are captured live by a scheduler inside `avaris serve`

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** APScheduler in the server process runs a morning pass (no odds call), 2 decision slots and 3 closing slots per game day. No live opening snapshot on the free tier. Guard refusal order: opening, closing, decision. A refused closing snapshot marks CLV unavailable.
- **Why:** historical odds are paid-only. After the downgrade the closing line exists only if a snapshot was taken near tip-off. 5 calls × 3 credits × 28 game days ≈ 420 of 500 free credits.
- **Consequences:** the server must run on game days. Usage page shows next and missed runs.

## ADR-005: Spread and total edges are per book at the book's line

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** no cross-book median price for spreads or totals. Each book's de-vigged price is a fair probability at its own line; model P(cover) is evaluated at that line; bet goes to the largest edge. Moneyline keeps the cross-book median. `w` is per target. `spread` is the home line, negative when home is favored.
- **Why:** books post different lines, so a median price across them is meaningless.

## ADR-004: `season_type` and `neutral_site` on `games`; preseason predicted but never a feature source

- **Date:** 2026-10-12 · **Status:** accepted (amended 2026-10-12 by ADR-014 and the preseason decision; was: betting on the regular season only, preseason dropped)
- **Decision:** preseason is stored with `season_type = preseason`. Every game is predicted and scored, preseason, play-in and playoffs included, with `season_type` as a model feature and σ fitted per bucket (preseason, regular, postseason). Headline metrics use the regular season; the other types are reported separately. Preseason results never update Elo, form or availability features, and preseason games are predicted at full strength (no injury report exists for preseason days). Neutral-site games get `home_court = 0` and venue-based travel.
- **Why:** the user wants preseason covered; preseason rotations are not representative, so they must not leak into regular-season features; playoffs have different home court and rest effects and a small sample; the 2019-20 bubble sits inside the tuning window.

## ADR-003: One `decision_ts` per game freezes injuries and features

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `decision_ts` = latest injury report at or before tip-off − 60 min, else tip-off − 60 min. Same rule in backtests and live. Leakage test runs at timestamp granularity.
- **Why:** without one instant, backtests use post-hoc availability while live picks are made before the injury report lands, and the backtest metrics are not believable. Amended by ADR-014: no odds are frozen at it.
- **Consequences:** `daily` writes a provisional prediction before `decision_ts` and a final one after it; only final predictions are scored. Timestamps are UTC; `game_date` is the ET date of tip-off.

## ADR-002: Tuning on 2015-16 to 2019-20 only, frozen for 2020-21+, 2025-26 holdout used once

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** Optuna and rung selection use walk-forward over 2015-16 to 2019-20 with one refit per season per trial. Hyperparameters and kept rung are frozen afterwards. Production model retrains weekly with frozen hyperparameters and a registry with promotion rules.
- **Why:** no tuning on scored seasons. Amended by ADR-014: the blend `w` and edge thresholds no longer exist.

## ADR-001: Stack and shape

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** personal, single-user, local-only. Python 3.12 + uv, DuckDB, scikit-learn + LightGBM, FastAPI serving a statically exported Next.js + shadcn/ui PWA. stats.nba.com for stats (ADR-009), official NBA injury reports. Amended by ADR-014: no odds source.
- **Why:** see `docs/plans/avaris-nba-analytics-model-build-plan.md`.
