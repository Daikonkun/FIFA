from __future__ import annotations

import json
from pathlib import Path

from scripts.update_ratings import build_ratings


def test_build_ratings_uses_aliases_and_hosts() -> None:
    fixture_teams = ["USA", "Congo DR"]
    elo_rows = {
        "united states": {
            "code": "US",
            "name": "United States",
            "global_rank": 27,
            "rating": 1780,
            "rating_three_month_change": 33,
        },
        "dr congo": {
            "code": "CD",
            "name": "DR Congo",
            "global_rank": 58,
            "rating": 1645,
            "rating_three_month_change": -12,
        },
    }
    confederations = {"US": "CONCACAF", "CD": "CAF"}

    ratings = build_ratings(fixture_teams, elo_rows, confederations)

    assert ratings["USA"]["elo"] == 1780
    assert ratings["USA"]["host"] is True
    assert ratings["Congo DR"]["confederation"] == "CAF"


def test_team_ratings_cover_fixture_teams() -> None:
    fixtures = json.loads(Path("data/fixtures.json").read_text())
    ratings = json.loads(Path("data/team_ratings.json").read_text())["teams"]
    fixture_teams = {fixture["team_a"] for fixture in fixtures} | {
        fixture["team_b"] for fixture in fixtures
    }

    assert fixture_teams <= set(ratings)
