from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import math
import re

from fifa_arb_agent.models import (
    Edge,
    Fixture,
    MarketOutcome,
    MatchForecast,
    PolymarketMarket,
    PropEdge,
    StageEdge,
    TeamStageProbability,
)
from fifa_arb_agent.polymarket import (
    PropMarketSpec,
    extract_prop_market_specs,
    extract_stage_market_team,
    match_team_outcome,
    match_yes_outcome,
)
from fifa_arb_agent.recommendations import build_combo_recommendation
from fifa_arb_agent.score_model import ScoreGrid, build_score_grid


STAGE_ATTRS = {
    "quarterfinals": "top_8",
    "semifinals": "semi_final",
    "final": "final",
    "winner": "champion",
}


def find_edges(
    forecast: MatchForecast,
    markets: list[PolymarketMarket],
    threshold: float,
    min_market_liquidity: float,
) -> list[Edge]:
    edges: list[Edge] = []
    fixture = forecast.fixture

    for market in markets:
        if market.liquidity is not None and market.liquidity < min_market_liquidity:
            continue
        if extract_prop_market_specs(market, fixture):
            continue

        for side, team, model_prob in (
            ("team_a", fixture.team_a, forecast.team_a_win),
            ("team_b", fixture.team_b, forecast.team_b_win),
        ):
            outcome = match_team_outcome(market, team)
            if outcome is None or outcome.price is None:
                continue
            edge = model_prob - outcome.price
            if _passes_threshold(edge, threshold):
                edges.append(
                    Edge(
                        side=side,
                        team=team,
                        model_probability=model_prob,
                        market_probability=outcome.price,
                        edge=edge,
                        market=market,
                        matched_outcome=outcome,
                    )
                )

    return sorted(edges, key=lambda item: item.edge, reverse=True)


def find_stage_edges(
    probabilities: list[TeamStageProbability],
    stage_markets: dict[str, list[PolymarketMarket]],
    threshold: float,
    min_market_liquidity: float,
) -> list[StageEdge]:
    probability_map = {_norm_team(item.team): item for item in probabilities}
    edges: list[StageEdge] = []

    for stage, markets in stage_markets.items():
        probability_attr = STAGE_ATTRS[stage]
        for market in markets:
            if market.liquidity is not None and market.liquidity < min_market_liquidity:
                continue
            market_team = extract_stage_market_team(market)
            if not market_team:
                continue
            probability = probability_map.get(_norm_team(market_team))
            if probability is None:
                continue
            outcome = match_yes_outcome(market)
            if outcome is None or outcome.price is None:
                continue
            model_probability = float(getattr(probability, probability_attr))
            edge = model_probability - outcome.price
            if _passes_threshold(edge, threshold):
                edges.append(
                    StageEdge(
                        stage=stage,
                        team=probability.team,
                        model_probability=model_probability,
                        market_probability=outcome.price,
                        edge=edge,
                        market=market,
                        matched_outcome=outcome,
                    )
                )

    return sorted(edges, key=lambda item: item.edge, reverse=True)


def find_prop_edges(
    forecast: MatchForecast,
    markets: list[PolymarketMarket],
    threshold: float,
    min_market_liquidity: float,
) -> list[PropEdge]:
    edges: list[PropEdge] = []
    if not markets:
        return edges
    score_grid: ScoreGrid | None = None
    for market in markets:
        if market.liquidity is not None and market.liquidity < min_market_liquidity:
            continue
        for spec in extract_prop_market_specs(market, forecast.fixture):
            if spec.outcome.price is None:
                continue
            if score_grid is None:
                score_grid = build_score_grid(forecast)
            model_probability = _price_prop_spec(score_grid, spec)
            edge = model_probability - spec.outcome.price
            if _passes_threshold(edge, threshold):
                edges.append(
                    PropEdge(
                        market_type=spec.market_type,
                        label=spec.label,
                        model_probability=model_probability,
                        market_probability=spec.outcome.price,
                        edge=edge,
                        market=market,
                        matched_outcome=spec.outcome,
                    )
                )
    return sorted(edges, key=lambda item: item.edge, reverse=True)


