from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    fixtures_path: Path = Path("data/fixtures.example.json")
    fixtures_url: str | None = None
    team_ratings_path: Path = Path("data/team_ratings.example.json")
    team_context_path: Path = Path("data/team_context.json")
    telegram_alerts_only: bool = True
    tournament_simulations: int = 20000
    tournament_seed: int = 2026
    report_lookahead_hours: int = 72
    edge_threshold: float = 0.06
    min_market_liquidity: float = 0.0
    timezone: str = "Asia/Hong_Kong"
    database_path: Path = Path("reports/fifa_agent.sqlite3")
    polymarket_gamma_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_base_url: str = "https://clob.polymarket.com"
    polymarket_search_template: str = "FIFA World Cup 2026 {team_a} {team_b}"
    request_timeout_seconds: float = Field(default=20.0, gt=0)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        fixtures_path=Path(os.getenv("FIXTURES_PATH", "data/fixtures.example.json")),
        fixtures_url=os.getenv("FIXTURES_URL") or None,
        team_ratings_path=Path(os.getenv("TEAM_RATINGS_PATH", "data/team_ratings.example.json")),
        team_context_path=Path(os.getenv("TEAM_CONTEXT_PATH", "data/team_context.json")),
        telegram_alerts_only=_bool_env(os.getenv("TELEGRAM_ALERTS_ONLY", "true")),
        tournament_simulations=int(os.getenv("TOURNAMENT_SIMULATIONS", "20000")),
        tournament_seed=int(os.getenv("TOURNAMENT_SEED", "2026")),
        report_lookahead_hours=int(os.getenv("REPORT_LOOKAHEAD_HOURS", "72")),
        edge_threshold=float(os.getenv("EDGE_THRESHOLD", "0.06")),
        min_market_liquidity=float(os.getenv("MIN_MARKET_LIQUIDITY", "0")),
        timezone=os.getenv("TIMEZONE", "Asia/Hong_Kong"),
        database_path=Path(os.getenv("DATABASE_PATH", "reports/fifa_agent.sqlite3")),
        polymarket_gamma_base_url=os.getenv(
            "POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com"
        ),
        polymarket_clob_base_url=os.getenv(
            "POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com"
        ),
        polymarket_search_template=os.getenv(
            "POLYMARKET_SEARCH_TEMPLATE", "FIFA World Cup 2026 {team_a} {team_b}"
        ),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
    )


def _bool_env(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}
