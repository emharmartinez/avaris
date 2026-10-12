# Phase 4 evaluation: 2020-21 to 2024-25, injury-report re-run, 2025-26 holdout

- **Generated:** 2026-10-12 by `avaris evaluate` (feature version 2, hash `7723ef74696d81d3`), frozen config from Phase 3
- **Models:** kept rung per target (`home_win` logistic, `margin` LightGBM, `total` ridge) against the Elo rung, `naive_home` (home win rate, mean home margin, mean total over the last 1,230 games) and `naive_net` (season-to-date net rating difference, or expected total). ADR-017
- **Method:** weekly walk-forward refits; calibration and σ from out-of-fold predictions on earlier seasons; 95% percentile bootstrap CIs over games (1,000 replicates), paired against Elo
- **Full reports** (every metric, every scope, metrics per season, charts):
  1. `phase-4/evaluation_2020-21_2024-25/report.md`: actual availability
  2. `phase-4/evaluation_2021-22_2024-25/report.md`: decision injury report
  3. `phase-4/holdout_2025-26/report.md`: holdout, both modes, scored once (`holdout_used.json`); predictions in `predictions.csv.gz`

## Headline: regular season, model vs Elo

| Run | Games | `home_win` log loss (Elo) | `margin` MAE (Elo) | `total` MAE (Elo) | 80% coverage margin / total |
|---|---|---|---|---|---|
| 2020-25, actual | 6,000 | 0.6164 (0.6389) | 10.67 (10.99) | 14.63 (15.70) | 0.80 / 0.81 |
| 2021-25, report | 4,920 | 0.6131 (0.6375) | 10.79 (10.94) | 14.60 (15.71) | 0.80 / 0.81 |
| 2025-26 holdout, actual | 1,230 | 0.5803 (0.6083) | 10.98 (11.51) | 15.02 (15.96) | 0.79 / 0.79 |
| 2025-26 holdout, report | 1,230 | 0.5820 (0.6083) | 11.08 (11.51) | 15.02 (15.96) | 0.78 / 0.79 |

- In every run the model beats Elo on regular-season log loss, Brier, MAE and RMSE with a paired CI that excludes 0
- Regular-season `home_win` accuracy beats Elo in 2020-25 (CI excludes 0) but not significantly in the holdout (+0.014 to +0.018)
- Both naive baselines lose to the model everywhere in the regular season. `naive_net` beats Elo on `total` (significantly) and on holdout `home_win` (not significantly); otherwise they lose to Elo too
- `naive_home` has the lowest ECE (0.004-0.010) only because a constant predictor is trivially calibrated; ECE's bootstrap interval is biased upward
- 80% intervals cover 78-81% everywhere in the regular season; the PIT histograms are close to flat

## Where the model does not beat Elo

- **Postseason `margin` with the injury report:** 2021-25 MAE 12.50 vs Elo 11.96 (+0.54, CI [+0.02, +1.10]); the holdout points the same way (+0.99, CI includes 0). With actual availability the model beats Elo here, so the report's postseason availability is what hurts
- **Holdout postseason `home_win` accuracy:** 0.60 vs 0.68 (actual), CI excludes 0; log loss and Brier are still lower than Elo's, not significantly
- **Postseason `home_win` (2020-25 and holdout):** log loss and Brier better than Elo but not significantly (361-413 games)
- **Play-in (6-10 games a season) and preseason:** mixed, every CI includes 0
- **Calibration:** holdout regular-season ECE 0.020 vs Elo 0.065, a paired CI that just includes 0

## Cost of late scratches: injury report vs actual availability

Paired differences of the model (report minus actual), same games:

| Window | `home_win` log loss | `margin` MAE | `total` MAE |
|---|---|---|---|
| 2021-25 regular (4,920) | -0.0005 [-0.0022, +0.0012] | +0.16 [+0.11, +0.20] | +0.01 [-0.01, +0.03] |
| 2021-25 postseason (361) | +0.0048 [-0.0034, +0.0136] | +0.83 [+0.37, +1.31] | +0.16 [+0.04, +0.30] |
| 2025-26 regular (1,230) | +0.0017 [-0.0014, +0.0048] | +0.10 [+0.03, +0.17] | +0.00 [-0.04, +0.04] |
| 2025-26 postseason (91) | -0.0177 [-0.0362, +0.0015] | +1.11 [-0.12, +2.30] | +0.41 [+0.13, +0.70] |

- **Live use:** win probability loses nothing measurable; margin MAE gets about 0.1-0.16 points worse in the regular season and close to a point worse in the postseason, where late scratches and rest decisions matter most
- The report re-run is the number to expect live; the regular-season advantage over Elo holds in it

## Availability era shift (issue #7)

- Mean strength lost per regular-season team-game (`lost_actual`): 11-18 for 2012-13 to 2019-20, 22 in 2020-21, 31-36 from 2021-22, when listed long-term absentees stay in the player set
- `lost_report` captures 82-85% of `lost_actual` from 2021-22
- **Decision:** the availability rule is unchanged. Picking a rule from 2021-25 results would tune on scored seasons, and any change needs a feature version bump and a retune (ADR-015)

## Drivers

- Mean absolute contribution per family, regular season 2020-25 (log-odds for `home_win`, points otherwise):

| Target | Elo | Form | Availability | Rest/travel | League | Home court | Game type |
|---|---|---|---|---|---|---|---|
| `home_win` | 0.39 | 0.20 | 0.21 | 0.08 | 0.03 | 0.01 | 0.01 |
| `margin` | 2.72 | 1.70 | 1.59 | 0.36 | 0.11 | 0.03 | 0.01 |
| `total` | 0.33 | 19.74 | 0.97 | 0.64 | 6.25 | 0.17 | 0.62 |

- The home edge sits in the base value (intercept), so the home-court family is small except at neutral sites and in 2020-21
- Base + contributions equal the model's raw output for every evaluation prediction (max gap 1e-13, in all three runs)

## Production model

- `avaris train --through 2026-09-01`: run `20261012T224157Z-b5c3`, 19,230 games from 2012-10-05 to 2026-06-13, all three targets promoted
- OOF metrics: `home_win` log loss 0.598, `margin` MAE 10.96, `total` MAE 14.76; margin σ 13.9 regular, 15.7 postseason, 14.9 preseason
