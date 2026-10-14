# Preseason win probability check (#20, ADR-023): the home_win classifier against
# P(margin > 0) under the margin model's N(mu, sigma), on the same preseason games
import numpy as np
import pandas as pd

from avaris.backtest.bootstrap import N_BOOT, bootstrap
from avaris.backtest.charts import reliability_svg
from avaris.backtest.metrics import log_loss, reliability
from avaris.backtest.report import markdown_table
from avaris.models.distributions import prob_above

REFERENCE = "classifier"
CHART = "reliability_preseason_home_win.svg"
RELIABILITY_BINS = 5  # a few hundred games per window: 10 bins would be mostly noise


def candidates(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    # One frame per candidate (game_id, y, pred, sigma), in game order as bootstrap needs.
    # frame: game_id, season, home_win_y, home_win_classifier, margin_pred, margin_sigma
    f = frame.sort_values("game_id").reset_index(drop=True)
    base = pd.DataFrame({"game_id": f["game_id"], "y": f["home_win_y"].astype(float)})
    from_margin = prob_above(f["margin_pred"].to_numpy(float), f["margin_sigma"].to_numpy(float),
                             0.0)
    return {
        "classifier": base.assign(pred=f["home_win_classifier"].astype(float), sigma=np.nan),
        "margin": base.assign(pred=from_margin, sigma=np.nan),
    }


def win_check_table(frame: pd.DataFrame, n_boot: int = N_BOOT, seed: int = 0) -> pd.DataFrame:
    # Log loss, Brier, accuracy and ECE with bootstrap CIs; diff is margin - classifier
    return bootstrap("home_win", candidates(frame), REFERENCE, n_boot, seed)


def _by_season(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for season, part in frame.groupby("season"):
        row: dict[str, object] = {"season": season, "games": len(part)}
        for name, c in candidates(part).items():
            row[name] = log_loss(c["y"].to_numpy(), c["pred"].to_numpy())
        rows.append(row)
    return pd.DataFrame(rows)


def render_win_check(
    frame: pd.DataFrame, title: str, n_boot: int = N_BOOT, seed: int = 0
) -> tuple[str, dict[str, str]]:
    # Markdown report and its reliability chart
    table = win_check_table(frame, n_boot, seed)
    table = table.assign(
        value=table["value"].round(4),
        ci=[f"[{lo:.4f}, {hi:.4f}]" for lo, hi in zip(table["lo"], table["hi"], strict=True)],
        diff=["ref" if pd.isna(d) else f"{d:.4f} [{lo:.4f}, {hi:.4f}]"
              for d, lo, hi in zip(table["diff"], table["diff_lo"], table["diff_hi"],
                                   strict=True)],
    )[["metric", "model", "value", "ci", "diff"]]
    seasons = sorted(frame["season"].unique())
    curves = {
        name: reliability(c["y"].to_numpy(), c["pred"].to_numpy(), RELIABILITY_BINS)
        for name, c in candidates(frame).items()
    }
    lines = [
        f"# {title}", "",
        f"- **Games:** {len(frame)} preseason games, {seasons[0]} to {seasons[-1]}",
        "- **classifier:** the kept `home_win` rung; **margin:** P(margin > 0) under the kept "
        "`margin` rung's N(mu, sigma), sigma from the preseason bucket",
        f"- **CIs:** 95% percentile bootstrap over games ({n_boot} replicates); `diff` is "
        "margin minus classifier, paired (negative is better, except accuracy)", "",
        "## Scores", "", markdown_table(table), "",
        "## Log loss by season", "", markdown_table(_by_season(frame).round(4)), "",
        f"## Reliability ({RELIABILITY_BINS} bins)", "",
    ]
    for name, curve in curves.items():
        lines += [f"**{name}**", "", markdown_table(curve.round(3)), ""]
    lines += [f"![Reliability diagram]({CHART})", ""]
    chart = reliability_svg(curves, "Reliability, home_win, preseason")
    return "\n".join(lines), {CHART: chart}
