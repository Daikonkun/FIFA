from __future__ import annotations

from scripts.update_team_context import build_team_context


def test_build_team_context_summarizes_api_payloads() -> None:
    context = build_team_context(
        {
            "team": {
                "id": 9,
                "name": "Spain",
                "code": "ESP",
                "logo": "logo.png",
                "founded": 1913,
            },
            "venue": {"name": "Stadium"},
        },
        [
            {
                "players": [
                    {"age": 24, "position": "Goalkeeper"},
                    {"age": 28, "position": "Defender"},
                    {"age": 30, "position": "Attacker"},
                ]
            }
        ],
        {
            "form": "W",
            "fixtures": {
                "played": {"total": 1},
                "wins": {"total": 1},
                "draws": {"total": 0},
                "loses": {"total": 0},
            },
            "goals": {
                "for": {"total": {"total": 2}},
                "against": {"total": {"total": 0}},
            },
        },
        [
            {
                "league": {
                    "standings": [
                        [
                            {
                                "rank": 1,
                                "team": {"id": 9},
                                "points": 3,
                                "goalsDiff": 2,
                                "group": "Group A",
                                "form": "W",
                            }
                        ]
                    ]
                }
            }
        ],
        [{"player": {"name": "Example"}}],
    )

    assert context["api_team_id"] == 9
    assert context["squad_size"] == 3
    assert context["avg_age"] == 27.3
    assert context["position_counts"]["Defender"] == 1
    assert context["tournament_points"] == 3
    assert context["injury_count"] == 1
