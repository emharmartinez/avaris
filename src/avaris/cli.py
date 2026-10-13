import json
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import duckdb
import httpx
import pandas as pd
import typer

from avaris.config import DEFAULT_CONFIG_PATH, ModelsSettings, Settings, load_settings
from avaris.db import connect
from avaris.features.build import build_features, feature_hash, write_features
from avaris.ingest.injuries import ingest_injuries
from avaris.ingest.runner import ingest_stats
from avaris.ingest.status import check_injuries, check_report, injury_report, season_report
from avaris.models.dataset import with_targets
from avaris.models.ladder import TARGETS
from avaris.models.registry import Registry
from avaris.pipeline.daily import make_injury_client, make_stats_client
from avaris.seasons import (
    season_for_date,
    season_label,
    season_range,
    season_start_year,
    today_et,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Avaris: personal NBA analytics model.",
    pretty_exceptions_show_locals=False,
)
db_app = typer.Typer(no_args_is_help=True, help="DuckDB maintenance.")
ingest_app = typer.Typer(no_args_is_help=True, help="Data ingest.")
features_app = typer.Typer(no_args_is_help=True, help="Point-in-time features.")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(features_app, name="features")

SEASON_RE = re.compile(r"\d{4}-\d{2}")
POLL_S = 1.0  # job status polling while the server runs a CLI job


def _open_read_only(settings: Settings) -> duckdb.DuckDBPyConnection:
    if not settings.paths.db_path.exists():
        typer.echo(f"No database at {settings.paths.db_path}; run `avaris ingest stats` first")
        raise typer.Exit(1)
    try:
        return connect(settings.paths.db_path, read_only=True)
    except duckdb.IOException as exc:
        # DuckDB allows one writer; a running ingest or server holds the file
        typer.echo(f"Database is locked by another process: {exc}")
        raise typer.Exit(1) from exc


def _show(df: pd.DataFrame) -> None:
    with pd.option_context("display.max_columns", None, "display.width", 250):
        typer.echo(df.to_string(index=False))


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path, typer.Option(help="Path to config.toml.")] = DEFAULT_CONFIG_PATH,
) -> None:
    ctx.obj = load_settings(config)


@db_app.command("init")
def db_init(ctx: typer.Context) -> None:
    # Create the DuckDB file and apply all migrations
    settings: Settings = ctx.obj
    connect(settings.paths.db_path).close()
    typer.echo(f"Initialized {settings.paths.db_path}")


@ingest_app.command("stats")
def ingest_stats_command(
    ctx: typer.Context,
    from_season: Annotated[
        str | None, typer.Option("--from", help="First season, e.g. 2012-13.")
    ] = None,
    to_season: Annotated[
        str | None, typer.Option("--to", help="Last season (default: current).")
    ] = None,
    rosters: Annotated[bool, typer.Option(help="Also fetch team rosters.")] = True,
) -> None:
    # Schedule, team and player game logs, and rosters from stats.nba.com (cached, throttled)
    settings: Settings = ctx.obj
    today = today_et()
    seasons = season_range(
        from_season or settings.stats.first_season, to_season or season_for_date(today)
    )
    client = make_stats_client(settings)
    con = connect(settings.paths.db_path)
    try:
        ingest_stats(
            con,
            client,
            seasons,
            today=today,
            refetch_days=settings.stats.refetch_days,
            rosters=rosters,
            progress=typer.echo,
        )
    finally:
        client.close()
        con.close()
    typer.echo(f"Done: {client.requests_made} requests to stats.nba.com")