def build_report(
    forecasts: list[MatchForecast],
    market_map: dict[str, list[PolymarketMarket]],
    edge_map: dict[str, list[Edge]],
    timezone: str,
    alerts_only: bool = False,
    prop_edge_map: dict[str, list[PropEdge]] | None = None,
) -> str:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(UTC).astimezone(tz)
    lines = [
        f"FIFA 2026 probability scan - {now_local:%Y-%m-%d %H:%M %Z}",
        "",
    ]

    filtered_forecasts = [
        forecast
        for forecast in forecasts
        if not alerts_only
        or edge_map.get(forecast.fixture.match_id)
        or (prop_edge_map or {}).get(forecast.fixture.match_id)
    ]

    if not filtered_forecasts:
        if alerts_only:
            lines.append("No probability arbitrage alerts above threshold.")
            return "\n".join(lines)
        lines.append("No upcoming fixtures in the configured lookahead window.")
        return "\n".join(lines)

    prop_edge_map = prop_edge_map or {}
    total_edges = sum(len(items) for items in edge_map.values()) + sum(
        len(items) for items in prop_edge_map.values()
    )
    lines.append(f"Fixtures scanned: {len(forecasts)}")
    lines.append(f"Probability edges flagged: {total_edges}")
    lines.append("Upcoming match predictions:")
    lines.append("")

    for forecast in filtered_forecasts:
        fixture = forecast.fixture
        local_kickoff = fixture.kickoff_utc.astimezone(tz)
        markets = market_map.get(fixture.match_id, [])
        edges = edge_map.get(fixture.match_id, [])
        prop_edges = prop_edge_map.get(fixture.match_id, [])

        lines.append(f"{fixture.team_a} vs {fixture.team_b}")
        lines.append(f"Kickoff: {local_kickoff:%Y-%m-%d %H:%M %Z} | Stage: {fixture.stage}")
        lines.append(
            "Model: "
            f"{fixture.team_a} {forecast.team_a_win:.1%}, "
            f"Draw {forecast.draw:.1%}, "
            f"{fixture.team_b} {forecast.team_b_win:.1%}"
        )
        lines.append(
            "No-draw fair: "
            f"{fixture.team_a} {forecast.fair_team_a_no_draw:.1%}, "
            f"{fixture.team_b} {forecast.fair_team_b_no_draw:.1%}"
        )
        lines.append(f"Markets matched: {len(markets)}")
        if not alerts_only:
            market_deviation_lines = _market_deviation_lines(forecast, markets)
            if market_deviation_lines:
                lines.append("Market deviations:")
                lines.extend(market_deviation_lines)
            else:
                lines.append("Market deviations: none matched")
            prop_deviation_lines = _prop_deviation_lines(forecast, markets)
            if prop_deviation_lines:
                lines.append("Handicap/total deviations:")
                lines.extend(prop_deviation_lines)
            else:
                lines.append("Handicap/total deviations: none matched")
            lines.append("Balanced combo:")
            lines.extend(_combo_recommendation_lines(forecast, markets))

        if edges:
            lines.append("Alerts:")
            for edge in edges[:3]:
                url = f" | {edge.market.url}" if edge.market.url else ""
                lines.append(
                    f"- {edge.team}: model {edge.model_probability:.1%} vs market "
                    f"{edge.market_probability:.1%}; edge {edge.edge:.1%}{url}"
                )
        elif not alerts_only:
            lines.append("Alerts: none above threshold")

        if prop_edges:
            lines.append("Handicap/total alerts:")
            for edge in prop_edges[:3]:
                url = f" | {edge.market.url}" if edge.market.url else ""
                lines.append(
                    f"- {edge.label}: model {edge.model_probability:.1%} vs market "
                    f"{edge.market_probability:.1%}; edge {edge.edge:.1%}{url}"
                )
        elif not alerts_only:
            lines.append("Handicap/total alerts: none above threshold")

        lines.append(f"Notes: {', '.join(forecast.model_notes)}")
        lines.append("")

    lines.append("Research alert only. Check wording, liquidity, spread, fees, and legal access before action.")
    return "\n".join(lines).strip()


