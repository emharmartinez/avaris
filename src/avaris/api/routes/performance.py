from typing import Annotated, Any

from fastapi import APIRouter, Query

from avaris.api.deps import AppClock, AppSettings, Cursor, rows
from avaris.api.drift import drift_scopes, reference_errors
from avaris.seasons import et_date, season_for_date

router = APIRouter(prefix="/api/performance", tags=["performance"])

SCOPES = {
    "regular": "('regular', 'cup_final')",
    "preseason": "('preseason')",
    "postseason": "('play_in', 'playoffs')",
    "all": "('preseason', 'regular', 'cup_final', 'play_in', 'playoffs')",
}
METRICS_SQL = """
select count(*) as n, avg(s.log_loss) as log_loss, avg(s.brier) as brier,
    avg(s.correct::double) as accuracy,
    avg(abs(s.margin_error)) as margin_mae, sqrt(avg(s.margin_error ^ 2)) as margin_rmse,
    avg(s.margin_in_80::double) as margin_coverage_80,
    avg(abs(s.total_error)) as total_mae, sqrt(avg(s.total_error ^ 2)) as total_rmse,
    avg(s.total_in_80::double) as total_coverage_80
from prediction_scores s join games g using (game_id)
where g.season = ? and g.season_type in {types}
"""


@router.get("")
def performance(
    cur: Cursor, clock: AppClock, settings: AppSettings,
    season: Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}$")] = None,
) -> dict[str, Any]:
    # Live scores of final predictions, season to date; headline scope is the regular season
    season = season or season_for_date(et_date(clock()))
    scopes = {name: rows(cur, METRICS_SQL.format(types=types), [season])[0]
              for name, types in SCOPES.items()}
    seasons = [r["season"] for r in rows(cur, """
        select distinct g.season from prediction_scores s join games g using (game_id)
        order by 1 desc
    """)]
    # Drift: live metrics against the reference backtest's range for the same number of games
    name = settings.server.drift_reference
    ref = reference_errors(settings.models.reports_dir / name / "predictions.csv.gz")
    drift = {"reference": name, "scopes": drift_scopes(ref, scopes)} if ref else None
    return {"season": season, "scopes": scopes, "seasons": seasons, "drift": drift}
