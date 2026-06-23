from __future__ import annotations

import json
import math
from pathlib import Path

from fifa_arb_agent.models import Fixture, MatchForecast, TeamContext, TeamRating
from fifa_arb_agent.team_context import TeamContexts


CONFEDERATION_WEIGHTS = {
    "UEFA": 0.04,
    "CONMEBOL": 0.04,
    "CONCACAF": 0.00,
    "CAF": -0.01,
    "AFC": -0.015,
    "OFC": -0.03,
    "UNKNOWN": 0.00,
}

RANK_WEIGHT = 0.05
CURRENT_WC_POINTS_WEIGHT = 0.10
CURRENT_WC_GOAL_DIFF_WEIGHT = 0.06
CURRENT_WC_FORM_WEIGHT = 0.04
CURRENT_WC_SIGNAL_CAP = 0.25
API_CONTEXT_CAP = 0.30


class TeamRatings:
    def __init__(self, teams: dict[str, TeamRating]) -> None:
        self.teams = teams
        self._normalized_teams = {_norm_team(name): value for name, value in teams.items()}
        self.defaulted_teams: set[str] = set()

    @classmethod
    def load(cls, path: Path) -> "TeamRatings":
        payload = json.loads(path.read_text())
        raw_teams = payload.get("teams", payload)
        return cls({name: TeamRating.model_validate(value) for name, value in raw_teams.items()})

    def get(self, team: str) -> TeamRating:
        rating = self.teams.get(team) or self._normalized_teams.get(_norm_team(team))
        if rating is not None:
            return rating

        self.defaulted_teams.add(team)
        return TeamRating(elo=1800, confederation="UNKNOWN")

    def was_defaulted(self, team: str) -> bool:
        return team in self.defaulted_teams


class WorldCupCalibrator:
    """Small transparent model for pre-match research alerts, not an execution model."""

    def forecast(
        self, fixture: Fixture, ratings: TeamRatings, contexts: TeamContexts | None = None
    ) -> MatchForecast:
        team_a = ratings.get(fixture.team_a)
        team_b = ratings.get(fixture.team_b)
        strength_delta, notes = self._strength_delta(fixture, team_a, team_b)
        if contexts is not None:
            context_delta, context_notes = self._context_delta(
                contexts.get(fixture.team_a), contexts.get(fixture.team_b)
            )
            strength_delta += context_delta
            notes.extend(context_notes)
        if ratings.was_defaulted(fixture.team_a):
            notes.append(f"low_confidence_missing_rating={fixture.team_a}")
        if ratings.was_defaulted(fixture.team_b):
            notes.append(f"low_confidence_missing_rating={fixture.team_b}")

        side_a_logit = strength_delta / 2
        side_b_logit = -strength_delta / 2
        draw_logit = self._draw_logit(fixture.stage, strength_delta)

        probs = _softmax([side_a_logit, draw_logit, side_b_logit])
        no_draw_total = probs[0] + probs[2]

        return MatchForecast(
            fixture=fixture,
            team_a_win=probs[0],
            draw=probs[1],
            team_b_win=probs[2],
            fair_team_a_no_draw=probs[0] / no_draw_total,
            fair_team_b_no_draw=probs[2] / no_draw_total,
            model_notes=notes,
        )

    def _strength_delta(
        self, fixture: Fixture, team_a: TeamRating, team_b: TeamRating
    ) -> tuple[float, list[str]]:
        notes: list[str] = []

        elo_component = (team_a.elo - team_b.elo) * math.log(10) / 400
        notes.append(f"elo_delta={team_a.elo - team_b.elo:+.0f}")

        rank_component = 0.0
        if team_a.fifa_rank and team_b.fifa_rank:
            rank_component = (team_b.fifa_rank - team_a.fifa_rank) / 50 * RANK_WEIGHT
            notes.append(f"rank_delta={team_b.fifa_rank - team_a.fifa_rank:+d}")

        wc_component = (
            math.log1p(team_a.wc_points_last_3) - math.log1p(team_b.wc_points_last_3)
        ) * 0.11

        conf_component = CONFEDERATION_WEIGHTS.get(
            team_a.confederation.upper(), 0.0
        ) - CONFEDERATION_WEIGHTS.get(team_b.confederation.upper(), 0.0)

        host_component = (0.22 if team_a.host else 0.0) - (0.22 if team_b.host else 0.0)

        rest_component = 0.0
        if fixture.rest_days_a is not None and fixture.rest_days_b is not None:
            rest_delta = max(min(fixture.rest_days_a - fixture.rest_days_b, 3), -3)
            rest_component = rest_delta * 0.055
            notes.append(f"rest_delta={rest_delta:+.1f}d")

        form_component = (team_a.form_delta - team_b.form_delta) * 0.35
        injury_component = (team_b.injury_penalty - team_a.injury_penalty) * 0.7

        total = (
            elo_component
            + rank_component
            + wc_component
            + conf_component
            + host_component
            + rest_component
            + form_component
            + injury_component
        )
        notes.append(f"worldcup_adjustment={total - elo_component:+.3f} logits")
        return total, notes

    def _context_delta(
        self, team_a: TeamContext | None, team_b: TeamContext | None
    ) -> tuple[float, list[str]]:
        if team_a is None or team_b is None:
            missing = []
            if team_a is None:
                missing.append("team_a")
            if team_b is None:
                missing.append("team_b")
            return 0.0, [f"api_context_missing={'+'.join(missing)}"]

        tournament_component = _team_tournament_signal(team_a) - _team_tournament_signal(team_b)
        squad_component = _team_squad_signal(team_a) - _team_squad_signal(team_b)
        total = _clamp(tournament_component + squad_component, -API_CONTEXT_CAP, API_CONTEXT_CAP)

        notes = [
            f"api_tournament_delta={tournament_component:+.3f} logits",
            f"api_squad_delta={squad_component:+.3f} logits",
        ]
        return total, notes

    @staticmethod
    def _draw_logit(stage: str, strength_delta: float) -> float:
        stage_lower = stage.lower()
        base = -1.16
        if "group" in stage_lower:
            base += 0.12
        if "knockout" in stage_lower or "final" in stage_lower or "round" in stage_lower:
            base -= 0.08

        closeness_boost = 0.22 * math.exp(-abs(strength_delta))
        return base + closeness_boost


