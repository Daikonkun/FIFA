from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import Fixture, MarketOutcome, MatchForecast, PolymarketMarket
from fifa_arb_agent.recommendations import build_combo_recommendation


def test_build_combo_recommendation_mixes_1x2_and_handicap_legs() -> None:
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

    combo = build_combo_recommendation(forecast, [])

    assert combo.profile == "favorite-weighted"
    assert [leg.role for leg in combo.legs] == ["safety", "direction", "upside"]
    assert {leg.market_type for leg in combo.legs} == {"1x2", "handicap"}
    assert sum(leg.stake_weight for leg in combo.legs) == 1.0


def test_combo_recommendation_attaches_market_edges() -> None:
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
    markets = [
        PolymarketMarket(
            market_id="1x2",
            question="Brazil vs Scotland winner",
            outcomes=[
                MarketOutcome(name="Brazil", price=0.70),
                MarketOutcome(name="Draw", price=0.15),
                MarketOutcome(name="Scotland", price=0.15),
            ],
        ),
        PolymarketMarket(
            market_id="handicap",
            question="Brazil vs Scotland handicap",
            outcomes=[
                MarketOutcome(name="Brazil -1.5", price=0.30),
                MarketOutcome(name="Scotland +1.5", price=0.70),
            ],
        ),
    ]

    combo = build_combo_recommendation(forecast, markets)

    assert combo.legs[1].label == "Brazil 1X2"
    assert combo.legs[1].market_probability == 0.70
    assert round(combo.legs[1].edge or 0, 2) == 0.05
