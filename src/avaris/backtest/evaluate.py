from typing import Any

import pandas as pd
from scipy.special import expit

from avaris.analytics.drivers import FAMILY_FEATURES
from avaris.backtest.bootstrap import METRICS, N_BOOT, bootstrap
from avaris.backtest.charts import pit_svg, reliability_svg
from avaris.backtest.metrics import pit, pit_counts, primary_metric, reliability
from avaris.backtest.report import markdown_table
from avaris.backtest.walkforward import walk_forward
from avaris.config import ModelsSettings
from avaris.features.build import AvailabilityMode
from avaris.models.ladder import TARGETS

# The kept rung ("model") against Elo and the two naive baselines (Phase 4)
MODELS = ("model", "elo", "naive_home", "naive_net")
REFERENCE = "elo"
SCOPES: dict[str, set[str]] = {
    "regular": {"regular"},
    "preseason": {"preseason"},
    "play_in": {"play_in"},
    "playoffs": {"playoffs"},
    "postseason": {"play_in", "playoffs"},
}
HIGHER_IS_BETTER = {"accuracy"}
NOT_RANKED = {"coverage_80"}  # target 0.80, not lower or higher
DRIVER_COLUMNS = [f"drv_{f}" for f in FAMILY_FEATURES]


def evaluate(
    data: pd.DataFrame,
    settings: ModelsSettings,
    seasons: list[str],
    availability: AvailabilityMode,
    progress: Any = lambda _msg: None,
) -> pd.DataFrame:
    # Weekly walk-forward of every model with the frozen config; training always uses who
    # played, the test block uses `availability`. The kept rung also records its drivers
    frames = []
    for target in TARGETS:
        cfg = settings.target(target)
        for name in MODELS:
            rung = cfg.rung if name == "model" else name
            preds = walk_forward(
                data, target, rung, cfg.params(rung), settings.seed, seasons, "weekly",
                oof_seasons=settings.oof_seasons, isotonic=cfg.calibration == "isotonic",
                availability=availability, drivers=name == "model",
            )
            frames.append(preds.assign(target=target, model=name, rung=rung,
                                       availability=availability))
            progress(f"{availability} {target} {name} ({rung}): {len(preds)} games")
    return pd.concat(frames, ignore_index=True)


def _scoped(preds: pd.DataFrame, scope: str) -> pd.DataFrame:
    return preds[preds["season_type"].isin(SCOPES[scope])]


def score_tables(preds: pd.DataFrame, n_boot: int = N_BOOT, seed: int = 0) -> pd.DataFrame:
    # Every metric with a bootstrap CI, and the paired difference to Elo, per scope
    out = []
    for target, part in preds.groupby("target", sort=False):
        for scope in SCOPES:
            scoped = _scoped(part, scope)
            if scoped.empty:
                continue
            frames = {
                str(m): g.sort_values("game_id").reset_index(drop=True)
                for m, g in scoped.groupby("model", sort=False)
            }
            table = bootstrap(str(target), frames, REFERENCE, n_boot, seed)
            out.append(table.assign(target=target, scope=scope,
                                    n=len(frames[REFERENCE])))
    return pd.concat(out, ignore_index=True)


def not_beating_elo(table: pd.DataFrame) -> pd.DataFrame:
    # The kept model's metrics that are worse than Elo, or better but with a paired CI that
    # includes no difference
    rows = []
    for r in table[(table["model"] == "model") & ~table["metric"].isin(NOT_RANKED)].to_dict(
        "records"
    ):
        sign = -1 if r["metric"] in HIGHER_IS_BETTER else 1
        diff, lo, hi = sign * r["diff"], sign * r["diff_lo"], sign * r["diff_hi"]
        if diff > 0:
            verdict = "worse"
        elif max(lo, hi) >= 0:
            verdict = "not significantly better"
        else:
            continue
        rows.append({
            "target": r["target"], "scope": r["scope"], "metric": r["metric"],
            "model": r["value"], "elo": r["value"] - r["diff"], "diff": r["diff"],
            "diff_lo": r["diff_lo"], "diff_hi": r["diff_hi"], "verdict": verdict,
        })
    out = pd.DataFrame(rows, columns=["target", "scope", "metric", "model", "elo", "diff",
                                      "diff_lo", "diff_hi", "verdict"])
    order = out["verdict"].map({"worse": 0, "not significantly better": 1})
    return out.assign(_o=order).sort_values("_o", kind="stable").drop(columns="_o")


def driver_check(preds: pd.DataFrame) -> pd.DataFrame:
    # Per target: the largest |base + contributions - raw output| and |link(raw) - pred|
    rows = []
    for target, part in preds[preds["model"] == "model"].groupby("target", sort=False):
        gap = part["base"] + part[DRIVER_COLUMNS].sum(axis=1) - part["raw"]
        output = expit(part["raw"]) if target == "home_win" else part["raw"]
        rows.append({
            "target": target, "n": len(part), "max_gap": float(gap.abs().max()),
            "max_pred_gap": float((output - part["pred"]).abs().max()),
        })
    return pd.DataFrame(rows)


def availability_by_season(data: pd.DataFrame) -> pd.DataFrame:
    # Mean strength lost per regular-season team-game, by who played and by the decision
    # report (issue #7: listed long-term absentees stay in the set from 2021-22)
    regular = data[data["season_type"] == "regular"]
    sides = [
        regular[["season", f"{s}_full_strength", f"{s}_lost_actual", f"{s}_lost_report"]]
        .set_axis(["season", "full_strength", "lost_actual", "lost_report"], axis=1)
        for s in ("home", "away")
    ]
    long = pd.concat(sides).dropna(subset=["lost_actual"])
    out = long.groupby("season").agg(
        team_games=("lost_actual", "size"), full_strength=("full_strength", "mean"),
        lost_actual=("lost_actual", "mean"), lost_report=("lost_report", "mean"),
    ).reset_index()
    return out.assign(report_share=out["lost_report"] / out["lost_actual"])