def build_backtest_report(forecasts: list[MatchForecast], timezone: str) -> str:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(UTC).astimezone(tz)
    completed = [
        forecast
        for forecast in forecasts
        if forecast.fixture.goals_a is not None and forecast.fixture.goals_b is not None
    ]
    lines = [
        f"Rolling backtest - {now_local:%Y-%m-%d %H:%M %Z}",
        "Scope: completed fixtures scored with current model inputs, not historical pre-kickoff snapshots.",
    ]

    if not completed:
        lines.append("Completed fixtures tested: 0")
        return "\n".join(lines)

    rows = [_score_completed_forecast(forecast) for forecast in completed]
    total = len(rows)
    top_pick_hits = sum(row["top_pick_hit"] for row in rows)
    non_draw_rows = [row for row in rows if row["actual"] != "draw"]
    non_draw_side_hits = sum(row["side_hit"] for row in non_draw_rows)
    draw_rows = [row for row in rows if row["actual"] == "draw"]
    draw_hits = sum(row["top_pick_hit"] for row in draw_rows)
    avg_brier = sum(row["brier"] for row in rows) / total
    avg_logloss = sum(row["logloss"] for row in rows) / total

    lines.extend(
        [
            f"Completed fixtures tested: {total}",
            f"1X2 top-pick accuracy: {top_pick_hits}/{total} ({top_pick_hits / total:.1%})",
            (
                "Non-draw side accuracy: "
                f"{non_draw_side_hits}/{len(non_draw_rows)} "
                f"({_safe_rate(non_draw_side_hits, len(non_draw_rows)):.1%})"
            ),
            f"Draw top-pick hits: {draw_hits}/{len(draw_rows)} ({_safe_rate(draw_hits, len(draw_rows)):.1%})",
            f"Brier score: {avg_brier:.3f}",
            f"Log loss: {avg_logloss:.3f}",
        ]
    )
    return "\n".join(lines)


def build_stage_edge_report(stage_edges: list[StageEdge], timezone: str) -> str:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(UTC).astimezone(tz)
    lines = [
        f"FIFA 2026 stage-market scan - {now_local:%Y-%m-%d %H:%M %Z}",
        f"Stage probability edges flagged: {len(stage_edges)}",
        "",
    ]
    if not stage_edges:
        lines.append("No stage-market probability arbitrage alerts above threshold.")
        return "\n".join(lines)

    for edge in stage_edges:
        url = f" | {edge.market.url}" if edge.market.url else ""
        lines.append(
            f"- {edge.stage} / {edge.team}: model {edge.model_probability:.1%} vs "
            f"market {edge.market_probability:.1%}; edge {edge.edge:.1%}{url}"
        )
    lines.append("")
    lines.append("Research alert only. Check wording, liquidity, spread, fees, and legal access before action.")
    return "\n".join(lines).strip()


def build_combined_alert_report(
    forecasts: list[MatchForecast],
    market_map: dict[str, list[PolymarketMarket]],
    edge_map: dict[str, list[Edge]],
    stage_edges: list[StageEdge],
    timezone: str,
    prop_edge_map: dict[str, list[PropEdge]] | None = None,
) -> str:
    sections = []
    match_edge_count = sum(len(items) for items in edge_map.values())
    prop_edge_map = prop_edge_map or {}
    prop_edge_count = sum(len(items) for items in prop_edge_map.values())
    if match_edge_count or prop_edge_count:
        sections.append(
            build_report(
                forecasts,
                market_map,
                edge_map,
                timezone,
                alerts_only=True,
                prop_edge_map=prop_edge_map,
            )
        )
    if stage_edges:
        sections.append(build_stage_edge_report(stage_edges, timezone))
    if not sections:
        return build_stage_edge_report([], timezone)
    return "\n\n".join(sections)