def _softmax(values: list[float]) -> list[float]:
    max_value = max(values)
    exp_values = [math.exp(value - max_value) for value in values]
    total = sum(exp_values)
    return [value / total for value in exp_values]


def _team_tournament_signal(context: TeamContext) -> float:
    if context.tournament_played <= 0:
        return 0.0
    points_per_match = context.tournament_points / context.tournament_played
    goal_diff_per_match = context.goals_diff / context.tournament_played
    form_score = _form_score(context.tournament_form or "")
    points_signal = (points_per_match - 1.0) * CURRENT_WC_POINTS_WEIGHT
    goal_diff_signal = goal_diff_per_match * CURRENT_WC_GOAL_DIFF_WEIGHT
    form_signal = form_score * CURRENT_WC_FORM_WEIGHT
    return _clamp(
        points_signal + goal_diff_signal + form_signal,
        -CURRENT_WC_SIGNAL_CAP,
        CURRENT_WC_SIGNAL_CAP,
    )


def _team_squad_signal(context: TeamContext) -> float:
    if context.squad_size <= 0:
        return -_clamp(context.injury_count * 0.018, 0.0, 0.08)
    depth_signal = _clamp((min(context.squad_size, 26) - 23) * 0.012, -0.06, 0.04)
    age_signal = 0.0
    if context.avg_age is not None:
        age_signal = -_clamp(abs(context.avg_age - 26.5) * 0.01, 0.0, 0.05)
    balance_signal = 0.0
    if context.position_counts:
        goalkeeper_count = context.position_counts.get("Goalkeeper", 0)
        defender_count = context.position_counts.get("Defender", 0)
        forward_count = context.position_counts.get("Attacker", 0) + context.position_counts.get(
            "Forward", 0
        )
        if goalkeeper_count >= 3 and defender_count >= 6 and forward_count >= 3:
            balance_signal = 0.018
    injury_signal = -_clamp(context.injury_count * 0.018, 0.0, 0.08)
    return depth_signal + age_signal + balance_signal + injury_signal


def _form_score(form: str) -> float:
    if not form:
        return 0.0
    values = {"W": 1.0, "D": 0.25, "L": -1.0}
    scores = [values.get(char.upper(), 0.0) for char in form[-5:]]
    return sum(scores) / len(scores) if scores else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _norm_team(value: str) -> str:
    aliases = {
        "usa": "united states",
        "u s a": "united states",
        "us": "united states",
        "south korea": "korea republic",
        "korea republic": "korea republic",
    }
    normalized = " ".join(value.casefold().replace("&", " and ").split())
    return aliases.get(normalized, normalized)
