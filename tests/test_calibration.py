from __future__ import annotations

from datetime import UTC, datetime

from fifa_arb_agent.models import Fixture, TeamContext, TeamRating
from fifa_arb_agent.ratings import CalibrationParameters, TeamRatings, WorldCupCalibrator
from fifa_arb_agent.team_context import TeamContexts


def test_stronger_team_gets_higher_win_probability() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="A",
        team_b="B",
        rest_days_a=5,
        rest_days_b=4,
    )
    ratings = TeamRatings(
        {
            "A": TeamRating(elo=2100, fifa_rank=2, wc_points_last_3=18, confederation="UEFA"),
            "B": TeamRating(elo=1800, fifa_rank=30, wc_points_last_3=2, confederation="AFC"),
        }
    )

    forecast = WorldCupCalibrator().forecast(fixture, ratings)

    assert forecast.team_a_win > forecast.team_b_win
    assert abs(forecast.team_a_win + forecast.draw + forecast.team_b_win - 1) < 0.000001


def test_host_advantage_moves_probability() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="A",
        team_b="B",
    )
    neutral = TeamRatings(
        {
            "A": TeamRating(elo=1900, fifa_rank=20, confederation="CONCACAF", host=False),
            "B": TeamRating(elo=1900, fifa_rank=20, confederation="CONCACAF", host=False),
        }
    )
    host = TeamRatings(
        {
            "A": TeamRating(elo=1900, fifa_rank=20, confederation="CONCACAF", host=True),
            "B": TeamRating(elo=1900, fifa_rank=20, confederation="CONCACAF", host=False),
        }
    )
    calibrator = WorldCupCalibrator()

    assert calibrator.forecast(fixture, host).team_a_win > calibrator.forecast(
        fixture, neutral
    ).team_a_win


def test_missing_team_rating_defaults_with_low_confidence_note() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="Known",
        team_b="Missing",
    )
    ratings = TeamRatings(
        {
            "Known": TeamRating(elo=1900, fifa_rank=20, confederation="UEFA"),
        }
    )

    forecast = WorldCupCalibrator().forecast(fixture, ratings)

    assert forecast.team_a_win > forecast.team_b_win
    assert "low_confidence_missing_rating=Missing" in forecast.model_notes


def test_api_football_context_moves_forecast_modestly() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="A",
        team_b="B",
    )
    ratings = TeamRatings(
        {
            "A": TeamRating(elo=1900, fifa_rank=20, confederation="UEFA"),
            "B": TeamRating(elo=1900, fifa_rank=20, confederation="UEFA"),
        }
    )
    contexts = TeamContexts(
        {
            "A": TeamContext(
                squad_size=26,
                avg_age=26.5,
                position_counts={"Goalkeeper": 3, "Defender": 8, "Attacker": 4},
                tournament_played=1,
                tournament_wins=1,
                tournament_points=3,
                goals_for=2,
                goals_against=0,
                goals_diff=2,
                tournament_form="W",
            ),
            "B": TeamContext(
                squad_size=20,
                avg_age=31.0,
                position_counts={"Goalkeeper": 2, "Defender": 5, "Attacker": 2},
                tournament_played=1,
                tournament_losses=1,
                tournament_points=0,
                goals_for=0,
                goals_against=2,
                goals_diff=-2,
                tournament_form="L",
                injury_count=2,
            ),
        }
    )
    calibrator = WorldCupCalibrator()

    base = calibrator.forecast(fixture, ratings)
    enriched = calibrator.forecast(fixture, ratings, contexts)

    assert enriched.team_a_win > base.team_a_win
    assert any(note.startswith("api_tournament_delta=") for note in enriched.model_notes)
    assert enriched.model_version == "calibration-v2"
    assert enriched.calibration_params["rank_weight"] == 0.025


def test_current_world_cup_weight_is_tuneable() -> None:
    fixture = Fixture(
        match_id="x",
        kickoff_utc=datetime(2026, 6, 17, tzinfo=UTC),
        team_a="A",
        team_b="B",
    )
    ratings = TeamRatings(
        {
            "A": TeamRating(elo=1900, fifa_rank=20, confederation="UEFA"),
            "B": TeamRating(elo=1900, fifa_rank=20, confederation="UEFA"),
        }
    )
    contexts = TeamContexts(
        {
            "A": TeamContext(tournament_played=2, tournament_points=3, goals_diff=1),
            "B": TeamContext(tournament_played=2, tournament_points=2, goals_diff=0),
        }
    )

    baseline = WorldCupCalibrator().forecast(fixture, ratings, contexts)
    heavier = WorldCupCalibrator(
        CalibrationParameters(current_wc_points_weight=0.24, current_wc_goal_diff_weight=0.10)
    ).forecast(fixture, ratings, contexts)

    assert heavier.team_a_win > baseline.team_a_win
