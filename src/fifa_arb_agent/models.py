from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Fixture(BaseModel):
    match_id: str
    kickoff_utc: datetime
    team_a: str
    team_b: str
    stage: str = "group"
    venue: str | None = None
    neutral_site: bool = True
    rest_days_a: float | None = None
    rest_days_b: float | None = None
    status_short: str | None = None
    goals_a: int | None = None
    goals_b: int | None = None


class TeamRating(BaseModel):
    elo: float = Field(..., description="Global Elo-style rating before the match.")
    fifa_rank: int | None = Field(default=None, description="Lower is better.")
    wc_points_last_3: float = Field(default=0.0, ge=0.0)
    confederation: str = "UNKNOWN"
    host: bool = False
    form_delta: float = Field(default=0.0, description="Recent form adjustment, centered on 0.")
    injury_penalty: float = Field(default=0.0, ge=0.0)


class TeamContext(BaseModel):
    api_team_id: int | None = None
    code: str | None = None
    logo: str | None = None
    founded: int | None = None
    venue_name: str | None = None
    squad_size: int = 0
    avg_age: float | None = None
    position_counts: dict[str, int] = Field(default_factory=dict)
    tournament_played: int = 0
    tournament_wins: int = 0
    tournament_draws: int = 0
    tournament_losses: int = 0
    tournament_points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goals_diff: int = 0
    group: str | None = None
    standing_rank: int | None = None
    standing_description: str | None = None
    tournament_form: str | None = None
    injury_count: int = 0


class MatchForecast(BaseModel):
    fixture: Fixture
    team_a_win: float
    draw: float
    team_b_win: float
    fair_team_a_no_draw: float
    fair_team_b_no_draw: float
    model_notes: list[str]
    model_version: str = "calibration-v1"
    calibration_params: dict[str, Any] = Field(default_factory=dict)


class MarketOutcome(BaseModel):
    name: str
    price: float | None = None
    token_id: str | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    midpoint: float | None = None


class PolymarketMarket(BaseModel):
    market_id: str
    question: str
    slug: str | None = None
    event_slug: str | None = None
    event_title: str | None = None
    liquidity: float | None = None
    volume: float | None = None
    outcomes: list[MarketOutcome]
    url: str | None = None


class Edge(BaseModel):
    side: Literal["team_a", "team_b"]
    team: str
    model_probability: float
    market_probability: float
    edge: float
    market: PolymarketMarket
    matched_outcome: MarketOutcome


class StageEdge(BaseModel):
    stage: Literal["quarterfinals", "semifinals", "final", "winner"]
    team: str
    model_probability: float
    market_probability: float
    edge: float
    market: PolymarketMarket
    matched_outcome: MarketOutcome


class PropEdge(BaseModel):
    market_type: Literal["handicap", "total_goals"]
    label: str
    model_probability: float
    market_probability: float
    edge: float
    market: PolymarketMarket
    matched_outcome: MarketOutcome


class ComboLeg(BaseModel):
    role: Literal["safety", "direction", "upside"]
    market_type: Literal["1x2", "handicap"]
    label: str
    model_probability: float
    stake_weight: float
    confidence_tier: Literal["observe", "lean", "alert"] = "observe"
    market_probability: float | None = None
    edge: float | None = None
    historical_hit_rate: float | None = None

    @property
    def fair_decimal_odds(self) -> float:
        return 1 / self.model_probability if self.model_probability > 0 else float("inf")


class MatchComboRecommendation(BaseModel):
    fixture: Fixture
    profile: str
    legs: list[ComboLeg]
    note: str


class TeamStageProbability(BaseModel):
    team: str
    top_32: float = 0.0
    top_16: float = 0.0
    top_8: float = 0.0
    semi_final: float = 0.0
    final: float = 0.0
    champion: float = 0.0
