from __future__ import annotations

import math
from dataclasses import dataclass

from fifa_arb_agent.models import MatchForecast


MAX_GOALS = 8


@dataclass(frozen=True)
class ScoreGrid:
    probabilities: dict[tuple[int, int], float]
    lambda_a: float
    lambda_b: float
    draw_factor: float

    def probability(self, goals_a: int, goals_b: int) -> float:
        return self.probabilities.get((goals_a, goals_b), 0.0)

    def price_handicap(self, team: str, handicap: float) -> float:
        total = 0.0
        for (goals_a, goals_b), probability in self.probabilities.items():
            if team == "team_a" and goals_a + handicap > goals_b:
                total += probability
            elif team == "team_b" and goals_b + handicap > goals_a:
                total += probability
        return total

    def price_total_goals(self, line: float, side: str) -> float:
        total = 0.0
        for (goals_a, goals_b), probability in self.probabilities.items():
            goals = goals_a + goals_b
            if side == "over" and goals > line:
                total += probability
            elif side == "under" and goals < line:
                total += probability
        return total

    def modal_score(self) -> tuple[int, int]:
        return max(self.probabilities.items(), key=lambda item: item[1])[0]


def build_score_grid(forecast: MatchForecast) -> ScoreGrid:
    target = (forecast.team_a_win, forecast.draw, forecast.team_b_win)
    total_goals_prior = _total_goals_prior(forecast)
    best: tuple[float, float, float, float] | None = None
    best_grid: dict[tuple[int, int], float] | None = None

    for lambda_a in _candidate_lambdas():
        for lambda_b in _candidate_lambdas():
            lambda_total = lambda_a + lambda_b
            if abs(lambda_total - total_goals_prior) > 1.4:
                continue
            base = _poisson_grid(lambda_a, lambda_b)
            for draw_factor in (0.75, 0.9, 1.05, 1.2, 1.4, 1.65, 1.9, 2.2):
                grid = _apply_low_score_correction(base, draw_factor)
                implied = _implied_result_probabilities(grid)
                error = sum((implied[index] - target[index]) ** 2 for index in range(3))
                error += 0.018 * (lambda_total - total_goals_prior) ** 2
                if best is None or error < best[0]:
                    best = (error, lambda_a, lambda_b, draw_factor)
                    best_grid = grid

    if best is None or best_grid is None:
        raise ValueError("Unable to build score grid.")

    _, lambda_a, lambda_b, draw_factor = best
    return ScoreGrid(best_grid, lambda_a, lambda_b, draw_factor)


def _total_goals_prior(forecast: MatchForecast) -> float:
    fixture = forecast.fixture
    stage = fixture.stage.lower()
    base = 2.45 if "group" in stage else 2.25
    favorite = max(forecast.team_a_win, forecast.team_b_win)
    imbalance = abs(forecast.team_a_win - forecast.team_b_win)
    base += 0.55 * max(favorite - 0.62, 0.0)
    base += 0.20 * imbalance
    base -= 0.35 * max(forecast.draw - 0.18, 0.0)
    return min(max(base, 1.65), 3.45)


def _candidate_lambdas() -> list[float]:
    return [value / 20 for value in range(6, 76)]


def _poisson_grid(lambda_a: float, lambda_b: float) -> dict[tuple[int, int], float]:
    probabilities = {}
    for goals_a in range(MAX_GOALS + 1):
        for goals_b in range(MAX_GOALS + 1):
            probabilities[(goals_a, goals_b)] = _poisson(goals_a, lambda_a) * _poisson(goals_b, lambda_b)
    return _normalize(probabilities)


def _poisson(k: int, lambda_value: float) -> float:
    return math.exp(-lambda_value) * lambda_value**k / math.factorial(k)


def _apply_low_score_correction(
    probabilities: dict[tuple[int, int], float], draw_factor: float
) -> dict[tuple[int, int], float]:
    adjusted = probabilities.copy()
    for score in ((0, 0), (1, 1)):
        adjusted[score] *= draw_factor
    adjusted[(1, 0)] *= 1.08
    adjusted[(0, 1)] *= 1.08
    return _normalize(adjusted)


def _implied_result_probabilities(probabilities: dict[tuple[int, int], float]) -> tuple[float, float, float]:
    team_a = 0.0
    draw = 0.0
    team_b = 0.0
    for (goals_a, goals_b), probability in probabilities.items():
        if goals_a > goals_b:
            team_a += probability
        elif goals_b > goals_a:
            team_b += probability
        else:
            draw += probability
    return team_a, draw, team_b


def _normalize(probabilities: dict[tuple[int, int], float]) -> dict[tuple[int, int], float]:
    total = sum(probabilities.values())
    return {score: probability / total for score, probability in probabilities.items()}
