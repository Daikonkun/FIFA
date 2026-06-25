from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from fifa_arb_agent.models import Fixture, MarketOutcome, PolymarketMarket


STAGE_MARKET_SPECS = {
    "quarterfinals": {
        "query": "World Cup 2026 quarter finals",
        "event_title": "World Cup: Nation To Reach Quarterfinals",
        "probability_attr": "top_8",
    },
    "semifinals": {
        "query": "World Cup 2026 semifinals",
        "event_title": "World Cup: Nation To Reach Semifinals",
        "probability_attr": "semi_final",
    },
    "final": {
        "query": "World Cup 2026 final",
        "event_title": "World Cup: Nation to Reach Final",
        "probability_attr": "final",
    },
    "winner": {
        "query": "World Cup 2026 winner",
        "event_title": "World Cup Winner",
        "probability_attr": "champion",
    },
}


@dataclass(frozen=True)
class PropMarketSpec:
    market_type: str
    label: str
    side: str
    line: float
    outcome: MarketOutcome


class PolymarketClient:
    def __init__(
        self,
        gamma_base_url: str,
        clob_base_url: str,
        search_template: str,
        timeout: float = 20.0,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.search_template = search_template
        self.timeout = timeout

    async def find_match_markets(self, fixture: Fixture) -> list[PolymarketMarket]:
        query = self.search_template.format(team_a=fixture.team_a, team_b=fixture.team_b)
        params = {
            "q": query,
            "events_status": "active",
            "limit_per_type": 10,
            "search_profiles": "false",
            "search_tags": "false",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.gamma_base_url}/public-search", params=params)
            response.raise_for_status()
            payload = response.json()

        markets = list(self._markets_from_search(payload))
        return [market for market in markets if _looks_like_supported_match_market(market, fixture)]

    async def enrich_orderbook_prices(self, markets: list[PolymarketMarket]) -> list[PolymarketMarket]:
        token_ids = [
            outcome.token_id
            for market in markets
            for outcome in market.outcomes
            if outcome.token_id is not None
        ]
        if not token_ids:
            return markets

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for token_id in token_ids:
                await self._attach_token_prices(client, markets, token_id)
        return markets

    async def find_stage_markets(self) -> dict[str, list[PolymarketMarket]]:
        stage_markets: dict[str, list[PolymarketMarket]] = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for stage, spec in STAGE_MARKET_SPECS.items():
                response = await client.get(
                    f"{self.gamma_base_url}/public-search",
                    params={
                        "q": spec["query"],
                        "events_status": "active",
                        "limit_per_type": 10,
                        "search_profiles": "false",
                        "search_tags": "false",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                event = _find_event(payload, str(spec["event_title"]))
                markets = []
                if event:
                    for raw_market in event.get("markets") or []:
                        market = _parse_market(
                            raw_market,
                            event_title=event.get("title"),
                            event_slug=event.get("slug"),
                        )
                        if market and _looks_like_supported_stage_market(market, stage):
                            markets.append(market)
                stage_markets[stage] = markets
        return stage_markets

    async def _attach_token_prices(
        self, client: httpx.AsyncClient, markets: list[PolymarketMarket], token_id: str
    ) -> None:
        midpoint: float | None = None
        best_bid: float | None = None
        best_ask: float | None = None

        midpoint_response = await client.get(f"{self.clob_base_url}/midpoint", params={"token_id": token_id})
        if midpoint_response.status_code == 200:
            midpoint_payload = midpoint_response.json()
            midpoint = _float_or_none(midpoint_payload.get("mid") or midpoint_payload.get("midpoint"))

        for side in ("BUY", "SELL"):
            price_response = await client.get(
                f"{self.clob_base_url}/price", params={"token_id": token_id, "side": side}
            )
            if price_response.status_code == 200:
                price = _float_or_none(price_response.json().get("price"))
                if side == "BUY":
                    best_ask = price
                else:
                    best_bid = price

        for outcome in _iter_outcomes(markets):
            if outcome.token_id == token_id:
                outcome.midpoint = midpoint
                outcome.best_bid = best_bid
                outcome.best_ask = best_ask
                outcome.price = midpoint or outcome.price

    def _markets_from_search(self, payload: dict[str, Any]) -> Iterable[PolymarketMarket]:
        for event in payload.get("events") or []:
            event_title = event.get("title")
            event_slug = event.get("slug")
            for raw_market in event.get("markets") or []:
                market = _parse_market(raw_market, event_title=event_title, event_slug=event_slug)
                if market:
                    yield market


def match_team_outcome(market: PolymarketMarket, team: str) -> MarketOutcome | None:
    team_norm = _norm(team)
    yes_candidate: MarketOutcome | None = None

    for outcome in market.outcomes:
        name_norm = _norm(outcome.name)
        if team_norm in name_norm or name_norm in team_norm:
            return outcome
        if name_norm == "yes":
            yes_candidate = outcome

    question_norm = _norm(market.question)
    if yes_candidate and team_norm in question_norm:
        return yes_candidate
    return None


def match_yes_outcome(market: PolymarketMarket) -> MarketOutcome | None:
    for outcome in market.outcomes:
        if _norm(outcome.name) == "yes":
            return outcome
    return market.outcomes[0] if market.outcomes else None


def extract_stage_market_team(market: PolymarketMarket) -> str | None:
    question = market.question
    match = re.search(r"Will (.*?) (?:reach|win)", question, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def extract_prop_market_specs(market: PolymarketMarket, fixture: Fixture) -> list[PropMarketSpec]:
    return _extract_total_specs(market) + _extract_handicap_specs(market, fixture)


def _parse_market(
    raw_market: dict[str, Any], event_title: str | None, event_slug: str | None
) -> PolymarketMarket | None:
    outcomes = _loads_maybe_json(raw_market.get("outcomes")) or []
    prices = _loads_maybe_json(raw_market.get("outcomePrices")) or []
    token_ids = _loads_maybe_json(raw_market.get("clobTokenIds")) or []
    if not isinstance(outcomes, list):
        return None

    parsed_outcomes = []
    for index, outcome in enumerate(outcomes):
        parsed_outcomes.append(
            MarketOutcome(
                name=str(outcome),
                price=_float_from_index(prices, index),
                token_id=_str_from_index(token_ids, index),
            )
        )

    slug = raw_market.get("slug")
    event_path = event_slug or slug
    return PolymarketMarket(
        market_id=str(raw_market.get("id") or raw_market.get("conditionId") or slug),
        question=str(raw_market.get("question") or raw_market.get("title") or ""),
        slug=slug,
        event_slug=event_slug,
        event_title=event_title,
        liquidity=_float_or_none(raw_market.get("liquidityNum") or raw_market.get("liquidity")),
        volume=_float_or_none(raw_market.get("volumeNum") or raw_market.get("volume")),
        outcomes=parsed_outcomes,
        url=f"https://polymarket.com/event/{event_path}" if event_path else None,
    )


def _find_event(payload: dict[str, Any], event_title: str) -> dict[str, Any] | None:
    target = _norm(event_title)
    for event in payload.get("events") or []:
        if _norm(event.get("title") or "") == target:
            return event
    return None


def _looks_like_supported_match_market(market: PolymarketMarket, fixture: Fixture) -> bool:
    text = _norm(" ".join([market.question, market.event_title or "", market.slug or ""]))
    if _norm(fixture.team_a) not in text or _norm(fixture.team_b) not in text:
        return False

    unsupported_terms = (
        "announcer",
        "announce",
        "say",
        "said",
        "mention",
        "mentioned",
        "goal scorer",
        "score a goal",
        "yellow card",
        "red card",
        "corner",
        "penalty awarded",
        "jersey",
        "anthem",
    )
    if any(term in text for term in unsupported_terms):
        return False

    win_terms = (" win", " winner", " beat", " defeat", " advance", " qualify")
    if any(term in f" {text}" for term in win_terms):
        return True
    if extract_prop_market_specs(market, fixture):
        return True

    outcome_text = [_norm(outcome.name) for outcome in market.outcomes]
    has_team_a = any(_norm(fixture.team_a) in outcome or outcome in _norm(fixture.team_a) for outcome in outcome_text)
    has_team_b = any(_norm(fixture.team_b) in outcome or outcome in _norm(fixture.team_b) for outcome in outcome_text)
    has_draw = any(outcome in {"draw", "tie"} for outcome in outcome_text)
    return has_team_a and has_team_b and has_draw


def _looks_like_supported_stage_market(market: PolymarketMarket, stage: str) -> bool:
    text = _norm(" ".join([market.question, market.event_title or "", market.slug or ""]))
    if "fair play" in text or "golden boot" in text or "halftime" in text:
        return False
    if stage == "quarterfinals":
        return "reach" in text and "quarterfinal" in text
    if stage == "semifinals":
        return "reach" in text and "semifinal" in text
    if stage == "final":
        return "reach" in text and "final" in text
    if stage == "winner":
        return " win " in f" {text} " and "world cup" in text
    return False


def _extract_total_specs(market: PolymarketMarket) -> list[PropMarketSpec]:
    specs: list[PropMarketSpec] = []
    text = _prop_text(" ".join([market.question, market.event_title or "", market.slug or ""]))
    for outcome in market.outcomes:
        outcome_text = _prop_text(outcome.name)
        line = _extract_total_line(" ".join([text, outcome_text]))
        if line is None:
            continue
        if "over" in outcome_text or " over " in f" {text} ":
            specs.append(
                PropMarketSpec("total_goals", f"Over {line:g} goals", "over", line, outcome)
            )
        if "under" in outcome_text or " under " in f" {text} ":
            specs.append(
                PropMarketSpec("total_goals", f"Under {line:g} goals", "under", line, outcome)
            )
    yes_outcome = _yes_outcome(market)
    if yes_outcome is not None:
        line = _extract_total_line(text)
        if line is not None:
            if " over " in f" {text} ":
                specs.append(
                    PropMarketSpec("total_goals", f"Over {line:g} goals", "over", line, yes_outcome)
                )
            elif " under " in f" {text} ":
                specs.append(
                    PropMarketSpec("total_goals", f"Under {line:g} goals", "under", line, yes_outcome)
                )
    return _dedupe_specs(specs)


def _extract_handicap_specs(market: PolymarketMarket, fixture: Fixture) -> list[PropMarketSpec]:
    specs: list[PropMarketSpec] = []
    market_text = _prop_text(" ".join([market.question, market.event_title or "", market.slug or ""]))
    for outcome in market.outcomes:
        combined = " ".join([market_text, _prop_text(outcome.name)])
        for side, team in (("team_a", fixture.team_a), ("team_b", fixture.team_b)):
            handicap = _extract_team_handicap(combined, team)
            if handicap is not None:
                specs.append(
                    PropMarketSpec(
                        "handicap",
                        f"{team} {handicap:+g}",
                        side,
                        handicap,
                        outcome,
                    )
                )
    yes_outcome = _yes_outcome(market)
    if yes_outcome is not None:
        for side, team in (("team_a", fixture.team_a), ("team_b", fixture.team_b)):
            handicap = _extract_team_handicap(market_text, team)
            if handicap is not None:
                specs.append(
                    PropMarketSpec(
                        "handicap",
                        f"{team} {handicap:+g}",
                        side,
                        handicap,
                        yes_outcome,
                    )
                )
            margin_handicap = _extract_win_margin_handicap(market_text, team)
            if margin_handicap is not None:
                specs.append(
                    PropMarketSpec(
                        "handicap",
                        f"{team} {margin_handicap:+g}",
                        side,
                        margin_handicap,
                        yes_outcome,
                    )
                )
    return _dedupe_specs(specs)


def _extract_total_line(text: str) -> float | None:
    match = re.search(r"(?:over|under|total goals?)\s+(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s+(?:goals?|total goals?)", text)
    if match and ("over" in text or "under" in text):
        return float(match.group(1))
    return None


def _extract_team_handicap(text: str, team: str) -> float | None:
    team_norm = _prop_text(team)
    escaped = re.escape(team_norm)
    patterns = (
        rf"{escaped}\s*([+-]\s*\d+(?:\.\d+)?)",
        rf"([+-]\s*\d+(?:\.\d+)?)\s*{escaped}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(" ", ""))
    return None


def _extract_win_margin_handicap(text: str, team: str) -> float | None:
    team_norm = _prop_text(team)
    if team_norm not in text:
        return None
    match = re.search(r"(?:by|margin of)\s+(\d+)\s*(?:or more|\+|plus)", text)
    if not match:
        return None
    return -(float(match.group(1)) - 0.5)


def _yes_outcome(market: PolymarketMarket) -> MarketOutcome | None:
    for outcome in market.outcomes:
        if _norm(outcome.name) == "yes":
            return outcome
    return None


def _dedupe_specs(specs: list[PropMarketSpec]) -> list[PropMarketSpec]:
    deduped: list[PropMarketSpec] = []
    seen = set()
    for spec in specs:
        key = (spec.market_type, spec.label, spec.side, spec.line, id(spec.outcome))
        if key not in seen:
            seen.add(key)
            deduped.append(spec)
    return deduped


def _loads_maybe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _float_from_index(values: Any, index: int) -> float | None:
    if isinstance(values, list) and index < len(values):
        return _float_or_none(values[index])
    return None


def _str_from_index(values: Any, index: int) -> str | None:
    if isinstance(values, list) and index < len(values) and values[index] is not None:
        return str(values[index])
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iter_outcomes(markets: list[PolymarketMarket]) -> Iterable[MarketOutcome]:
    for market in markets:
        yield from market.outcomes


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _prop_text(value: str) -> str:
    return re.sub(r"[^a-z0-9.+-]+", " ", value.casefold()).strip()
