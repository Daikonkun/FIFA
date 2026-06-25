from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import (
    Edge,
    Fixture,
    MarketOutcome,
    MatchForecast,
    PolymarketMarket,
    TeamStageProbability,
)
from fifa_arb_agent.report import (
    build_backtest_report,
    build_report,
    build_upcoming_prediction_report,
    find_prop_edges,
    find_stage_edges,
)


def test_alerts_only_report_excludes_matches_without_edges() -> None:
    fixture_a = Fixture(
        match_id="a",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Argentina",
        team_b="France",
    )
    fixture_b = Fixture(
        match_id="b",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="Brazil",
        team_b="England",
    )
    forecasts = [
        MatchForecast(
            fixture=fixture_a,
            team_a_win=0.6,
            draw=0.2,
            team_b_win=0.2,
            fair_team_a_no_draw=0.75,
            fair_team_b_no_draw=0.25,
            model_notes=[],
        ),
        MatchForecast(
            fixture=fixture_b,
            team_a_win=0.4,
            draw=0.2,
            team_b_win=0.4,
            fair_team_a_no_draw=0.5,
            fair_team_b_no_draw=0.5,
            model_notes=[],
        ),
    ]
    market = PolymarketMarket(
        market_id="m",
        question="Argentina vs France winner",
        outcomes=[MarketOutcome(name="Argentina", price=0.5)],
    )
    edge = Edge(
        side="team_a",
        team="Argentina",
        model_probability=0.6,
        market_probability=0.5,
        edge=0.1,
        market=market,
        matched_outcome=market.outcomes[0],
    )

    report = build_report(
        forecasts,
        {"a": [market], "b": []},
        {"a": [edge], "b": []},
        "Asia/Hong_Kong",
        alerts_only=True,
    )

    assert "Argentina vs France" in report
    assert "Brazil vs England" not in report
    assert "Alerts: none above threshold" not in report


def test_full_report_includes_upcoming_prediction_details() -> None:
    fixture = Fixture(
        match_id="a",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Argentina",
        team_b="France",
    )
    forecast = MatchForecast(
        fixture=fixture,
        team_a_win=0.6,
        draw=0.2,
        team_b_win=0.2,
        fair_team_a_no_draw=0.75,
        fair_team_b_no_draw=0.25,
        model_notes=["elo_delta=+100"],
    )

    report = build_report([forecast], {"a": []}, {"a": []}, "Asia/Hong_Kong")

    assert "Upcoming match predictions:" in report
    assert "Model: Argentina 60.0%, Draw 20.0%, France 20.0%" in report
    assert "No-draw fair: Argentina 75.0%, France 25.0%" in report


def test_full_report_includes_prediction_market_deviations() -> None:
    fixture = Fixture(
        match_id="a",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Argentina",
        team_b="France",
    )
    forecast = MatchForecast(
        fixture=fixture,
        team_a_win=0.6,
        draw=0.2,
        team_b_win=0.2,
        fair_team_a_no_draw=0.75,
        fair_team_b_no_draw=0.25,
        model_notes=[],
    )
    market = PolymarketMarket(
        market_id="m",
        question="Argentina vs France winner",
        outcomes=[
            MarketOutcome(name="Argentina", price=0.55),
            MarketOutcome(name="Draw", price=0.20),
            MarketOutcome(name="France", price=0.25),
        ],
    )

    report = build_report([forecast], {"a": [market]}, {"a": []}, "Asia/Hong_Kong")

    assert "Market deviations:" in report
    assert "- Argentina: model 60.0% vs market 55.0%; deviation +5.0%" in report
    assert "- Draw: model 20.0% vs market 20.0%; deviation +0.0%" in report
    assert "- France: model 20.0% vs market 25.0%; deviation -5.0%" in report


def test_full_report_includes_handicap_and_total_deviations() -> None:
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
    market = PolymarketMarket(
        market_id="m",
        question="Brazil vs Scotland handicap and total goals",
        outcomes=[
            MarketOutcome(name="Brazil -1.5", price=0.20),
            MarketOutcome(name="Scotland +1.5", price=0.80),
            MarketOutcome(name="Over 2.5", price=0.35),
            MarketOutcome(name="Under 2.5", price=0.65),
        ],
    )

    prop_edges = find_prop_edges(forecast, [market], 0.15, 0)
    report = build_report(
        [forecast],
        {"a": [market]},
        {"a": []},
        "Asia/Hong_Kong",
        prop_edge_map={"a": prop_edges},
    )

    assert "Handicap/total deviations:" in report
    assert "Brazil -1.5: model" in report
    assert "Over 2.5 goals: model" in report
    assert "Handicap/total alerts:" in report