@ingest_app.command("injuries")
def ingest_injuries_command(
    ctx: typer.Context,
    from_season: Annotated[
        str | None, typer.Option("--from", help="First season, e.g. 2021-22.")
    ] = None,
    to_season: Annotated[
        str | None, typer.Option("--to", help="Last season (default: current).")
    ] = None,
) -> None:
    # Official NBA injury reports at each game's decision slot (cached, throttled)
    settings: Settings = ctx.obj
    cfg = settings.injuries
    seasons = season_range(
        from_season or cfg.first_season, to_season or season_for_date(today_et())
    )
    client = make_injury_client(settings)
    con = connect(settings.paths.db_path)
    try:
        summary = ingest_injuries(
            con,
            client,
            seasons,
            now_utc=datetime.now(UTC).replace(tzinfo=None),
            step_back_hours=cfg.step_back_hours,
            progress=typer.echo,
        )
    finally:
        client.close()
        con.close()
    typer.echo(
        f"Done: {summary.reports} reports, {summary.entries} entries, "
        f"{summary.unmatched_players} unmatched player rows, {client.requests_made} requests"
    )


@ingest_app.command("status")
def ingest_status_command(
    ctx: typer.Context,
    check: Annotated[bool, typer.Option(help="Exit 1 if a data check fails.")] = False,
) -> None:
    # Per-season row counts, injury report coverage and data-quality checks
    con = _open_read_only(ctx.obj)
    try:
        report = season_report(con)
        injuries = injury_report(con)
    finally:
        con.close()
    _show(report)
    _show(injuries)
    today = today_et()
    failures = [*check_report(report, today=today), *check_injuries(injuries, today=today)]
    for failure in failures:
        typer.echo(f"FAIL {failure}")
    if not failures:
        typer.echo("All checks passed")
    if check and failures:
        raise typer.Exit(1)



def _training_data(settings: Settings) -> pd.DataFrame:
    # Features as of each game's decision_ts, plus targets for final games
    con = _open_read_only(settings)
    try:
        return with_targets(build_features(con).features, con)
    finally:
        con.close()


def _targets(target: list[str] | None) -> tuple[str, ...]:
    chosen = tuple(target or TARGETS)
    unknown = set(chosen) - set(TARGETS)
    if unknown:
        raise typer.BadParameter(f"unknown target(s): {', '.join(sorted(unknown))}")
    return chosen


TargetOption = Annotated[
    list[str] | None, typer.Option("--target", help="home_win, margin or total (repeatable).")
]


def _scored_seasons(cfg: ModelsSettings, first: str, last: str) -> list[str]:
    # A walk-forward window: valid labels, never reaching the holdout (ADR-002)
    for label in (first, last):
        if not SEASON_RE.fullmatch(label) or season_label(season_start_year(label)) != label:
            typer.echo(f"invalid season label {label!r}: use the form 2024-25")
            raise typer.Exit(1)
    seasons = season_range(first, last)
    if not seasons:
        typer.echo(f"empty season window {first} to {last}")
        raise typer.Exit(1)
    if seasons[-1] >= cfg.holdout_season:
        typer.echo(f"{cfg.holdout_season} is the holdout: score it once with "
                   "`avaris evaluate --holdout`")
        raise typer.Exit(1)
    return seasons


@features_app.command("build")
def features_build(ctx: typer.Context) -> None:
    # Rebuild the features and team_ratings tables from the stored data
    settings: Settings = ctx.obj
    con = connect(settings.paths.db_path)
    try:
        fs = build_features(con)
        write_features(con, fs)
    finally:
        con.close()
    typer.echo(f"features: {len(fs.features)} games, team_ratings: {len(fs.team_ratings)} rows")


