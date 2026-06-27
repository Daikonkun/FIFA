from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fifa_arb_agent.models import Fixture, MatchComboRecommendation, MatchForecast, PolymarketMarket
from fifa_arb_agent.recommendations import build_combo_recommendation
from fifa_arb_agent.report import find_edges, find_prop_edges


EDGE_BUCKETS = (
    ("0-5%", 0.0, 0.05),
    ("5-10%", 0.05, 0.10),
    ("10-15%", 0.10, 0.15),
    ("15%+", 0.15, float("inf")),
)


@dataclass
class LegStats:
    count: int = 0
    hits: int = 0
    profit: float = 0.0
    edge_total: float = 0.0

    def add(self, hit: bool, market_probability: float | None, edge: float | None) -> None:
        self.count += 1
        self.hits += int(hit)
        if edge is not None:
            self.edge_total += edge
        if market_probability is not None and 0 < market_probability < 1:
            self.profit += (1 / market_probability - 1) if hit else -1

    @property
    def hit_rate(self) -> float:
        return self.hits / self.count if self.count else 0.0

    @property
    def average_edge(self) -> float:
        return self.edge_total / self.count if self.count else 0.0


@dataclass
class EvaluationResult:
    scans_loaded: int = 0
    forecast_rows_loaded: int = 0
    settled_pre_match_forecasts: int = 0
    top_pick_hits: int = 0
    non_draw_rows: int = 0
    non_draw_side_hits: int = 0
    brier_total: float = 0.0
    logloss_total: float = 0.0
    one_x_two_alerts: LegStats = field(default_factory=LegStats)
    handicap_alerts: LegStats = field(default_factory=LegStats)
    combo_roles: dict[str, LegStats] = field(default_factory=lambda: defaultdict(LegStats))
    edge_buckets: dict[str, LegStats] = field(default_factory=lambda: defaultdict(LegStats))

    def render(self) -> str:
        total = self.settled_pre_match_forecasts
        lines = [
            "Historical model evaluation",
            "Scope: stored pre-kickoff scan snapshots joined to latest completed scores.",
            f"Scans loaded: {self.scans_loaded}",
            f"Forecast rows loaded: {self.forecast_rows_loaded}",
            f"Settled pre-match forecasts: {total}",
        ]
        if not total:
            return "\n".join(lines)

        lines.extend(
            [
                f"1X2 top-pick accuracy: {self.top_pick_hits}/{total} ({self.top_pick_hits / total:.1%})",
                (
                    "Non-draw side accuracy: "
                    f"{self.non_draw_side_hits}/{self.non_draw_rows} "
                    f"({_safe_rate(self.non_draw_side_hits, self.non_draw_rows):.1%})"
                ),
                f"Brier score: {self.brier_total / total:.3f}",
                f"Log loss: {self.logloss_total / total:.3f}",
                "",
                "Alert legs at configured edge threshold",
                f"- 1X2: {_format_leg_stats(self.one_x_two_alerts)}",
                f"- Handicap: {_format_leg_stats(self.handicap_alerts)}",
                "",
                "Combo active legs",
            ]
        )
        for role in ("safety", "direction", "upside"):
            lines.append(f"- {role}: {_format_leg_stats(self.combo_roles[role])}")

        lines.append("")
        lines.append("Positive-edge buckets")
        for label, _, _ in EDGE_BUCKETS:
            lines.append(f"- {label}: {_format_leg_stats(self.edge_buckets[label])}")
        return "\n".join(lines)


def evaluate_stored_scans(
    database_path: Path,
    fixtures_path: Path,
    edge_threshold: float = 0.15,
) -> EvaluationResult:
    fixtures = _load_completed_fixtures(fixtures_path)
    result = EvaluationResult()

    with sqlite3.connect(database_path) as conn:
        scan_rows = conn.execute("SELECT id, created_at FROM scans ORDER BY id").fetchall()
        result.scans_loaded = len(scan_rows)
        created_at_by_scan = {scan_id: _parse_datetime(created_at) for scan_id, created_at in scan_rows}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(scan_items)")}
        combo_expr = "combo_json" if "combo_json" in columns else "NULL AS combo_json"
        item_rows = conn.execute(
            f"""
            SELECT scan_id, match_id, forecast_json, markets_json, {combo_expr}
            FROM scan_items
            ORDER BY scan_id, match_id
            """
        ).fetchall()

    result.forecast_rows_loaded = len(item_rows)
    seen_matches: set[tuple[int, str]] = set()
    for scan_id, match_id, forecast_json, markets_json, combo_json in item_rows:
        scan_created_at = created_at_by_scan.get(scan_id)
        completed_fixture = fixtures.get(match_id)
        if scan_created_at is None or completed_fixture is None:
            continue
        if scan_created_at >= completed_fixture.kickoff_utc:
            continue
        row_key = (scan_id, match_id)
        if row_key in seen_matches:
            continue
        seen_matches.add(row_key)

        forecast = MatchForecast.model_validate_json(forecast_json)
        markets = [
            PolymarketMarket.model_validate(item)
            for item in json.loads(markets_json or "[]")
        ]
        forecast = forecast.model_copy(update={"fixture": completed_fixture})
        result.settled_pre_match_forecasts += 1
        _score_forecast_accuracy(result, forecast)
        _score_alert_edges(result, forecast, markets, edge_threshold)
        combo = _load_combo(combo_json, forecast, markets)
        _score_combo(result, combo, completed_fixture)

    return result


