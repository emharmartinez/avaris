import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb
import pandas as pd

P_CLIP = 1e-6
NO_SNAPSHOT = "no ESPN snapshot before decision time"
NOT_FITTED = "not fitted: run `avaris rest-fit`; model values shown"
NONE_ENABLED = "no coefficient beat the raw model; model values shown"


@dataclass(frozen=True)
class RestParams:
    # margin -= k_margin * lost_diff, total -= k_total * lost_sum,
    # logit(p_home_win) -= k_win * lost_diff; a k is applied only when enabled (ADR-022)
    k_margin: float
    k_total: float
    k_win: float
    use_margin: bool
    use_total: bool
    use_win: bool
    fitted_at: datetime | None = None

    @property
    def any_enabled(self) -> bool:
        return self.use_margin or self.use_total or self.use_win


DISABLED = RestParams(0.0, 0.0, 0.0, False, False, False)


def load_params(con: duckdb.DuckDBPyConnection) -> RestParams:
    row = con.execute(
        "select k_margin, k_total, k_win, use_margin, use_total, use_win, fitted_at "
        "from rest_params order by fitted_at desc limit 1"
    ).fetchone()
    if row is None:
        return DISABLED
    *values, fitted_at = row
    return RestParams(*values, fitted_at=fitted_at)


def _logit(p: float) -> float:
    p = min(max(p, P_CLIP), 1 - P_CLIP)
    return math.log(p / (1 - p))


def _known(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def apply_rest(
    row: Mapping[str, Any], rest: Mapping[str, Any] | None, params: RestParams
) -> dict[str, Any]:
    # Preseason only: shift p_home_win, margin_mu and total_mu by the value ESPN lists out,
    # keep the model's values as raw_*, and describe it all in the rest block
    out: dict[str, Any] = {
        k: row[k] for k in ("season_type", "p_home_win", "margin_mu", "total_mu")}
    if row["season_type"] != "preseason" or rest is None:
        return {**out, "raw_p_home_win": None, "raw_margin_mu": None, "raw_total_mu": None,
                "rest": None}
    out.update(raw_p_home_win=row["p_home_win"], raw_margin_mu=row["margin_mu"],
               raw_total_mu=row["total_mu"])
    snapshot = None if pd.isna(rest["snapshot_ts"]) else pd.Timestamp(rest["snapshot_ts"])
    home, away = _known(rest["home_lost_espn"]), _known(rest["away_lost_espn"])
    k = {
        "margin": params.k_margin if params.use_margin else 0.0,
        "total": params.k_total if params.use_total else 0.0,
        "win": params.k_win if params.use_win else 0.0,
    }
    adjusted = snapshot is not None and params.any_enabled
    if adjusted and home is not None and away is not None:
        diff, total = home - away, home + away
        out["margin_mu"] = row["margin_mu"] - k["margin"] * diff
        out["total_mu"] = row["total_mu"] - k["total"] * total
        z = _logit(float(row["p_home_win"])) - k["win"] * diff
        out["p_home_win"] = 1 / (1 + math.exp(-z))
    note = (None if adjusted else NO_SNAPSHOT if snapshot is None
            else NONE_ENABLED if params.fitted_at else NOT_FITTED)
    out["rest"] = {
        "adjusted": adjusted, "note": note, "k": k,
        "snapshot_ts": None if snapshot is None else f"{snapshot.isoformat()}Z",
        "home": {"lost": home, "players": list(rest["home_players"])},
        "away": {"lost": away, "players": list(rest["away_players"])},
    }
    return out
