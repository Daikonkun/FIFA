from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from fifa_arb_agent.models import Fixture, TeamStageProbability
from fifa_arb_agent.ratings import TeamRatings, WorldCupCalibrator
from fifa_arb_agent.team_context import TeamContexts


COMPLETED_STATUSES = {"FT", "AET", "PEN"}


@dataclass
class TableRow:
    team: str
    points: int = 0
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against


class TournamentSimulator:
    def __init__(
        self,
        ratings: TeamRatings,
        contexts: TeamContexts,
        calibrator: WorldCupCalibrator | None = None,
        seed: int = 2026,
    ) -> None:
        self.ratings = ratings
        self.contexts = contexts
        self.calibrator = calibrator or WorldCupCalibrator()
        self.random = random.Random(seed)
        self._fixture_probability_cache: dict[str, tuple[float, float, float]] = {}
        self._advance_probability_cache: dict[tuple[str, str, str], float] = {}

    def simulate(self, fixtures: list[Fixture], simulations: int) -> list[TeamStageProbability]:
        group_fixtures = [fixture for fixture in fixtures if _is_group_stage(fixture)]
        if not group_fixtures:
            raise ValueError("Tournament simulation requires group-stage fixtures.")

        teams = sorted({fixture.team_a for fixture in group_fixtures} | {fixture.team_b for fixture in group_fixtures})
        counts = {
            team: defaultdict(int)
            for team in teams
        }

        group_map = self._group_map(teams)
        for _ in range(simulations):
            qualifiers = self._simulate_group_stage(group_fixtures, group_map)
            for team in qualifiers:
                counts[team]["top_32"] += 1

            round_of_16 = self._play_knockout_round(qualifiers, "round_of_32")
            for team in round_of_16:
                counts[team]["top_16"] += 1

            top_8 = self._play_knockout_round(round_of_16, "round_of_16")
            for team in top_8:
                counts[team]["top_8"] += 1

            semi_finalists = self._play_knockout_round(top_8, "quarter_final")
            for team in semi_finalists:
                counts[team]["semi_final"] += 1

            finalists = self._play_knockout_round(semi_finalists, "semi_final")
            for team in finalists:
                counts[team]["final"] += 1

            champion = self._play_knockout_round(finalists, "final")[0]
            counts[champion]["champion"] += 1

        return sorted(
            [
                TeamStageProbability(
                    team=team,
                    top_32=counts[team]["top_32"] / simulations,
                    top_16=counts[team]["top_16"] / simulations,
                    top_8=counts[team]["top_8"] / simulations,
                    semi_final=counts[team]["semi_final"] / simulations,
                    final=counts[team]["final"] / simulations,
                    champion=counts[team]["champion"] / simulations,
                )
                for team in teams
            ],
            key=lambda item: (item.champion, item.final, item.top_8),
            reverse=True,
        )

    def _group_map(self, teams: list[str]) -> dict[str, str]:
        group_map = {}
        for team in teams:
            context = self.contexts.get(team)
            if context and context.group:
                group_map[team] = context.group
        if len(group_map) == len(teams):
            return group_map
        raise ValueError("Tournament simulation requires group names in team context data.")

    def _simulate_group_stage(
        self, fixtures: list[Fixture], group_map: dict[str, str]
    ) -> list[str]:
        tables: dict[str, dict[str, TableRow]] = defaultdict(dict)
        for team, group in group_map.items():
            tables[group][team] = TableRow(team=team)

        for fixture in fixtures:
            if not _is_group_stage(fixture):
                continue
            goals_a, goals_b = self._match_score(fixture)
            self._apply_result(tables[group_map[fixture.team_a]], fixture.team_a, fixture.team_b, goals_a, goals_b)

        ranked_groups = {group: self._rank_rows(rows.values()) for group, rows in tables.items()}
        qualifiers = []
        third_place = []
        for rows in ranked_groups.values():
            qualifiers.extend([rows[0].team, rows[1].team])
            third_place.append(rows[2])

        qualifiers.extend(row.team for row in self._rank_rows(third_place)[:8])
        return self._seed_qualifiers(qualifiers, ranked_groups)

    def _match_score(self, fixture: Fixture) -> tuple[int, int]:
        if (
            fixture.status_short in COMPLETED_STATUSES
            and fixture.goals_a is not None
            and fixture.goals_b is not None
        ):
            return fixture.goals_a, fixture.goals_b

        team_a_win, draw_probability, team_b_win = self._fixture_probabilities(fixture)
        draw = self.random.random()
        if draw < team_a_win:
            margin = 2 if team_a_win > 0.72 and self.random.random() < 0.35 else 1
            return margin, 0
        if draw < team_a_win + draw_probability:
            score = 1 if self.random.random() < 0.45 else 0
            return score, score
        margin = 2 if team_b_win > 0.72 and self.random.random() < 0.35 else 1
        return 0, margin

    def _play_knockout_round(self, teams: list[str], stage: str) -> list[str]:
        winners = []
        for index in range(0, len(teams), 2):
            team_a = teams[index]
            team_b = teams[index + 1]
            team_a_advance = self._advance_probability(team_a, team_b, stage)
            winners.append(team_a if self.random.random() < team_a_advance else team_b)
        return winners

    def _fixture_probabilities(self, fixture: Fixture) -> tuple[float, float, float]:
        cached = self._fixture_probability_cache.get(fixture.match_id)
        if cached is not None:
            return cached
        forecast = self.calibrator.forecast(fixture, self.ratings, self.contexts)
        probabilities = (forecast.team_a_win, forecast.draw, forecast.team_b_win)
        self._fixture_probability_cache[fixture.match_id] = probabilities
        return probabilities

    def _advance_probability(self, team_a: str, team_b: str, stage: str) -> float:
        key = (team_a, team_b, stage)
        cached = self._advance_probability_cache.get(key)
        if cached is not None:
            return cached

        fixture = Fixture(
            match_id=f"sim-{stage}-{team_a}-{team_b}",
            kickoff_utc=_dummy_kickoff(),
            team_a=team_a,
            team_b=team_b,
            stage=stage,
        )
        forecast = self.calibrator.forecast(fixture, self.ratings, self.contexts)
        probability = forecast.team_a_win + forecast.draw * forecast.fair_team_a_no_draw
        self._advance_probability_cache[key] = probability
        return probability

    @staticmethod
    def _apply_result(
        rows: dict[str, TableRow], team_a: str, team_b: str, goals_a: int, goals_b: int
    ) -> None:
        row_a = rows[team_a]
        row_b = rows[team_b]
        row_a.played += 1
        row_b.played += 1
        row_a.goals_for += goals_a
        row_a.goals_against += goals_b
        row_b.goals_for += goals_b
        row_b.goals_against += goals_a

        if goals_a > goals_b:
            row_a.points += 3
            row_a.wins += 1
            row_b.losses += 1
        elif goals_b > goals_a:
            row_b.points += 3
            row_b.wins += 1
            row_a.losses += 1
        else:
            row_a.points += 1
            row_b.points += 1
            row_a.draws += 1
            row_b.draws += 1

    def _rank_rows(self, rows: Iterable[TableRow]) -> list[TableRow]:
        row_list = list(rows)
        self.random.shuffle(row_list)
        return sorted(
            row_list,
            key=lambda row: (row.points, row.goal_diff, row.goals_for, row.wins),
            reverse=True,
        )

    def _seed_qualifiers(
        self, qualifiers: list[str], ranked_groups: dict[str, list[TableRow]]
    ) -> list[str]:
        rank_lookup = {}
        for rows in ranked_groups.values():
            for rank, row in enumerate(rows, start=1):
                rank_lookup[row.team] = rank
        seeded = sorted(
            qualifiers,
            key=lambda team: (
                rank_lookup.get(team, 9),
                -self.ratings.get(team).elo,
                team,
            ),
        )
        return _balanced_bracket_order(seeded)