@app.command("tune")
def tune_command(
    ctx: typer.Context,
    target: TargetOption = None,
    rung: Annotated[list[str] | None, typer.Option(help="linear or lgbm (repeatable).")] = None,
    trials: Annotated[int | None, typer.Option(help="Trials per study (default: config).")] = None,
) -> None:
    # Optuna on the tuning window, one refit per season; resumable (SQLite storage)
    import optuna

    from avaris.backtest.tuning import best_params, tune

    settings: Settings = ctx.obj
    cfg = settings.models
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    data = _training_data(settings)
    seasons = _scored_seasons(cfg, cfg.tune_first_season, cfg.tune_last_season)
    out_path = cfg.reports_dir / "tuning.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    for t in _targets(target):
        for r in rung or ["linear", "lgbm"]:
            study = tune(data, t, r, seasons, n_trials=trials or cfg.n_trials,
                         n_jobs=cfg.n_jobs, seed=cfg.seed, storage=cfg.optuna_storage)
            params = best_params(study, r)
            results.setdefault(t, {})[r] = {
                "value": study.best_value, "params": params, "trials": len(study.trials),
            }
            typer.echo(f"{t} {r}: best {study.best_value:.4f} after {len(study.trials)} trials "
                       f"{json.dumps(params)}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    typer.echo(f"Wrote {out_path}; freeze the chosen params in config.toml")


@app.command("backtest")
def backtest_command(
    ctx: typer.Context,
    from_season: Annotated[str | None, typer.Option("--from", help="First test season.")] = None,
    to_season: Annotated[str | None, typer.Option("--to", help="Last test season.")] = None,
    refit: Annotated[str, typer.Option(help="season or weekly.")] = "weekly",
    target: TargetOption = None,
) -> None:
    # Walk-forward rung comparison with the frozen hyperparameters
    from avaris.backtest.report import compare_rungs, kept_rungs, to_markdown

    settings: Settings = ctx.obj
    cfg = settings.models
    if refit not in ("season", "weekly"):
        raise typer.BadParameter("refit must be season or weekly")
    first, last = from_season or cfg.tune_first_season, to_season or cfg.tune_last_season
    seasons = _scored_seasons(cfg, first, last)
    data = _training_data(settings)
    data = data[data["season"] <= seasons[-1]]
    table, preds = compare_rungs(
        data, cfg, seasons, refit, _targets(target),  # type: ignore[arg-type]
        progress=typer.echo,
    )
    kept = kept_rungs(table)
    name = f"walkforward_{first}_{last}_{refit}"
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    report = to_markdown(table, kept, f"Walk-forward {first} to {last} ({refit} refits)")
    (cfg.reports_dir / f"{name}.md").write_text(report + "\n")
    preds.to_csv(cfg.reports_dir / f"{name}_predictions.csv.gz", index=False)
    _show(table[table["scope"] == "regular"].drop(columns=["scope"]).round(4))
    typer.echo(f"Kept rungs: {json.dumps(kept)}")
    typer.echo(f"Wrote {cfg.reports_dir / name}.md")


def _holdout_seasons(
    cfg: ModelsSettings, data: pd.DataFrame, modes: list[str], from_season: str | None,
    to_season: str | None,
) -> list[str]:
    # The holdout is scored once, whole, in both availability modes (ADR-002)
    season = cfg.holdout_season
    if from_season or to_season:
        typer.echo("--holdout scores the configured holdout season; drop --from and --to")
        raise typer.Exit(1)
    if sorted(modes) != ["actual", "report"]:
        typer.echo("the holdout is scored once, in both availability modes: drop --availability")
        raise typer.Exit(1)
    out = cfg.reports_dir / f"holdout_{season}"
    if cfg.holdout_marker.exists() or out.exists():
        typer.echo(f"The {season} holdout has already been scored ({cfg.holdout_marker}, "
                   f"{out}); it is used once (ADR-002)")
        raise typer.Exit(1)
    rows = data[(data["season"] == season) & (data["season_type"] != "preseason")]
    open_games = int(rows["margin"].isna().sum())
    if rows.empty or open_games:
        typer.echo(f"{season}: {open_games} of {len(rows)} games are not final; ingest the "
                   "finished season before scoring the holdout")
        raise typer.Exit(1)
    counts = rows["season_type"].value_counts().to_dict()
    typer.echo(f"Scoring the {season} holdout once: {counts}")
    return [season]


def _write_marker(path: Path, season: str, modes: list[str], out: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "season": season, "availability": modes, "status": status,
        "at": datetime.now(UTC).isoformat(), "report": str(out),
    }, indent=2) + "\n")


