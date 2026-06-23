from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import re

from fifa_arb_agent.models import (
    Edge,
    Fixture,
    MatchForecast,
    PolymarketMarket,
    StageEdge,
    TeamStageProbability,
)
from fifa_arb_agent.polymarket import extract_stage_market_team, match_team_outcome, match_yes_outcome


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


def build_report(
    forecasts: list[MatchForecast],
    market_map: dict[str, list[PolymarketMarket]],
    edge_map: dict[str, list[Edge]],
    timezone: str,
    alerts_only: bool = False,
) -> str:
    tz = ZoneInfo(timezone)
    now_local = datetime.now(UTC).astimezone(tz)
    lines = [
        f"FIFA 2026 probability scan - {now_local:%Y-%m-%d %H:%M %Z}",
        "",
    ]

    filtered_forecasts = [
        forecast for forecast in forecasts if not alerts_only or edge_map.get(forecast.fixture.match_id)
    ]

    if not filtered_forecasts:
        if alerts_only:
            lines.append("No probability arbitrage alerts above threshold.")
            return "\n".join(lines)
        lines.append("No upcoming fixtures in the configured lookahead window.")
        return "\n".join(lines)

    total_edges = sum(len(items) for items in edge_map.values())
    lines.append(f"Fixtures scanned: {len(forecasts)}")
    lines.append(f"Probability edges flagged: {total_edges}")
    lines.append("")

    for forecast in filtered_forecasts:
        fixture = forecast.fixture
        local_kickoff = fixture.kickoff_utc.astimezone(tz)
        markets = market_map.get(fixture.match_id, [])
        edges = edge_map.get(fixture.match_id, [])

        lines.append(f"{fixture.team_a} vs {fixture.team_b}")
        lines.append(f"Kickoff: {local_kickoff:%Y-%m-%d %H:%M %Z} | Stage: {fixture.stage}")
        lines.append(
            "Model: "
            f"{fixture.team_a} {forecast.team_a_win:.1%}, "
            f"Draw {forecast.draw:.1%}, "
            f"{fixture.team_b} {forecast.team_b_win:.1%}"
        )
        lines.append(f"Markets matched: {len(markets)}")

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

        lines.append(f"Notes: {', '.join(forecast.model_notes)}")
        lines.append("")

    lines.append("Research alert only. Check wording, liquidity, spread, fees, and legal access before action.")
    return "\n".join(lines).strip()


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
) -> str:
    sections = []
    match_edge_count = sum(len(items) for items in edge_map.values())
    if match_edge_count:
        sections.append(build_report(forecasts, market_map, edge_map, timezone, alerts_only=True))
    if stage_edges:
        sections.append(build_stage_edge_report(stage_edges, timezone))
    if not sections:
        return build_stage_edge_report([], timezone)
    return "\n\n".join(sections)


def fixture_label(fixture: Fixture) -> str:
    return f"{fixture.team_a} vs {fixture.team_b}"


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
