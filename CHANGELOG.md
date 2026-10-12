# Changelog

## Unreleased

### Changed
- **Plan:** added production training to `docs/plans/plan-for-this-first-snug-fox.md`
  - `avaris train --through DATE`, artifact `meta.json`, and `registry.json` with promotion rules and a feature-hash check
  - Weekly retrain triggered by `avaris daily`, plus `POST /api/jobs/train`
  - Tuning and rung selection on 2015-16 to 2019-20 only; hyperparameters frozen for 2020-21+
  - Walk-forward fitting of blend `w` and edge thresholds, with 2020-21 as a warm-up season
  - Final refit through 2025-26 after the holdout run, as the first production model