def _score_forecast_accuracy(result: EvaluationResult, forecast: MatchForecast) -> None:
    actual = _actual_result(forecast.fixture)
    probabilities = {
        "team_a": forecast.team_a_win,
        "draw": forecast.draw,
        "team_b": forecast.team_b_win,
    }
    top_pick = max(probabilities, key=probabilities.get)
    side_pick = "team_a" if forecast.team_a_win >= forecast.team_b_win else "team_b"
    result.top_pick_hits += int(top_pick == actual)
    if actual != "draw":
        result.non_draw_rows += 1
        result.non_draw_side_hits += int(side_pick == actual)
    result.brier_total += sum(
        (probability - (1.0 if outcome == actual else 0.0)) ** 2
        for outcome, probability in probabilities.items()
    )
    result.logloss_total += -math.log(max(probabilities[actual], 1e-12))


def _score_alert_edges(
    result: EvaluationResult,
    forecast: MatchForecast,
    markets: list[PolymarketMarket],
    edge_threshold: float,
) -> None:
    for edge in find_edges(forecast, markets, 0.0, 0.0):
        hit = _actual_result(forecast.fixture) == edge.side
        _score_bucket(result, hit, edge.market_probability, edge.edge)
        if edge.edge >= edge_threshold:
            result.one_x_two_alerts.add(hit, edge.market_probability, edge.edge)

    for edge in find_prop_edges(forecast, markets, 0.0, 0.0):
        if edge.market_type != "handicap":
            continue
        hit = _handicap_hit(forecast.fixture, edge.label)
        if hit is None:
            continue
        _score_bucket(result, hit, edge.market_probability, edge.edge)
        if edge.edge >= edge_threshold:
            result.handicap_alerts.add(hit, edge.market_probability, edge.edge)


def _score_combo(
    result: EvaluationResult,
    combo: MatchComboRecommendation,
    fixture: Fixture,
) -> None:
    for leg in combo.legs:
        if leg.stake_weight <= 0:
            continue
        if leg.market_type == "1x2":
            team = leg.label.removesuffix(" 1X2")
            hit = _team_won(fixture, team)
        else:
            hit = _handicap_hit(fixture, leg.label)
        if hit is None:
            continue
        result.combo_roles[leg.role].add(hit, leg.market_probability, leg.edge)


def _score_bucket(
    result: EvaluationResult,
    hit: bool,
    market_probability: float | None,
    edge: float,
) -> None:
    for label, low, high in EDGE_BUCKETS:
        if low <= edge < high:
            result.edge_buckets[label].add(hit, market_probability, edge)
            return


def _load_combo(
    combo_json: str | None,
    forecast: MatchForecast,
    markets: list[PolymarketMarket],
) -> MatchComboRecommendation:
    if combo_json:
        try:
            return MatchComboRecommendation.model_validate_json(combo_json)
        except ValueError:
            pass
    return build_combo_recommendation(forecast, markets)


def _load_completed_fixtures(path: Path) -> dict[str, Fixture]:
    payload = json.loads(path.read_text())
    fixtures = {}
    for item in payload:
        fixture = Fixture.model_validate(item)
        if fixture.goals_a is not None and fixture.goals_b is not None:
            fixtures[fixture.match_id] = fixture
    return fixtures


def _actual_result(fixture: Fixture) -> str:
    if fixture.goals_a is None or fixture.goals_b is None:
        raise ValueError("Completed fixture requires goals.")
    if fixture.goals_a > fixture.goals_b:
        return "team_a"
    if fixture.goals_b > fixture.goals_a:
        return "team_b"
    return "draw"


def _team_won(fixture: Fixture, team: str) -> bool | None:
    actual = _actual_result(fixture)
    if _norm(team) == _norm(fixture.team_a):
        return actual == "team_a"
    if _norm(team) == _norm(fixture.team_b):
        return actual == "team_b"
    return None


def _handicap_hit(fixture: Fixture, label: str) -> bool | None:
    if fixture.goals_a is None or fixture.goals_b is None:
        return None
    line_match = re.search(r"([+-]\d+(?:\.\d+)?)$", label.strip())
    if not line_match:
        return None
    line = float(line_match.group(1))
    team = label[: line_match.start()].strip()
    if _norm(team) == _norm(fixture.team_a):
        return fixture.goals_a + line > fixture.goals_b
    if _norm(team) == _norm(fixture.team_b):
        return fixture.goals_b + line > fixture.goals_a
    return None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_leg_stats(stats: LegStats) -> str:
    if stats.count == 0:
        return "0 legs"
    return (
        f"{stats.hits}/{stats.count} hit ({stats.hit_rate:.1%}), "
        f"avg edge {stats.average_edge:.1%}, unit ROI {stats.profit / stats.count:+.2f}"
    )


def _safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
