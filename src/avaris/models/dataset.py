import duckdb
import numpy as np
import pandas as pd

from avaris.features.build import AvailabilityMode, model_frame

TARGET_COLUMNS = ("home_win", "margin", "total")


def with_targets(features: pd.DataFrame, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Features plus home_win, margin and total; targets are NaN until a game is final
    results = con.execute(
        "select game_id, home_pts, away_pts from games "
        "where status = 'final' and home_pts is not null and away_pts is not null"
    ).df()
    data = features.merge(results, on="game_id", how="left")
    data["margin"] = (data["home_pts"] - data["away_pts"]).astype(float)
    data["total"] = (data["home_pts"] + data["away_pts"]).astype(float)
    data["home_win"] = np.where(data["margin"].isna(), np.nan, (data["margin"] > 0).astype(float))
    return data.drop(columns=["home_pts", "away_pts"])


def xy(
    data: pd.DataFrame, target: str, availability: AvailabilityMode = "actual"
) -> tuple[pd.DataFrame, np.ndarray]:
    rows = data[data[target].notna()]
    return model_frame(rows, availability), rows[target].to_numpy(dtype=float)
