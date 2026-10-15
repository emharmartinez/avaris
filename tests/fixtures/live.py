# Models trained on the synthetic league before its unplayed 2021-22 rounds (D1, D2)
from datetime import date, datetime
from pathlib import Path

import duckdb

from avaris.config import ModelsSettings, TargetModelSettings
from avaris.features.build import build_features
from avaris.models.dataset import with_targets
from avaris.pipeline.train import train

D1, D2 = date(2021, 11, 26), date(2021, 11, 27)
LGBM = {"n_estimators": 20, "num_leaves": 4, "min_child_samples": 5}


def models_settings(artifacts: Path) -> ModelsSettings:
    lgbm = TargetModelSettings(rung="lgbm", lgbm=LGBM)
    return ModelsSettings(
        artifacts_dir=artifacts, oof_seasons=1, promote_tolerance=10.0,
        home_win=TargetModelSettings(rung="linear", calibration="none"), margin=lgbm,
        total=TargetModelSettings(rung="linear"),
    )


def train_before_d1(db: Path, artifacts: Path) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        data = with_targets(build_features(con).features, con)
    finally:
        con.close()
    train(data, models_settings(artifacts), through=D1, run_id="r1", now=datetime(2021, 11, 26))


def scoreboard_payload(*games: dict[str, object]) -> dict[str, object]:
    # A scoreboardv3 response; each game: game_id, status (1-3), period, clock, label, home, away
    return {"scoreboard": {"games": [{
        "gameId": g["game_id"], "gameStatus": g.get("status", 2),
        "gameStatusText": g.get("label", "2nd Qtr"), "period": g.get("period", 2),
        "gameClock": g.get("clock", "PT05M00.00S"), "regulationPeriods": 4,
        "homeTeam": {"score": g.get("home", 0)}, "awayTeam": {"score": g.get("away", 0)},
    } for g in games]}}
