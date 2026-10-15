# The Traditional model's check in ADR-024: regular-season log loss, MAE and 80% coverage
# against Elo and the league average, and on the injury-report seasons the same without the
# injury term (#29). Never reads 2025-26 (the holdout).
#   uv run python scripts/traditional_check.py data/avaris.duckdb   (server stopped, or a copy)
import math
import sys

import duckdb
import numpy as np
import pandas as pd

from avaris.api.routes.traditional import FEATURES
from avaris.backtest.metrics import Z_80
from avaris.traditional.pregame import pregame

WINDOWS = (("2015-16", "2019-20"), ("2020-21", "2024-25"))
REPORT_WINDOW = ("2021-22", "2024-25")  # injury reports exist from 2021-22
NO_INJURIES = {f"{side}_lost_{kind}": None for side in ("home", "away")
               for kind in ("report", "usual")}
COLUMNS = ", ".join(f"f.{name}" for name in FEATURES)
SQL = f"""
select g.season, g.home_pts - g.away_pts as margin, g.home_pts + g.away_pts as total,
    f.elo_prob, {COLUMNS}
from games g join (
    select * from features
    qualify row_number() over (partition by game_id order by decision_ts desc) = 1
) f on f.game_id = g.game_id
where g.status = 'final' and g.home_pts is not null and g.season_type = 'regular'
    and g.season between ? and ?
"""


def log_loss(won: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(won * np.log(p) + (1 - won) * np.log(1 - p)))


def check(games: pd.DataFrame, label: str, injuries: bool = True) -> None:
    rows = games.to_dict("records")
    found = [pregame(row if injuries else {**row, **NO_INJURIES}) for row in rows]
    lines = [line for line in found if line is not None]
    games = games[[line is not None for line in found]]
    p = np.array([line.p_home_win for line in lines])
    margin_mu = np.array([line.margin_mu for line in lines])
    total_mu = np.array([line.total_mu for line in lines])
    sigma_m, sigma_t = lines[0].margin_sigma, lines[0].total_sigma
    margin, total = games.margin.to_numpy(), games.total.to_numpy()
    won = (margin > 0).astype(float)
    cover_m = np.mean(np.abs(margin - margin_mu) <= Z_80 * sigma_m)
    cover_t = np.mean(np.abs(total - total_mu) <= Z_80 * sigma_t)
    print(f"{label}: {len(games)} games")
    print(f"  residual std  margin {math.sqrt(np.mean((margin - margin_mu) ** 2)):.2f}"
          f"  total {math.sqrt(np.mean((total - total_mu) ** 2)):.2f}")
    elo_loss = log_loss(won, games.elo_prob.to_numpy())
    print(f"  log loss      {log_loss(won, p):.4f} (Elo {elo_loss:.4f})")
    print(f"  margin MAE    {np.mean(np.abs(margin - margin_mu)):.2f}"
          f" (Elo {np.mean(np.abs(margin - games.elo_margin)):.2f})")
    print(f"  total MAE     {np.mean(np.abs(total - total_mu)):.2f}"
          f" (league {np.mean(np.abs(total - games.league_total)):.2f})")
    print(f"  80% coverage  margin {cover_m:.3f}  total {cover_t:.3f}")


def main() -> None:
    con = duckdb.connect(sys.argv[1], read_only=True)
    for first, last in WINDOWS:
        check(con.execute(SQL, [first, last]).df(), f"{first} to {last}")
    first, last = REPORT_WINDOW
    games = con.execute(SQL, [first, last]).df()
    check(games, f"{first} to {last}, injury term")
    check(games, f"{first} to {last}, no injury term", injuries=False)


if __name__ == "__main__":
    main()
