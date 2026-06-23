from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import Fixture, TeamContext, TeamRating
from fifa_arb_agent.ratings import TeamRatings, WorldCupCalibrator
from fifa_arb_agent.team_context import TeamContexts
from fifa_arb_agent.tournament import TournamentSimulator, summarize_stage_probabilities


def test_tournament_simulator_outputs_stage_probabilities() -> None:
    teams = [f"Team {index:02d}" for index in range(48)]
    fixtures = []
    contexts = {}
    ratings = {}

    for group_index in range(12):
        group = f"Group {chr(ord('A') + group_index)}"
        group_teams = teams[group_index * 4 : group_index * 4 + 4]
        for team_index, team in enumerate(group_teams):
            contexts[team] = TeamContext(group=group, squad_size=26, avg_age=26.5)
            ratings[team] = TeamRating(
                elo=2100 - (group_index * 4 + team_index) * 5,
                fifa_rank=group_index * 4 + team_index + 1,
                confederation="UEFA",
            )
        for i, team_a in enumerate(group_teams):
            for team_b in group_teams[i + 1 :]:
                fixtures.append(
                    Fixture(
                        match_id=f"{team_a}-{team_b}",
                        kickoff_utc=datetime(2026, 6, 1, tzinfo=UTC),
                        team_a=team_a,
                        team_b=team_b,
                        stage="group",
                    )
                )

    probabilities = TournamentSimulator(
        TeamRatings(ratings),
        TeamContexts(contexts),
        WorldCupCalibrator(),
        seed=1,
    ).simulate(fixtures, simulations=25)

    assert len(probabilities) == 48
    assert sum(item.top_32 for item in probabilities) == 32
    assert sum(item.top_8 for item in probabilities) == 8
    assert sum(item.semi_final for item in probabilities) == 4
    assert sum(item.final for item in probabilities) == 2
    assert sum(item.champion for item in probabilities) == 1
    summary = summarize_stage_probabilities(probabilities)
    assert "Tournament advancement probabilities" in summary
    assert "Quarter-finals - highest top-8 probability" in summary
    assert "Semi-finals - highest semi-final probability" in summary
    assert "Final - highest final probability" in summary
