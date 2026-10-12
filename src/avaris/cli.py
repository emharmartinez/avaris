from pathlib import Path
from typing import Annotated

import duckdb
import pandas as pd
import typer

from avaris.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from avaris.db import connect
from avaris.ingest.runner import ingest_stats
from avaris.ingest.stats_client import RawCache, StatsClient, Throttle
from avaris.ingest.status import check_report, season_report
from avaris.seasons import season_for_date, season_range, today_et

app = typer.Typer(no_args_is_help=True, help="Avaris: personal NBA betting model.")
db_app = typer.Typer(no_args_is_help=True, help="DuckDB maintenance.")
ingest_app = typer.Typer(no_args_is_help=True, help="Data ingest.")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")


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
    client = StatsClient(
        cache=RawCache(settings.paths.cache_dir),
        throttle=Throttle(settings.stats.min_interval_s),
        timeout_s=settings.stats.timeout_s,
        max_attempts=settings.stats.max_attempts,
    )
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


@ingest_app.command("status")
def ingest_status_command(
    ctx: typer.Context,
    check: Annotated[bool, typer.Option(help="Exit 1 if a Phase 1 check fails.")] = False,
) -> None:
    # Per-season row counts and data-quality checks
    settings: Settings = ctx.obj
    if not settings.paths.db_path.exists():
        typer.echo(f"No database at {settings.paths.db_path}; run `avaris ingest stats` first")
        raise typer.Exit(1)
    try:
        con = connect(settings.paths.db_path, read_only=True)
    except duckdb.IOException as exc:
        # DuckDB allows one writer; a running ingest or server holds the file
        typer.echo(f"Database is locked by another process: {exc}")
        raise typer.Exit(1) from exc
    try:
        report = season_report(con)
    finally:
        con.close()
    with pd.option_context("display.max_columns", None, "display.width", 250):
        typer.echo(report.to_string(index=False))
    failures = check_report(report, today=today_et())
    for failure in failures:
        typer.echo(f"FAIL {failure}")
    if not failures:
        typer.echo("All checks passed")
    if check and failures:
        raise typer.Exit(1)
