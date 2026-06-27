from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import replace
from pathlib import Path

from fifa_arb_agent.evaluation import evaluate_stored_scans
from fifa_arb_agent.models import Fixture
from fifa_arb_agent.ratings import CalibrationParameters, TeamRatings, WorldCupCalibrator
from fifa_arb_agent.team_context import TeamContexts


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate FIFA model snapshots and candidates.")
    parser.add_argument("--database", default="reports/fifa_agent.sqlite3")
    parser.add_argument("--fixtures", default="data/fixtures.json")
    parser.add_argument("--ratings", default="data/team_ratings.json")
    parser.add_argument("--team-context", default="data/team_context.json")
    parser.add_argument("--edge-threshold", type=float, default=0.15)
    parser.add_argument("--grid-search", action="store_true")
    args = parser.parse_args()

    result = evaluate_stored_scans(
        Path(args.database),
        Path(args.fixtures),
        edge_threshold=args.edge_threshold,
    )
    print(result.render())

    if args.grid_search:
        print("")
        print(
            _render_grid_search(
                Path(args.fixtures),
                Path(args.ratings),
                Path(args.team_context),
            )
        )


def _render_grid_search(fixtures_path: Path, ratings_path: Path, context_path: Path) -> str:
    fixtures = _load_completed_fixtures(fixtures_path)
    ratings = TeamRatings.load(ratings_path)
    contexts = TeamContexts.load(context_path)
    rows = []
    for name, parameters in _candidate_parameters():
        calibrator = WorldCupCalibrator(parameters)
        brier = 0.0
        logloss = 0.0
        hits = 0
        for fixture in fixtures:
            forecast = calibrator.forecast(fixture, ratings, contexts)
            probabilities = {
                "team_a": forecast.team_a_win,
                "draw": forecast.draw,
                "team_b": forecast.team_b_win,
            }
            actual = _actual_result(fixture.goals_a, fixture.goals_b)
            hits += int(max(probabilities, key=probabilities.get) == actual)
            brier += sum(
                (probability - (1.0 if outcome == actual else 0.0)) ** 2
                for outcome, probability in probabilities.items()
            )
            logloss += -math.log(max(probabilities[actual], 1e-12))
        total = len(fixtures) or 1
        rows.append((logloss / total, brier / total, hits / total, name, parameters))

    lines = ["Calibration candidate grid search", "Scope: current-snapshot completed fixtures."]
    for logloss, brier, accuracy, name, parameters in sorted(rows)[:8]:
        lines.append(
            f"- {name}: logloss {logloss:.3f}, brier {brier:.3f}, "
            f"accuracy {accuracy:.1%}, params {parameters.model_dump()}"
        )
    return "\n".join(lines)


def _candidate_parameters() -> list[tuple[str, CalibrationParameters]]:
    base = CalibrationParameters()
    candidates = [("baseline", base)]
    for rank_weight, points_weight, gd_weight, form_weight, draw_boost in itertools.product(
        (0.025, 0.05, 0.075),
        (0.10, 0.14, 0.18),
        (0.06, 0.09),
        (0.04, 0.07),
        (0.18, 0.22, 0.26),
    ):
        name = (
            f"rank={rank_weight:.3f},points={points_weight:.2f},"
            f"gd={gd_weight:.2f},form={form_weight:.2f},draw={draw_boost:.2f}"
        )
        candidates.append(
            (
                name,
                replace(
                    base,
                    rank_weight=rank_weight,
                    current_wc_points_weight=points_weight,
                    current_wc_goal_diff_weight=gd_weight,
                    current_wc_form_weight=form_weight,
                    draw_closeness_boost=draw_boost,
                ),
            )
        )
    return candidates


def _actual_result(goals_a: int, goals_b: int) -> str:
    if goals_a > goals_b:
        return "team_a"
    if goals_b > goals_a:
        return "team_b"
    return "draw"


def _load_completed_fixtures(path: Path) -> list[Fixture]:
    payload = json.loads(path.read_text())
    raw_fixtures = payload["fixtures"] if isinstance(payload, dict) and "fixtures" in payload else payload
    return [
        Fixture.model_validate(item)
        for item in raw_fixtures
        if item.get("goals_a") is not None and item.get("goals_b") is not None
    ]


if __name__ == "__main__":
    main()
