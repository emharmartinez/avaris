from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from avaris.features.build import AvailabilityMode


def injury_impact(
    availability: pd.DataFrame, mode: AvailabilityMode, names: Mapping[int, str] | None = None
) -> pd.DataFrame:
    # Strength lost per team and game (the availability feature) and the players behind it,
    # largest loss first. actual: set players who did not play (missing before the game);
    # report: Out and Doubtful 1, Questionable 0.5 on the decision report
    a = availability.assign(value=availability["rate"] * availability["minutes"])
    if mode == "actual":
        absent = pd.to_numeric(a["absent_actual"].astype(object), errors="coerce").astype(float)
    else:
        absent = a["absent_report"].astype(float)
    a = a.assign(lost=a["value"] * absent)
    rows = []
    for (game_id, team_id), g in a.groupby(["game_id", "team_id"], sort=False):
        unknown = g["lost"].isna().any()
        hit = g[g["lost"].fillna(0) != 0].sort_values("lost", ascending=False)
        players: list[dict[str, Any]] = [{
            "player_id": int(p["player_id"]),
            "name": (names or {}).get(int(p["player_id"])),
            "status": p["report_status"],
            "value": float(p["value"]),
            "lost": float(p["lost"]),
        } for p in _records(hit)]
        full = float(g["value"].sum())
        lost = np.nan if unknown else float(g["lost"].sum())
        rows.append({
            "game_id": game_id, "team_id": team_id, "full_strength": full, "lost": lost,
            "lost_share": lost / full if full else np.nan, "players": players,
        })
    return pd.DataFrame(rows)


def player_names(con: Any) -> dict[int, str]:
    # Each player's most recent name in the game logs
    df = con.execute(
        "select player_id, arg_max(player_name, game_date_et) as name from player_games "
        "group by player_id"
    ).df()
    return {int(r["player_id"]): str(r["name"]) for r in _records(df)}


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): v for k, v in r.items()} for r in df.to_dict("records")]
