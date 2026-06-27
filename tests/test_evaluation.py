from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fifa_arb_agent.evaluation import evaluate_stored_scans
from fifa_arb_agent.models import Fixture, MarketOutcome, MatchForecast, PolymarketMarket
from fifa_arb_agent.storage import ReportStore


def test_evaluate_stored_scans_scores_pre_match_alerts(tmp_path) -> None:
    kickoff = datetime.now(UTC) + timedelta(days=1)
    forecast_fixture = Fixture(
        match_id="a",
        kickoff_utc=kickoff,
        team_a="Argentina",
        team_b="France",
    )
    completed_fixture = forecast_fixture.model_copy(update={"goals_a": 2, "goals_b": 0})
    forecast = MatchForecast(
        fixture=forecast_fixture,
        team_a_win=0.70,
        draw=0.15,
        team_b_win=0.15,
        fair_team_a_no_draw=0.82,
        fair_team_b_no_draw=0.18,
        model_notes=[],
    )
    market = PolymarketMarket(
        market_id="m",
        question="Argentina vs France winner",
        outcomes=[
            MarketOutcome(name="Argentina", price=0.50),
            MarketOutcome(name="Draw", price=0.20),
            MarketOutcome(name="France", price=0.30),
        ],
    )
    database_path = tmp_path / "reports.sqlite3"
    ReportStore(database_path).save("report", [forecast], {"a": [market]}, {"a": []})
    fixtures_path = tmp_path / "fixtures.json"
    fixtures_path.write_text(json.dumps([completed_fixture.model_dump(mode="json")]))

    result = evaluate_stored_scans(database_path, fixtures_path, edge_threshold=0.15)

    assert result.settled_pre_match_forecasts == 1
    assert result.top_pick_hits == 1
    assert result.one_x_two_alerts.count == 1
    assert result.one_x_two_alerts.hits == 1
    assert "Historical model evaluation" in result.render()
