from __future__ import annotations

from fifa_arb_agent.models import (
    ComboLeg,
    Fixture,
    MatchComboRecommendation,
    MatchForecast,
    PolymarketMarket,
)
from fifa_arb_agent.polymarket import (
    extract_prop_market_specs,
    match_team_outcome,
)
from fifa_arb_agent.score_model import ScoreGrid, build_score_grid


def build_combo_recommendation(
    forecast: MatchForecast, markets: list[PolymarketMarket]
) -> MatchComboRecommendation:
    score_grid = build_score_grid(forecast)
    favorite_side, favorite_team, favorite_win = _favorite(forecast)

    safety = _safety_handicap_leg(forecast, score_grid, markets)
    direction = _direction_leg(forecast, markets, favorite_team, favorite_win)
    upside = _upside_handicap_leg(forecast.fixture, score_grid, markets, favorite_side, favorite_team)

    if favorite_win >= 0.72:
        weights = {"safety": 0.45, "direction": 0.35, "upside": 0.20}
        profile = "favorite-weighted"
    elif favorite_win <= 0.55:
        weights = {"safety": 0.60, "direction": 0.25, "upside": 0.15}
        profile = "defensive-balanced"
    else:
        weights = {"safety": 0.50, "direction": 0.35, "upside": 0.15}
        profile = "balanced"

    legs = [
        safety.model_copy(update={"stake_weight": weights["safety"]}),
        direction.model_copy(update={"stake_weight": weights["direction"]}),
        upside.model_copy(update={"stake_weight": weights["upside"]}),
    ]
    return MatchComboRecommendation(
        fixture=forecast.fixture,
        profile=profile,
        legs=legs,
        note="Use only when market price is below model fair price; weights are a research mix.",
    )


def _favorite(forecast: MatchForecast) -> tuple[str, str, float]:
    if forecast.team_a_win >= forecast.team_b_win:
        return "team_a", forecast.fixture.team_a, forecast.team_a_win
    return "team_b", forecast.fixture.team_b, forecast.team_b_win


def _safety_handicap_leg(
    forecast: MatchForecast, score_grid: ScoreGrid, markets: list[PolymarketMarket]
) -> ComboLeg:
    fixture = forecast.fixture
    candidates = []
    for side, team in (("team_a", fixture.team_a), ("team_b", fixture.team_b)):
        for line in (1.5, 2.5):
            probability = score_grid.price_handicap(side, line)
            candidates.append((abs(probability - 0.78), probability, side, team, line))
    _, probability, side, team, line = min(candidates, key=lambda item: (item[0], -item[1]))
    return _with_market_price(
        ComboLeg(
            role="safety",
            market_type="handicap",
            label=f"{team} {line:+g}",
            model_probability=probability,
            stake_weight=0.0,
        ),
        markets,
        fixture=fixture,
        side=side,
        line=line,
    )


def _direction_leg(
    forecast: MatchForecast,
    markets: list[PolymarketMarket],
    favorite_team: str,
    favorite_win: float,
) -> ComboLeg:
    leg = ComboLeg(
        role="direction",
        market_type="1x2",
        label=f"{favorite_team} 1X2",
        model_probability=favorite_win,
        stake_weight=0.0,
    )
    market_probability = _match_1x2_market_price(markets, forecast.fixture, favorite_team)
    if market_probability is None:
        return leg
    return leg.model_copy(
        update={"market_probability": market_probability, "edge": favorite_win - market_probability}
    )


def _upside_handicap_leg(
    fixture: Fixture,
    score_grid: ScoreGrid,
    markets: list[PolymarketMarket],
    favorite_side: str,
    favorite_team: str,
) -> ComboLeg:
    candidates = []
    for line in (-1.5, -2.5):
        probability = score_grid.price_handicap(favorite_side, line)
        candidates.append((abs(probability - 0.34), probability, line))
    _, probability, line = min(candidates, key=lambda item: (item[0], -item[1]))
    return _with_market_price(
        ComboLeg(
            role="upside",
            market_type="handicap",
            label=f"{favorite_team} {line:+g}",
            model_probability=probability,
            stake_weight=0.0,
        ),
        markets,
        fixture=fixture,
        side=favorite_side,
        line=line,
    )


def _with_market_price(
    leg: ComboLeg, markets: list[PolymarketMarket], fixture: Fixture, side: str, line: float
) -> ComboLeg:
    market_probability = _match_handicap_market_price(markets, fixture, side, line)
    if market_probability is None:
        return leg
    return leg.model_copy(
        update={
            "market_probability": market_probability,
            "edge": leg.model_probability - market_probability,
        }
    )


def _match_1x2_market_price(
    markets: list[PolymarketMarket], fixture: Fixture, team: str
) -> float | None:
    for market in markets:
        if extract_prop_market_specs(market, fixture):
            continue
        outcome = match_team_outcome(market, team)
        if outcome is not None and outcome.price is not None:
            return outcome.price
    return None


def _match_handicap_market_price(
    markets: list[PolymarketMarket], fixture: Fixture, side: str, line: float
) -> float | None:
    for market in markets:
        for spec in extract_prop_market_specs(market, fixture):
            if spec.market_type == "handicap" and spec.side == side and abs(spec.line - line) < 0.001:
                return spec.outcome.price
    return None
