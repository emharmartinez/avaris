# The API and the built PWA on the synthetic league with a frozen clock, for Playwright.
# The app is the one `avaris serve` runs; the clock is frozen at noon ET-ish on D2 (the
# league's games are in 2021), and the daily job runs offline.
#   uv run python -m tests.fixtures.web_server --web web/out --port 8765
import argparse
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import uvicorn

from avaris.api.main import create_app
from avaris.config import PathsSettings, ServerSettings, Settings
from avaris.db import connect
from avaris.pipeline.daily import run_daily
from avaris.pipeline.jobs import JobRunner, Progress, default_runners
from tests.fixtures.live import D1, D2, models_settings, scoreboard_payload, train_before_d1
from tests.fixtures.synthetic import BOS, INJURED_STAR, write_league
from tests.integration.test_daily import add_report

NOW = datetime(2021, 11, 27, 17, 0)  # D1 games final and scored, D2 provisional
UNPREDICTED = "0022100047"  # ATL @ DEN: left for the Refresh flow to predict
LIVE_GAME = "0022100048"  # BOS @ BKN: in the 3rd quarter on the fake live scoreboard
SCOREBOARD = scoreboard_payload({"game_id": LIVE_GAME, "period": 3, "clock": "PT04M12.00S",
                                 "label": "3rd Qtr", "home": 70, "away": 66})
REFERENCE = "evaluation_2021-22_2024-25"
# A report table as wide as the real ones (13 columns of values with CIs)
COLUMNS = ["model"] + [f"{m}{d}" for m in ("log_loss", "brier", "accuracy", "ece", "margin_mae",
                                           "total_mae") for d in ("", " vs Elo")]
ROW = " | ".join(["model"] + ["0.6131 (0.6071 to 0.6190)"] * (len(COLUMNS) - 1))
REPORT = f"""# Evaluation 2021-22 to 2024-25

## Run: report availability

<script>window.__injected = true</script>

| {" | ".join(COLUMNS)} |
|{"---|" * len(COLUMNS)}
| {ROW} |
"""
CHART = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
         '<rect width="120" height="60" fill="#888"/></svg>\n')


def write_reference(reports: Path) -> None:
    # A small report-mode backtest: markdown with raw HTML, one chart, per-game predictions
    out = reports / REFERENCE
    out.mkdir(parents=True)
    (out / "report.md").write_text(REPORT)
    (out / "reliability_report.svg").write_text(CHART)
    rows = [{"game_id": f"g{i}", "season": "2022-23", "season_type": "regular", "y": y,
             "pred": p, "target": t, "model": "model", "availability": "report"}
            for i in range(200)
            for t, y, p in (("home_win", i % 2, 0.55 if i % 2 else 0.45),
                            ("margin", float(i % 25 - 12), 0.0),
                            ("total", 220.0 + i % 30 - 15, 220.0))]
    pd.DataFrame(rows).to_csv(out / "predictions.csv.gz", index=False)


def build(root: Path, web: Path) -> Settings:
    db = write_league(root / "league.duckdb")
    artifacts = root / "artifacts"
    train_before_d1(db, artifacts)
    settings = Settings(paths=PathsSettings(db_path=db, cache_dir=root / "cache"),
                        models=models_settings(artifacts),
                        server=ServerSettings(web_dir=web, daily_on_startup=False))
    con = connect(db)
    try:
        add_report(con, NOW - timedelta(hours=1), D2, INJURED_STAR, BOS)
        con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                    "where game_date_et = ?", [D1])
        run_daily(con, settings, now=NOW, refresh=None)
        con.execute("delete from predictions where game_id = ?", [UNPREDICTED])
        # On the scoreboard already: the Traditional tab shows it live
        con.execute("update games set status = 'in_progress' where game_id = ?", [LIVE_GAME])
    finally:
        con.close()
    write_reference(settings.models.reports_dir)
    return settings


def offline_runners(settings: Settings) -> dict[str, JobRunner]:
    runners = default_runners(settings, lambda: NOW)
    daily = runners["daily"]

    def offline_daily(cur: Any, params: dict[str, Any], progress: Progress) -> str:
        return daily(cur, {**params, "offline": True}, progress)

    return {**runners, "daily": offline_daily}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", type=Path, default=Path("web/out"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="avaris-web-e2e-") as tmp:
        settings = build(Path(tmp), args.web.resolve())
        app = create_app(settings, clock=lambda: NOW, runners=offline_runners(settings),
                         live_scoreboard=lambda _day: SCOREBOARD)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