def _fmt(v: float) -> str:
    return "" if pd.isna(v) else f"{v:.4f}" if abs(v) < 10 else f"{v:.2f}"


def _ci(v: float, lo: float, hi: float) -> str:
    return "" if pd.isna(v) else f"{_fmt(v)} [{_fmt(lo)}, {_fmt(hi)}]"


def _wide(table: pd.DataFrame) -> pd.DataFrame:
    # One row per model: each metric with its CI and its paired difference to Elo
    rows = []
    for model, part in table.groupby("model", sort=False):
        row: dict[str, Any] = {"model": model}
        for r in part.to_dict("records"):
            row[str(r["metric"])] = _ci(r["value"], r["lo"], r["hi"])
            row[f"{r['metric']} vs Elo"] = _ci(r["diff"], r["diff_lo"], r["diff_hi"]) or "ref"
        rows.append(row)
    return pd.DataFrame(rows)


def _season_table(preds: pd.DataFrame, target: str) -> pd.DataFrame:
    metric = primary_metric(target)
    fn = METRICS[target][metric]
    regular = preds[(preds["target"] == target) & (preds["season_type"] == "regular")]
    rows = []
    for season, part in regular.groupby("season"):
        row: dict[str, Any] = {"season": season}
        for model, g in part.groupby("model", sort=False):
            row[str(model)] = fn(g["y"].to_numpy(), g["pred"].to_numpy(),
                                 g["sigma"].to_numpy(dtype=float))
        row["games"] = len(part) // part["model"].nunique()
        rows.append(row)
    return pd.DataFrame(rows)


def _driver_summary(preds: pd.DataFrame) -> pd.DataFrame:
    # Mean absolute contribution per family on regular-season games (link scale)
    model = preds[(preds["model"] == "model") & (preds["season_type"] == "regular")]
    rows = []
    for target, part in model.groupby("target", sort=False):
        row: dict[str, Any] = {"target": target, "rung": part["rung"].iloc[0]}
        for col in DRIVER_COLUMNS:
            row[col.removeprefix("drv_")] = float(part[col].abs().mean())
        rows.append(row)
    return pd.DataFrame(rows)


def render_report(
    runs: dict[str, pd.DataFrame],
    title: str,
    data: pd.DataFrame | None = None,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> tuple[str, dict[str, str]]:
    # Markdown report and its SVG charts for one or more availability runs
    lines = [f"# {title}", ""]
    charts: dict[str, str] = {}
    for label, preds in runs.items():
        seasons = sorted(preds["season"].unique())
        table = score_tables(preds, n_boot, seed)
        lines += [
            f"## Run: {label} availability", "",
            f"- **Seasons:** {seasons[0]} to {seasons[-1]}; weekly refits, frozen config",
            f"- **Availability at test time:** `{label}`; training, calibration and sigma use"
            " who actually played",
            f"- **CIs:** 95% percentile bootstrap over games ({n_boot} replicates); "
            "`vs Elo` is the paired difference (negative is better, except accuracy). ECE is "
            "biased upward under resampling, so its interval can sit above the estimate",
            "",
            "### Where the model does not beat Elo", "",
        ]
        worse = not_beating_elo(table)
        lines += [markdown_table(worse.round(4)) if not worse.empty
                  else "- Nowhere: every metric beats Elo with a CI excluding zero", ""]
        for target in TARGETS:
            part = table[table["target"] == target]
            lines += [f"## {target} ({label} availability)", ""]
            for scope in SCOPES:
                scoped = part[part["scope"] == scope]
                if scoped.empty:
                    continue
                lines += [f"**{scope}** ({int(scoped['n'].iloc[0])} games)", "",
                          markdown_table(_wide(scoped)), ""]
            lines += [f"**{primary_metric(target)} by season (regular season)**", "",
                      markdown_table(_season_table(preds, target).round(4)), ""]
        lines += [f"### Calibration ({label} availability)", ""]
        name = f"reliability_{label}.svg"
        home = preds[(preds["target"] == "home_win") & (preds["season_type"] == "regular")]
        series = {
            str(m): reliability(g["y"].to_numpy(), g["pred"].to_numpy())
            for m, g in home.groupby("model", sort=False) if m != "naive_home"
        }
        charts[name] = reliability_svg(series, f"Reliability, home_win, regular ({label})")
        lines += [f"![Reliability diagram]({name})", ""]
        for target in ("margin", "total"):
            g = preds[(preds["target"] == target) & (preds["model"] == "model")
                      & (preds["season_type"] == "regular")]
            values = pit(g["y"].to_numpy(), g["pred"].to_numpy(), g["sigma"].to_numpy(float))
            name = f"pit_{target}_{label}.svg"
            charts[name] = pit_svg(pit_counts(values), f"PIT, {target}, regular ({label})")
            lines += [f"![PIT histogram, {target}]({name})", ""]
        lines += [f"### Drivers ({label} availability)", "",
                  "- Mean absolute contribution per family, regular season (log-odds for "
                  "`home_win`, points otherwise)", "",
                  markdown_table(_driver_summary(preds).round(3)), "",
                  "- Check: base + contributions = raw output for every prediction", "",
                  markdown_table(driver_check(preds)), ""]
    if data is not None:
        lines += ["## Availability era shift (issue #7)", "",
                  markdown_table(availability_by_season(data).round(3)), ""]
    return "\n".join(lines), charts