def summarize_stage_probabilities(
    probabilities: list[TeamStageProbability], limit: int = 12
) -> str:
    lines = [
        "Tournament advancement probabilities",
        "Bracket method: seeded approximation until official knockout slot mapping is added.",
    ]

    quarter_finalists = sorted(probabilities, key=lambda item: item.top_8, reverse=True)[:8]
    semi_finalists = sorted(probabilities, key=lambda item: item.semi_final, reverse=True)[:4]
    finalists = sorted(probabilities, key=lambda item: item.final, reverse=True)[:2]

    lines.append("")
    lines.append("Quarter-finals - highest top-8 probability")
    for item in quarter_finalists:
        lines.append(f"- {item.team}: {item.top_8:.1%}")

    lines.append("")
    lines.append("Semi-finals - highest semi-final probability")
    for item in semi_finalists:
        lines.append(f"- {item.team}: {item.semi_final:.1%}")

    lines.append("")
    lines.append("Final - highest final probability")
    for item in finalists:
        lines.append(
            f"- {item.team}: final {item.final:.1%}, champion {item.champion:.1%}"
        )
    return "\n".join(lines)


def _balanced_bracket_order(seeded: list[str]) -> list[str]:
    if len(seeded) != 32:
        raise ValueError(f"Expected 32 qualifiers, got {len(seeded)}.")
    seed_pairs = [
        (1, 32),
        (16, 17),
        (8, 25),
        (9, 24),
        (4, 29),
        (13, 20),
        (5, 28),
        (12, 21),
        (2, 31),
        (15, 18),
        (7, 26),
        (10, 23),
        (3, 30),
        (14, 19),
        (6, 27),
        (11, 22),
    ]
    ordered = []
    for seed_a, seed_b in seed_pairs:
        ordered.extend([seeded[seed_a - 1], seeded[seed_b - 1]])
    return ordered


def _dummy_kickoff():
    from datetime import UTC, datetime

    return datetime(2026, 7, 1, tzinfo=UTC)


def _is_group_stage(fixture: Fixture) -> bool:
    return "group" in fixture.stage.lower()
