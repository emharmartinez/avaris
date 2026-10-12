import pandas as pd

from avaris.backtest.report import kept_rungs, summarize


def test_kept_rung_must_beat_the_best_rung_below() -> None:
    table = pd.DataFrame([
        ("home_win", "elo", 0.64), ("home_win", "linear", 0.63), ("home_win", "lgbm", 0.635),
        ("margin", "elo", 10.0), ("margin", "linear", 10.1), ("margin", "lgbm", 9.9),
        ("total", "elo", 15.0), ("total", "linear", 15.5), ("total", "lgbm", 15.2),
    ], columns=["target", "rung", "primary"])
    table["scope"] = "regular"
    assert kept_rungs(table) == {"home_win": "linear", "margin": "lgbm", "total": "elo"}


def test_summarize_scores_regular_season_and_other_types_separately() -> None:
    preds = pd.DataFrame({
        "season_type": ["regular", "regular", "preseason", "playoffs"],
        "season": "2019-20",
        "y": [1.0, 0.0, 1.0, 0.0],
        "pred": [0.7, 0.4, 0.5, 0.2],
        "sigma": float("nan"),
    })
    rows = summarize("home_win", "elo", preds)
    scopes = {r["scope"]: r for r in rows}
    assert set(scopes) == {"regular", "preseason", "postseason", "all"}
    assert scopes["regular"]["n"] == 2
    assert scopes["regular"]["primary"] == scopes["regular"]["log_loss"]


def test_markdown_table() -> None:
    from avaris.backtest.report import markdown_table

    out = markdown_table(pd.DataFrame({"rung": ["elo"], "mae": [10.12345]}))
    assert out.splitlines() == ["| rung | mae |", "|---|---|", "| elo | 10.1235 |"]


def test_markdown_table_prints_counts_without_decimals() -> None:
    from avaris.backtest.report import markdown_table

    assert markdown_table(pd.DataFrame({"n": [5979.0]})).splitlines()[-1] == "| 5979 |"