def test_upcoming_prediction_report_is_threshold_free() -> None:
    fixture = Fixture(
        match_id="a",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Argentina",
        team_b="France",
    )
    forecast = MatchForecast(
        fixture=fixture,
        team_a_win=0.6,
        draw=0.2,
        team_b_win=0.2,
        fair_team_a_no_draw=0.75,
        fair_team_b_no_draw=0.25,
        model_notes=[],
    )
    market = PolymarketMarket(
        market_id="m",
        question="Argentina vs France winner",
        outcomes=[
            MarketOutcome(name="Argentina", price=0.58),
            MarketOutcome(name="Draw", price=0.20),
            MarketOutcome(name="France", price=0.22),
        ],
    )

    report = build_upcoming_prediction_report([forecast], {"a": [market]}, "Asia/Hong_Kong")

    assert "Match observations are not filtered by the arbitrage threshold." in report
    assert "Argentina vs France" in report
    assert "Market dev: Argentina +2.0%, Draw +0.0%, France -2.0%" in report


def test_upcoming_prediction_report_includes_prop_deviation_summary() -> None:
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
    market = PolymarketMarket(
        market_id="m",
        question="Brazil vs Scotland handicap",
        outcomes=[
            MarketOutcome(name="Brazil -1.5", price=0.40),
            MarketOutcome(name="Scotland +1.5", price=0.60),
        ],
    )

    report = build_upcoming_prediction_report([forecast], {"a": [market]}, "Asia/Hong_Kong")

    assert "Handicap/total dev: Brazil -1.5" in report
    assert "Scotland +1.5" in report


def test_find_stage_edges_compares_stage_market_prices() -> None:
    probability = TeamStageProbability(
        team="Argentina",
        top_8=0.8,
        semi_final=0.64,
        final=0.42,
        champion=0.27,
    )
    market = PolymarketMarket(
        market_id="m",
        question="Will Argentina reach the Semifinals at the 2026 FIFA World Cup?",
        event_title="World Cup: Nation To Reach Semifinals",
        outcomes=[MarketOutcome(name="Yes", price=0.40), MarketOutcome(name="No", price=0.60)],
    )

    edges = find_stage_edges([probability], {"semifinals": [market]}, 0.06, 0)

    assert len(edges) == 1
    assert edges[0].team == "Argentina"
    assert round(edges[0].edge, 2) == 0.24


def test_find_stage_edges_uses_inclusive_threshold() -> None:
    probability = TeamStageProbability(team="Argentina", semi_final=0.55)
    market = PolymarketMarket(
        market_id="m",
        question="Will Argentina reach the Semifinals at the 2026 FIFA World Cup?",
        event_title="World Cup: Nation To Reach Semifinals",
        outcomes=[MarketOutcome(name="Yes", price=0.40), MarketOutcome(name="No", price=0.60)],
    )

    edges = find_stage_edges([probability], {"semifinals": [market]}, 0.15, 0)

    assert len(edges) == 1
    assert edges[0].team == "Argentina"


def test_build_backtest_report_scores_completed_matches() -> None:
    win_fixture = Fixture(
        match_id="win",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Argentina",
        team_b="France",
        goals_a=2,
        goals_b=0,
    )
    draw_fixture = Fixture(
        match_id="draw",
        kickoff_utc=datetime(2026, 6, 18, tzinfo=UTC),
        team_a="Brazil",
        team_b="England",
        goals_a=1,
        goals_b=1,
    )
    forecasts = [
        MatchForecast(
            fixture=win_fixture,
            team_a_win=0.6,
            draw=0.2,
            team_b_win=0.2,
            fair_team_a_no_draw=0.75,
            fair_team_b_no_draw=0.25,
            model_notes=[],
        ),
        MatchForecast(
            fixture=draw_fixture,
            team_a_win=0.4,
            draw=0.2,
            team_b_win=0.4,
            fair_team_a_no_draw=0.5,
            fair_team_b_no_draw=0.5,
            model_notes=[],
        ),
    ]

    report = build_backtest_report(forecasts, "Asia/Hong_Kong")

    assert "Completed fixtures tested: 2" in report
    assert "1X2 top-pick accuracy: 1/2 (50.0%)" in report
    assert "Non-draw side accuracy: 1/1 (100.0%)" in report
    assert "Draw top-pick hits: 0/1 (0.0%)" in report
