import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from scipy.stats import norm

from avaris.db import connect
from avaris.preseason.rest import DISABLED, RestParams, apply_rest, load_params

FITTED = datetime(2026, 10, 13, 20, 0)
PARAMS = RestParams(k_margin=0.5, k_total=0.4, k_win=0.05, use_margin=True, use_total=True,
                    use_win=True, fitted_at=FITTED)
SNAPSHOT = datetime(2026, 10, 13, 18, 0)
SIGMA = 15.0
P_RAW = float(norm.cdf(-2.0 / SIGMA))
BRUNSON = {"name": "Jalen Brunson", "player_id": 1628973, "status": "Day-To-Day",
           "comment": "won't suit up", "value": 12.0, "matched": True}


def model_row(season_type: str = "preseason") -> dict[str, object]:
    # A preseason p_home_win is P(margin > 0) under N(margin_mu, margin_sigma) (ADR-023)
    return {"season_type": season_type, "p_home_win": P_RAW, "margin_mu": -2.0,
            "margin_sigma": SIGMA, "total_mu": 220.0}


def rest(home: float, away: float, snapshot: datetime | None = SNAPSHOT) -> dict[str, object]:
    unknown = snapshot is None
    return {
        "snapshot_ts": pd.NaT if unknown else snapshot,
        "home_lost_espn": math.nan if unknown else home,
        "away_lost_espn": math.nan if unknown else away,
        "home_players": [], "away_players": [] if unknown or not away else [BRUNSON],
    }


def test_non_preseason_rows_pass_through() -> None:
    out = apply_rest(model_row("regular"), rest(0, 12), PARAMS)
    expected = {k: v for k, v in model_row("regular").items() if k != "margin_sigma"}
    assert out == {**expected, "raw_p_home_win": None, "raw_margin_mu": None,
                   "raw_total_mu": None, "rest": None}


def test_a_preseason_game_without_a_rest_row_passes_through() -> None:
    out = apply_rest(model_row(), None, PARAMS)
    assert out["rest"] is None and out["margin_mu"] == -2.0 and out["raw_margin_mu"] is None


def test_adjustment_maths() -> None:
    out = apply_rest(model_row(), rest(home=0.0, away=12.0), PARAMS)
    # The away team lost 12: the home side gains
    assert out["margin_mu"] == pytest.approx(-2.0 + 0.5 * 12)
    assert out["total_mu"] == pytest.approx(220.0 - 0.4 * 12)
    # The win follows the adjusted margin; k_win is retired (ADR-023)
    assert out["p_home_win"] == pytest.approx(norm.cdf((-2.0 + 0.5 * 12) / SIGMA))
    assert (out["raw_p_home_win"], out["raw_margin_mu"], out["raw_total_mu"]) == (
        P_RAW, -2.0, 220.0)
    block = out["rest"]
    assert isinstance(block, dict)
    assert block["adjusted"] is True
    assert block["snapshot_ts"] == "2026-10-13T18:00:00Z"
    assert block["note"] is None
    assert block["k"] == {"margin": 0.5, "total": 0.4, "win": 0.0}
    assert block["win_from_margin"] is True
    assert block["home"] == {"lost": 0.0, "players": []}
    assert block["away"] == {"lost": 12.0, "players": [BRUNSON]}


def test_a_disabled_k_leaves_its_output_raw() -> None:
    params = RestParams(0.5, 0.4, 0.05, use_margin=False, use_total=True, use_win=True,
                        fitted_at=FITTED)
    out = apply_rest(model_row(), rest(0.0, 12.0), params)
    assert out["total_mu"] == pytest.approx(220.0 - 0.4 * 12)
    # No margin shift, so the win does not move either; use_win alone does nothing
    assert out["margin_mu"] == -2.0 and out["p_home_win"] == pytest.approx(P_RAW)
    block = out["rest"]
    assert isinstance(block, dict)
    assert block["k"] == {"margin": 0.0, "total": 0.4, "win": 0.0}
    assert block["win_from_margin"] is False


def test_without_fitted_params_the_list_is_shown_unadjusted() -> None:
    out = apply_rest(model_row(), rest(0.0, 12.0), DISABLED)
    assert (out["p_home_win"], out["margin_mu"], out["total_mu"]) == (P_RAW, -2.0, 220.0)
    assert out["raw_margin_mu"] == -2.0
    block = out["rest"]
    assert isinstance(block, dict)
    assert block["adjusted"] is False and block["away"]["players"] == [BRUNSON]
    assert "rest-fit" in block["note"]


def test_without_a_snapshot_nothing_moves_and_the_block_says_so() -> None:
    out = apply_rest(model_row(), rest(0, 0, snapshot=None), PARAMS)
    assert (out["p_home_win"], out["margin_mu"], out["total_mu"]) == (P_RAW, -2.0, 220.0)
    block = out["rest"]
    assert isinstance(block, dict)
    assert block["adjusted"] is False and block["snapshot_ts"] is None
    assert block["home"] == {"lost": None, "players": []}
    assert block["note"] == "no ESPN snapshot before decision time"


def test_load_params_reads_the_latest_fit(tmp_path: Path) -> None:
    con = connect(tmp_path / "a.duckdb")
    assert load_params(con) == DISABLED
    con.execute("insert into rest_params values (?, 0.1, 0.2, 0.3, true, false, true, '{}')",
                [datetime(2026, 10, 1)])
    con.execute("insert into rest_params values (?, 0.5, 0.4, 0.05, true, true, true, '{}')",
                [FITTED])
    assert load_params(con) == PARAMS
