from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import Fixture, MarketOutcome, PolymarketMarket
from fifa_arb_agent.polymarket import (
    _looks_like_supported_match_market,
    _looks_like_supported_stage_market,
    extract_prop_market_specs,
    extract_stage_market_team,
    match_team_outcome,
    match_yes_outcome,
)


def test_matches_named_outcome() -> None:
    market = PolymarketMarket(
        market_id="1",
        question="Argentina vs France winner",
        outcomes=[
            MarketOutcome(name="Argentina", price=0.45),
            MarketOutcome(name="France", price=0.35),
            MarketOutcome(name="Draw", price=0.20),
        ],
    )

    assert match_team_outcome(market, "Argentina").price == 0.45


def test_matches_yes_no_question() -> None:
    market = PolymarketMarket(
        market_id="1",
        question="Will Brazil beat England in the 2026 World Cup?",
        outcomes=[
            MarketOutcome(name="Yes", price=0.52),
            MarketOutcome(name="No", price=0.48),
        ],
    )

    assert match_team_outcome(market, "Brazil").price == 0.52


def test_supported_match_market_excludes_announcer_props() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="England",
        team_b="Croatia",
    )
    market = PolymarketMarket(
        market_id="1",
        question="What will the announcers say during England vs Croatia?",
        outcomes=[
            MarketOutcome(name="England", price=0.20),
            MarketOutcome(name="Croatia", price=0.20),
        ],
    )

    assert not _looks_like_supported_match_market(market, fixture)


def test_supported_match_market_allows_three_way_winner() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="England",
        team_b="Croatia",
    )
    market = PolymarketMarket(
        market_id="1",
        question="England vs Croatia match winner",
        outcomes=[
            MarketOutcome(name="England", price=0.44),
            MarketOutcome(name="Croatia", price=0.31),
            MarketOutcome(name="Draw", price=0.25),
        ],
    )

    assert _looks_like_supported_match_market(market, fixture)


def test_supported_stage_market_extracts_team_and_yes_outcome() -> None:
    market = PolymarketMarket(
        market_id="1",
        question="Will Argentina reach the Semifinals at the 2026 FIFA World Cup?",
        event_title="World Cup: Nation To Reach Semifinals",
        outcomes=[
            MarketOutcome(name="Yes", price=0.40),
            MarketOutcome(name="No", price=0.60),
        ],
    )

    assert _looks_like_supported_stage_market(market, "semifinals")
    assert extract_stage_market_team(market) == "Argentina"
    assert match_yes_outcome(market).price == 0.40


def test_extracts_handicap_market_specs() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="Brazil",
        team_b="Scotland",
    )
    market = PolymarketMarket(
        market_id="1",
        question="Brazil vs Scotland handicap",
        outcomes=[
            MarketOutcome(name="Brazil -1.5", price=0.42),
            MarketOutcome(name="Scotland +1.5", price=0.58),
        ],
    )

    specs = extract_prop_market_specs(market, fixture)

    assert [(spec.label, spec.side, spec.line) for spec in specs] == [
        ("Brazil -1.5", "team_a", -1.5),
        ("Scotland +1.5", "team_b", 1.5),
    ]
    assert _looks_like_supported_match_market(market, fixture)


def test_extracts_total_goals_market_specs() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="Brazil",
        team_b="Scotland",
    )
    market = PolymarketMarket(
        market_id="1",
        question="Brazil vs Scotland total goals 2.5",
        outcomes=[
            MarketOutcome(name="Over 2.5", price=0.51),
            MarketOutcome(name="Under 2.5", price=0.49),
        ],
    )

    specs = extract_prop_market_specs(market, fixture)

    assert [(spec.label, spec.side, spec.line) for spec in specs] == [
        ("Over 2.5 goals", "over", 2.5),
        ("Under 2.5 goals", "under", 2.5),
    ]
    assert _looks_like_supported_match_market(market, fixture)
