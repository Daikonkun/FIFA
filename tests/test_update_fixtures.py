from __future__ import annotations

from scripts.update_fixtures import normalize_fixtures


def test_normalize_api_football_fixture() -> None:
    fixtures = [
        {
            "fixture": {
                "id": 123,
                "date": "2026-06-16T19:00:00+00:00",
                "venue": {"name": "MetLife Stadium", "city": "East Rutherford"},
            },
            "league": {"round": "Group Stage - 1"},
            "teams": {
                "home": {"id": 10, "name": "Argentina"},
                "away": {"id": 20, "name": "France"},
            },
        }
    ]

    normalized = normalize_fixtures(fixtures)

    assert normalized == [
        {
            "match_id": "api-football-123",
            "kickoff_utc": "2026-06-16T19:00:00Z",
            "team_a": "Argentina",
            "team_b": "France",
            "stage": "group",
            "venue": "MetLife Stadium, East Rutherford",
            "neutral_site": True,
            "rest_days_a": None,
            "rest_days_b": None,
            "status_short": None,
            "goals_a": None,
            "goals_b": None,
        }
    ]
