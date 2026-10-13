from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

from avaris.backtest.metrics import PROB_CLIP, Z_80, pit
from avaris.db import upsert

FINAL_PREDICTIONS_SQL = """
select p.game_id, p.p_home_win, p.margin_mu, p.margin_sigma, p.total_mu, p.total_sigma,
    (g.home_pts - g.away_pts)::double as margin, (g.home_pts + g.away_pts)::double as total,
    s.margin as scored_margin, s.total as scored_total
from predictions p
join games g using (game_id)
left join prediction_scores s using (game_id)
where p.status = 'final' and g.status = 'final'
    and g.home_pts is not null and g.away_pts is not null
"""


def score_frame(rows: pd.DataFrame, scored_at: datetime) -> pd.DataFrame:
    # Per-game scores of final predictions against the result
    p = np.clip(rows["p_home_win"].to_numpy(dtype=float), PROB_CLIP, 1 - PROB_CLIP)
    margin, total = rows["margin"].to_numpy(dtype=float), rows["total"].to_numpy(dtype=float)
    y = (margin > 0).astype(float)
    out = pd.DataFrame({
        "game_id": rows["game_id"].to_numpy(), "scored_at": scored_at,
        "home_win": y, "margin": margin, "total": total,
        "log_loss": -(y * np.log(p) + (1 - y) * np.log(1 - p)),
        "brier": (p - y) ** 2, "correct": (p > 0.5) == (y == 1),
    })
    for target, outcome in (("margin", margin), ("total", total)):
        mu = rows[f"{target}_mu"].to_numpy(dtype=float)
        sigma = rows[f"{target}_sigma"].to_numpy(dtype=float)
        out[f"{target}_error"] = outcome - mu
        out[f"{target}_in_80"] = np.abs(outcome - mu) <= Z_80 * sigma
        out[f"{target}_pit"] = pit(outcome, mu, sigma)
    return out


def score_predictions(con: duckdb.DuckDBPyConnection, now: datetime) -> int:
    # Scores every final prediction of a final game that is unscored or whose result
    # changed since (stat corrections); returns the rows written
    rows = con.execute(FINAL_PREDICTIONS_SQL).df()
    changed = (rows["scored_margin"] != rows["margin"]) | (rows["scored_total"] != rows["total"])
    todo = rows[rows["scored_margin"].isna() | changed]
    return upsert(con, "prediction_scores", score_frame(todo, now)) if len(todo) else 0
