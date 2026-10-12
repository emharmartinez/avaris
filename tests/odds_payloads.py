# Hand-built Odds API responses in the documented v4 shape (decimal odds).
# Not recorded from the live API yet: replace with responses from the user's 1-week test.
from datetime import datetime, timedelta
from typing import Any

from avaris.ingest.odds_api import iso_z

MARKETS = ("h2h", "spreads", "totals")


def outcomes(
    market: str, home: str, away: str, spread: float, total: float, shade: float = 0.0
) -> list[dict[str, Any]]:
    if market == "h2h":
        fav, dog = (1.5 + shade, 2.7) if spread < 0 else (2.7, 1.5 + shade)
        return [{"name": home, "price": fav}, {"name": away, "price": dog}]
    if market == "spreads":
        return [
            {"name": home, "price": 1.91 + shade, "point": spread},
            {"name": away, "price": 1.91, "point": -spread},
        ]
    return [
        {"name": "Over", "price": 1.91 + shade, "point": total},
        {"name": "Under", "price": 1.91, "point": total},
    ]


def event(
    event_id: str,
    home: str,
    away: str,
    commence: datetime,
    spread: float = -4.5,
    total: float = 221.5,
    books: tuple[str, ...] = ("fanduel", "draftkings"),
    markets: tuple[str, ...] = MARKETS,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "sport_key": "basketball_nba",
        "sport_title": "NBA",
        "commence_time": iso_z(commence),
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {
                "key": book,
                "title": book.title(),
                "last_update": iso_z(commence - timedelta(hours=3)),
                "markets": [
                    {"key": m, "outcomes": outcomes(m, home, away, spread, total, 0.01 * i)}
                    for m in markets
                ],
            }
            for i, book in enumerate(books)
        ],
    }


def historical(snapshot: datetime, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "timestamp": iso_z(snapshot),
        "previous_timestamp": iso_z(snapshot - timedelta(minutes=5)),
        "next_timestamp": iso_z(snapshot + timedelta(minutes=5)),
        "data": events,
    }
