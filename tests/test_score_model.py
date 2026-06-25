from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import Fixture, MatchForecast
from fifa_arb_agent.score_model import build_score_grid


def test_score_grid_prices_handicap_and_totals() -> None:
    fixture = Fixture(
        match_id="a",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Brazil",
        team_b="Scotland",
    )
    forecast = MatchForecast(
        fixture=fixture,
        team_a_win=0.75,
        draw=0.12,
        team_b_win=0.13,
        fair_team_a_no_draw=0.85,
        fair_team_b_no_draw=0.15,
        model_notes=[],
    )

    grid = build_score_grid(forecast)

    assert grid.price_handicap("team_a", -1.5) > 0.25
    assert grid.price_handicap("team_b", 1.5) < 0.75
    assert 0.2 < grid.price_total_goals(2.5, "over") < 0.8
    assert abs(
        grid.price_total_goals(2.5, "over") + grid.price_total_goals(2.5, "under") - 1
    ) < 0.000001