@app.command("evaluate")
def evaluate_command(
    ctx: typer.Context,
    from_season: Annotated[str | None, typer.Option("--from", help="First test season.")] = None,
    to_season: Annotated[str | None, typer.Option("--to", help="Last test season.")] = None,
    availability: Annotated[
        list[str] | None, typer.Option(help="actual or report (repeatable; default actual).")
    ] = None,
    holdout: Annotated[
        bool, typer.Option("--holdout", help="Score the holdout season (once only).")
    ] = False,
    n_boot: Annotated[int, typer.Option(help="Bootstrap replicates.")] = 1000,
) -> None:
    # Weekly walk-forward of the kept rungs against Elo and the naive baselines, with
    # bootstrap CIs, calibration, drivers and charts
    from avaris.backtest.evaluate import evaluate, render_report

    settings: Settings = ctx.obj
    cfg = settings.models
    modes = availability or (["actual", "report"] if holdout else ["actual"])
    if set(modes) - {"actual", "report"}:
        raise typer.BadParameter("availability must be actual or report")
    data = _training_data(settings)
    marker = cfg.holdout_marker
    if holdout:
        seasons = _holdout_seasons(cfg, data, modes, from_season, to_season)
        name = f"holdout_{cfg.holdout_season}"
    else:
        seasons = _scored_seasons(cfg, from_season or cfg.eval_first_season,
                                  to_season or cfg.eval_last_season)
        name = f"evaluation_{seasons[0]}_{seasons[-1]}"
    if "report" in modes and seasons[0] < settings.injuries.first_season:
        first_reports = settings.injuries.first_season
        typer.echo(f"report availability: injury reports start in {first_reports}; "
                   f"pass --from {first_reports}")
        raise typer.Exit(1)
    out = cfg.reports_dir / name
    if holdout:
        # Recorded before scoring: a crash after this point still counts as a use
        _write_marker(marker, cfg.holdout_season, modes, out, "started")
    data = data[data["season"] <= seasons[-1]]
    runs = {
        m: evaluate(data, cfg, seasons, m, progress=typer.echo)  # type: ignore[arg-type]
        for m in modes
    }
    title = f"Evaluation {seasons[0]} to {seasons[-1]}" + (" (holdout)" if holdout else "")
    report, charts = render_report(runs, title, data, n_boot=n_boot, seed=cfg.seed)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report + "\n")
    for chart, svg in charts.items():
        (out / chart).write_text(svg + "\n")
    pd.concat(runs.values()).to_csv(out / "predictions.csv.gz", index=False)
    if holdout:
        _write_marker(marker, cfg.holdout_season, modes, out, "scored")
    typer.echo(f"Wrote {out / 'report.md'}")


def _run_job(settings: Settings, kind: str, params: dict[str, object]) -> None:
    # In-process on a read-write connection; when a server holds the database (one
    # writer), the job runs there instead
    from avaris.pipeline.jobs import default_runners

    try:
        con = connect(settings.paths.db_path)
    except duckdb.IOException as exc:
        _server_job(settings, kind, params, exc)
        return
    try:
        message = default_runners(settings)[kind](con, params, typer.echo)
    finally:
        con.close()
    typer.echo(message)


def _server_job(
    settings: Settings, kind: str, params: dict[str, object], locked: Exception
) -> None:
    base = f"http://{settings.server.host}:{settings.server.port}"
    try:
        response = httpx.post(f"{base}/api/jobs/{kind}", json=params or None, timeout=10)
        if response.status_code == 409:
            typer.echo(f"The server is busy: {response.json()['detail']}")
            raise typer.Exit(1)
        response.raise_for_status()
        job = response.json()
        typer.echo(f"Database held by the server at {base}: running {kind} as job "
                   f"{job['job_id']}")
        seen = 0
        while True:
            poll = httpx.get(f"{base}/api/jobs/{job['job_id']}", timeout=10)
            poll.raise_for_status()
            job = poll.json()
            for line in job["log"][seen:]:
                typer.echo(line)
            seen = len(job["log"])
            if job["status"] != "running":
                break
            time.sleep(POLL_S)
    except httpx.HTTPStatusError as exc:
        typer.echo(f"The Avaris server at {base} failed: {exc}")
        raise typer.Exit(1) from exc
    except httpx.HTTPError as exc:
        typer.echo(f"Database is locked by another process ({locked}) and no Avaris server "
                   f"answers at {base} ({exc})")
        raise typer.Exit(1) from exc
    typer.echo(job["message"] or job["status"])
    if job["status"] != "succeeded":
        raise typer.Exit(1)