def build_upcoming_prediction_report(
    forecasts: list[MatchForecast],
    market_map: dict[str, list[PolymarketMarket]],
    timezone: str,
) -> str:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(UTC).astimezone(tz)
    lines = [
        f"FIFA 2026 upcoming predictions - {now_local:%Y-%m-%d %H:%M %Z}",
        f"Upcoming fixtures: {len(forecasts)}",
        "Match observations are not filtered by the arbitrage threshold.",
        "",
    ]
    if not forecasts:
        lines.append("No upcoming fixtures in the configured lookahead window.")
        return "\n".join(lines)

    for forecast in forecasts:
        fixture = forecast.fixture
        local_kickoff = fixture.kickoff_utc.astimezone(tz)
        lines.append(f"{fixture.team_a} vs {fixture.team_b} | {local_kickoff:%m-%d %H:%M %Z}")
        lines.append(
            "Model: "
            f"{fixture.team_a} {forecast.team_a_win:.1%}, "
            f"Draw {forecast.draw:.1%}, "
            f"{fixture.team_b} {forecast.team_b_win:.1%}"
        )
        lines.append(
            "No-draw fair: "
            f"{fixture.team_a} {forecast.fair_team_a_no_draw:.1%}, "
            f"{fixture.team_b} {forecast.fair_team_b_no_draw:.1%}"
        )
        deviation_summary = _market_deviation_summary(forecast, market_map.get(fixture.match_id, []))
        if deviation_summary:
            lines.append(f"Market dev: {', '.join(deviation_summary)}")
        else:
            lines.append("Market dev: none matched")
        prop_summary = _prop_deviation_summary(forecast, market_map.get(fixture.match_id, []))
        if prop_summary:
            lines.append(f"Handicap/total dev: {', '.join(prop_summary)}")
        else:
            lines.append("Handicap/total dev: none matched")
        lines.append(f"Combo: {_combo_recommendation_summary(forecast, market_map.get(fixture.match_id, []))}")
        lines.append("")

    return "\n".join(lines).strip()


def fixture_label(fixture: Fixture) -> str:
    return f"{fixture.team_a} vs {fixture.team_b}"


def _market_deviation_lines(forecast: MatchForecast, markets: list[PolymarketMarket]) -> list[str]:
    fixture = forecast.fixture
    lines: list[str] = []
    for market in markets[:3]:
        if extract_prop_market_specs(market, fixture):
            continue
        for label, model_probability, outcome in (
            (fixture.team_a, forecast.team_a_win, match_team_outcome(market, fixture.team_a)),
            ("Draw", forecast.draw, _match_draw_outcome(market)),
            (fixture.team_b, forecast.team_b_win, match_team_outcome(market, fixture.team_b)),
        ):
            if outcome is None or outcome.price is None:
                continue
            url = f" | {market.url}" if market.url else ""
            lines.append(
                f"- {label}: model {model_probability:.1%} vs market {outcome.price:.1%}; "
                f"deviation {model_probability - outcome.price:+.1%}{url}"
            )
    return lines


def _prop_deviation_lines(forecast: MatchForecast, markets: list[PolymarketMarket]) -> list[str]:
    if not markets:
        return []
    score_grid: ScoreGrid | None = None
    lines: list[str] = []
    for market in markets[:3]:
        for spec in extract_prop_market_specs(market, forecast.fixture):
            if spec.outcome.price is None:
                continue
            if score_grid is None:
                score_grid = build_score_grid(forecast)
            model_probability = _price_prop_spec(score_grid, spec)
            url = f" | {market.url}" if market.url else ""
            lines.append(
                f"- {spec.label}: model {model_probability:.1%} vs market "
                f"{spec.outcome.price:.1%}; deviation {model_probability - spec.outcome.price:+.1%}{url}"
            )
    return lines


def _combo_recommendation_lines(
    forecast: MatchForecast, markets: list[PolymarketMarket]
) -> list[str]:
    combo = build_combo_recommendation(forecast, markets)
    lines = [f"Profile: {combo.profile}"]
    for leg in combo.legs:
        market = ""
        if leg.market_probability is not None and leg.edge is not None:
            market = f", market {leg.market_probability:.1%}, edge {leg.edge:+.1%}"
        lines.append(
            f"- {leg.role.title()} {leg.stake_weight:.0%}: {leg.label} "
            f"model {leg.model_probability:.1%}, fair <= {leg.model_probability:.3f} "
            f"(dec {leg.fair_decimal_odds:.2f}){market}"
        )
    lines.append(f"Note: {combo.note}")
    return lines


