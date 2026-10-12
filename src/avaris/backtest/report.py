from typing import Any

import numpy as np
import pandas as pd

from avaris.backtest.metrics import primary_metric, score
from avaris.backtest.walkforward import Refit, walk_forward
from avaris.config import ModelsSettings
from avaris.models.distributions import BUCKETS
from avaris.models.ladder import RUNGS, TARGETS

SCOPES = ("regular", "preseason", "postseason", "all")


def summarize(target: str, rung: str, preds: pd.DataFrame) -> list[dict[str, Any]]:
    # Metrics per scope; the headline scope is the regular season
    buckets = preds["season_type"].map(BUCKETS)
    rows = []
    for scope in SCOPES:
        part = preds if scope == "all" else preds[(buckets == scope) & (
            preds["season_type"] != "cup_final"
        )]
        if part.empty:
            continue
        sigma = part["sigma"].to_numpy(dtype=float)
        result = score(
            target, part["y"].to_numpy(), part["pred"].to_numpy(),
            sigma if np.isfinite(sigma).all() else None,
        )
        rows.append({
            "target": target, "rung": rung, "scope": scope,
            "primary": result[primary_metric(target)], **result,
        })
    return rows


def compare_rungs(
    data: pd.DataFrame,
    settings: ModelsSettings,
    seasons: list[str],
    refit: Refit,
    targets: tuple[str, ...] = TARGETS,
    progress: Any = lambda _msg: None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Walk-forward every rung of every target with the frozen hyperparameters
    rows, preds = [], []
    for target in targets:
        for rung in RUNGS:
            params = settings.target(target).params(rung)
            p = walk_forward(data, target, rung, params, settings.seed, seasons, refit,
                             oof_seasons=settings.oof_seasons)
            rows.extend(summarize(target, rung, p))
            preds.append(p.assign(target=target, rung=rung))
            progress(f"{target} {rung}: done")
    return pd.DataFrame(rows), pd.concat(preds, ignore_index=True)


def kept_rungs(table: pd.DataFrame) -> dict[str, str]:
    # A rung is kept only if it beats the best rung below it on the regular season
    regular = table[table["scope"] == "regular"]
    kept: dict[str, str] = {}
    for target, part in regular.groupby("target", sort=False):
        metric = dict(zip(part["rung"], part["primary"], strict=True))
        best = "elo"
        for rung in RUNGS[1:]:
            if rung in metric and metric[rung] < metric[best]:
                best = rung
        kept[str(target)] = best
    return kept


def to_markdown(table: pd.DataFrame, kept: dict[str, str], title: str) -> str:
    lines = [f"# {title}", "", "**Kept rungs:** " + ", ".join(
        f"`{t}` = {r}" for t, r in kept.items()
    ), ""]
    for target, part in table.groupby("target", sort=False):
        lines += [f"## {target}", ""]
        cols = [c for c in part.columns if c not in ("target",) and part[c].notna().any()]
        lines.append(markdown_table(part[cols]))
        lines.append("")
    return "\n".join(lines)


def markdown_table(df: pd.DataFrame) -> str:
    def cell(v: object) -> str:
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    rows = [
        "| " + " | ".join(df.columns) + " |",
        "|" + "---|" * len(df.columns),
        *("| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False)),
    ]
    return "\n".join(rows)