@app.command("daily")
def daily_command(
    ctx: typer.Context,
    offline: Annotated[bool, typer.Option(help="Skip the stats and injury refresh.")] = False,
) -> None:
    # Refresh, retrain when stale, provisional and final predictions for today and any
    # missed game, then score; idempotent
    _run_job(ctx.obj, "daily", {"offline": True} if offline else {})


@app.command("score")
def score_command(ctx: typer.Context) -> None:
    # Per-game scores of final predictions once the games are final
    _run_job(ctx.obj, "score", {})


@app.command("serve")
def serve_command(
    ctx: typer.Context,
    daily: Annotated[bool, typer.Option(help="Run `daily` once on startup.")] = True,
    host: Annotated[str | None, typer.Option(help="Bind address (default: config).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default: config).")] = None,
    dev: Annotated[
        bool, typer.Option(help="Allow CORS from loopback origins (for `next dev`).")
    ] = False,
    idle_min: Annotated[
        float | None,
        typer.Option(min=0, help="Stop after this many minutes without a request; 0 = never "
                     "(default: config)."),
    ] = None,
) -> None:
    # The local API and the PWA; holds the one read-write DuckDB connection
    import uvicorn

    from avaris.api import main as api_main
    from avaris.api.deps import LOOPBACK_HOSTS

    settings: Settings = ctx.obj
    overrides: dict[str, Any] = {}
    if dev:
        overrides["dev_cors"] = True
    if idle_min is not None:
        overrides["idle_shutdown_min"] = idle_min
    if overrides:
        settings = settings.model_copy(
            update={"server": settings.server.model_copy(update=overrides)})
    bind = host or settings.server.host
    if bind not in LOOPBACK_HOSTS and bind != "::1":
        typer.echo(f"WARNING: binding to {bind}: the API has no authentication, and it "
                   "answers only requests addressed to 127.0.0.1 or localhost")
    if not settings.server.web_dir.is_dir():
        typer.echo(f"No PWA at {settings.server.web_dir}: run `npm run build` in web/ "
                   "(serving the API only)")
    server: uvicorn.Server | None = None

    def stop() -> None:
        # Graceful: uvicorn finishes in-flight responses, then runs the app's shutdown
        if server is not None:
            server.should_exit = True

    api = api_main.create_app(settings, daily_on_startup=settings.server.daily_on_startup and daily,
                              shutdown=stop)
    server = uvicorn.Server(uvicorn.Config(api, host=bind, port=port or settings.server.port))
    server.run()


@app.command("train")
def train_command(
    ctx: typer.Context,
    through: Annotated[
        str | None, typer.Option(help="Train on games dated before this ET date (default: today).")
    ] = None,
    target: TargetOption = None,
    promote: Annotated[
        str | None, typer.Option(help="Manually promote this run ID instead of training.")
    ] = None,
) -> None:
    # Refit the kept rungs with frozen hyperparameters; the registry decides promotion
    settings: Settings = ctx.obj
    registry = Registry(settings.models.models_dir)
    if promote:
        targets = _targets(target) if target else tuple(registry.find_targets(promote))
        for t in targets:
            registry.promote(t, promote, feature_hash())
            typer.echo(f"{t}: promoted {promote}")
        return
    params: dict[str, object] = {"target": list(_targets(target))}
    if through:
        params["through"] = date.fromisoformat(through).isoformat()
    _run_job(settings, "train", params)