def _combo_recommendation_summary(forecast: MatchForecast, markets: list[PolymarketMarket]) -> str:
    combo = build_combo_recommendation(forecast, markets)
    parts = []
    for leg in combo.legs:
        market = ""
        if leg.edge is not None:
            market = f", edge {leg.edge:+.1%}"
        parts.append(f"{leg.role} {leg.stake_weight:.0%} {leg.label} p {leg.model_probability:.1%}{market}")
    return "; ".join(parts)


def _match_draw_outcome(market: PolymarketMarket) -> MarketOutcome | None:
    for outcome in market.outcomes:
        if _norm_team(outcome.name) in {"draw", "tie"}:
            return outcome
    return None


def _market_deviation_summary(
    forecast: MatchForecast, markets: list[PolymarketMarket]
) -> list[str]:
    fixture = forecast.fixture
    summary: list[str] = []
    for market in markets[:1]:
        if extract_prop_market_specs(market, fixture):
            continue
        for label, model_probability, outcome in (
            (fixture.team_a, forecast.team_a_win, match_team_outcome(market, fixture.team_a)),
            ("Draw", forecast.draw, _match_draw_outcome(market)),
            (fixture.team_b, forecast.team_b_win, match_team_outcome(market, fixture.team_b)),
        ):
            if outcome is None or outcome.price is None:
                continue
            summary.append(f"{label} {model_probability - outcome.price:+.1%}")
    return summary


def _prop_deviation_summary(
    forecast: MatchForecast, markets: list[PolymarketMarket]
) -> list[str]:
    if not markets:
        return []
    score_grid: ScoreGrid | None = None
    summary: list[str] = []
    for market in markets[:1]:
        for spec in extract_prop_market_specs(market, forecast.fixture):
            if spec.outcome.price is None:
                continue
            if score_grid is None:
                score_grid = build_score_grid(forecast)
            model_probability = _price_prop_spec(score_grid, spec)
            summary.append(f"{spec.label} {model_probability - spec.outcome.price:+.1%}")
    return summary


def _price_prop_spec(score_grid: ScoreGrid, spec: PropMarketSpec) -> float:
    if spec.market_type == "handicap":
        return score_grid.price_handicap(spec.side, spec.line)
    if spec.market_type == "total_goals":
        return score_grid.price_total_goals(spec.line, spec.side)
    raise ValueError(f"Unsupported prop market type: {spec.market_type}")


def _score_completed_forecast(forecast: MatchForecast) -> dict[str, float | bool | str]:
    fixture = forecast.fixture
    probabilities = {
        "team_a": forecast.team_a_win,
        "draw": forecast.draw,
        "team_b": forecast.team_b_win,
    }
    top_pick = max(probabilities, key=probabilities.get)
    if fixture.goals_a is None or fixture.goals_b is None:
        raise ValueError("Completed forecast scoring requires goals.")
    if fixture.goals_a > fixture.goals_b:
        actual = "team_a"
    elif fixture.goals_b > fixture.goals_a:
        actual = "team_b"
    else:
        actual = "draw"

    side_pick = "team_a" if forecast.team_a_win >= forecast.team_b_win else "team_b"
    return {
        "actual": actual,
        "top_pick_hit": top_pick == actual,
        "side_hit": side_pick == actual,
        "brier": sum(
            (probability - (1.0 if outcome == actual else 0.0)) ** 2
            for outcome, probability in probabilities.items()
        ),
        "logloss": -math.log(max(probabilities[actual], 1e-12)),
    }


def _safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _norm_team(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    aliases = {
        "cape verde": "cape verde islands",
        "usa": "usa",
        "united states": "usa",
    }
    return aliases.get(normalized, normalized)


def _passes_threshold(edge: float, threshold: float) -> bool:
    return edge + 1e-9 >= threshold
