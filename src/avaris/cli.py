import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import duckdb
import pandas as pd
import typer

from avaris.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from avaris.db import connect
from avaris.ingest.injuries import InjuryClient, ingest_injuries
from avaris.ingest.odds_api import CreditGuard, LedgerMismatch, OddsApiClient, load_api_key
from avaris.ingest.odds_backfill import estimate_plan, plan_backfill, run_backfill
from avaris.ingest.odds_status import check_odds, odds_report, reconcile_run, usage_report
from avaris.ingest.runner import ingest_stats
from avaris.ingest.stats_client import RawCache, StatsClient, Throttle
from avaris.ingest.status import check_injuries, check_report, injury_report, season_report
from avaris.seasons import season_for_date, season_range, today_et

app = typer.Typer(no_args_is_help=True, help="Avaris: personal NBA betting model.")
db_app = typer.Typer(no_args_is_help=True, help="DuckDB maintenance.")
ingest_app = typer.Typer(no_args_is_help=True, help="Data ingest.")
app.add_typer(db_app, name="db")
odds_app = typer.Typer(no_args_is_help=True, help="The Odds API, guarded by CreditGuard.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(odds_app, name="odds")


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
    client = InjuryClient(
        settings.paths.cache_dir,
        Throttle(cfg.min_interval_s),
        timeout_s=cfg.timeout_s,
        max_attempts=cfg.max_attempts,
    )
    con = connect(settings.paths.db_path)
    try:
        summary = ingest_injuries(
            con,
            client,
            seasons,
            now_utc=datetime.now(UTC).replace(tzinfo=None),
            max_step_back=cfg.max_step_back,
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


@odds_app.command("backfill")
def odds_backfill_command(
    ctx: typer.Context,
    date_from: Annotated[
        str | None, typer.Option("--from", help="First game day (ET), YYYY-MM-DD.")
    ] = None,
    date_to: Annotated[
        str | None, typer.Option("--to", help="Last game day (ET; default: yesterday).")
    ] = None,
    estimate: Annotated[bool, typer.Option(help="Only estimate credits (offline).")] = False,
    confirm: Annotated[bool, typer.Option(help="Spend credits on the backfill.")] = False,
    max_credits: Annotated[
        int | None, typer.Option(help="Per-run credit cap (required with --confirm).")
    ] = None,
    monthly_budget: Annotated[
        int | None, typer.Option(help="Monthly credit budget (required with --confirm).")
    ] = None,
    usd_per_credit: Annotated[float | None, typer.Option(help="Plan price per credit.")] = None,
    max_usd: Annotated[float | None, typer.Option(help="Monthly USD cap.")] = None,
) -> None:
    # Historical open, decision and closing snapshots per regular-season game day
    settings: Settings = ctx.obj
    cfg = settings.odds
    start = date.fromisoformat(date_from or cfg.first_date)
    end = date.fromisoformat(date_to) if date_to else today_et() - timedelta(days=1)
    if confirm and not estimate and (max_credits is None or monthly_budget is None):
        typer.echo("--confirm requires explicit --max-credits and --monthly-budget caps")
        raise typer.Exit(1)
    spend = confirm and not estimate
    limits = cfg.guard.model_copy(update={
        k: v for k, v in {
            "max_credits_per_run": max_credits, "monthly_credit_budget": monthly_budget,
            "usd_per_credit": usd_per_credit, "max_monthly_usd": max_usd,
        }.items() if v is not None
    })
    con = connect(settings.paths.db_path) if spend else _open_read_only(settings)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    guard = CreditGuard(con, limits, run_id=run_id)
    client = OddsApiClient(
        load_api_key() if spend else None, guard, settings.paths.cache_dir, sport=cfg.sport,
        regions=cfg.regions, markets=cfg.markets, timeout_s=cfg.timeout_s,
        max_attempts=cfg.max_attempts,
    )
    try:
        plan = plan_backfill(con, start, end, cfg)
        _show(estimate_plan(plan, client))
        if not spend:
            typer.echo(f"Estimate only ({start} to {end}): pass --confirm to spend credits")
            return
        client.prime()
        typer.echo(f"Run {run_id}: {guard.used} credits used this month, {guard.remaining} left")
        try:
            summary = run_backfill(con, client, plan, cfg, progress=typer.echo)
        except LedgerMismatch as exc:
            typer.echo(f"Stopped, ledger mismatch: {exc}")
            raise typer.Exit(1) from exc
        ledger, headers = reconcile_run(con, run_id)
        typer.echo(
            f"Done: {summary.calls} calls, {summary.cached} cached, {summary.rows} odds rows"
        )
        if ledger == headers:
            typer.echo(f"Ledger reconciled: {ledger} credits")
        else:
            typer.echo(f"Ledger NOT reconciled: ledger {ledger} vs headers {headers} credits")
            raise typer.Exit(1)
        if summary.refused:
            raise typer.Exit(2)
    finally:
        client.close()
        con.close()


@odds_app.command("usage")
def odds_usage_command(ctx: typer.Context) -> None:
    # Odds API credits per month from the api_usage ledger
    con = _open_read_only(ctx.obj)
    try:
        _show(usage_report(con))
    finally:
        con.close()


@odds_app.command("status")
def odds_status_command(
    ctx: typer.Context,
    check: Annotated[bool, typer.Option(help="Exit 1 if a Phase 2 odds check fails.")] = False,
) -> None:
    # Per-season odds coverage: open, decision and close snapshots, unmatched events
    con = _open_read_only(ctx.obj)
    try:
        report = odds_report(con)
    finally:
        con.close()
    _show(report)
    failures = check_odds(report, today=today_et())
    for failure in failures:
        typer.echo(f"FAIL {failure}")
    if not failures:
        typer.echo("All checks passed")
    if check and failures:
        raise typer.Exit(1)
