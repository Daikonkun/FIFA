from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Update normalized FIFA 2026 fixtures.")
    parser.add_argument("--output", default=os.getenv("FIXTURES_PATH", "data/fixtures.json"))
    parser.add_argument("--season", type=int, default=int(os.getenv("API_FOOTBALL_SEASON", "2026")))
    parser.add_argument("--league", type=int, default=_optional_int(os.getenv("API_FOOTBALL_LEAGUE_ID")) or 1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fixtures = fetch_api_football_fixtures(args.league, args.season)
    normalized = normalize_fixtures(fixtures)

    if args.dry_run:
        print(json.dumps(normalized[:5], indent=2))
        print(f"fixtures={len(normalized)}")
        return

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(normalized, indent=2) + "\n")
    print(f"Wrote {len(normalized)} fixtures to {output}")


def fetch_api_football_fixtures(league: int, season: int) -> list[dict[str, Any]]:
    load_dotenv(".env")
    api_key = os.getenv("API_FOOTBALL_KEY")
    base_url = os.getenv("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io").rstrip("/")
    if not api_key:
        raise RuntimeError("API_FOOTBALL_KEY is required.")

    response = httpx.get(
        f"{base_url}/fixtures",
        params={"league": league, "season": season},
        headers={"x-apisports-key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(
            "API-Football returned errors. "
            f"For FIFA 2026, confirm your plan includes season access: {payload['errors']}"
        )
    return payload.get("response", [])


def normalize_fixtures(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(fixtures, key=lambda item: item["fixture"]["date"])
    last_match_at: dict[int, datetime] = {}
    normalized: list[dict[str, Any]] = []

    for item in ordered:
        fixture = item["fixture"]
        league = item.get("league", {})
        teams = item["teams"]
        home = teams["home"]
        away = teams["away"]
        home_id = int(home["id"])
        away_id = int(away["id"])
        kickoff = _parse_api_datetime(fixture["date"])

        rest_days_home = _rest_days(last_match_at.get(home_id), kickoff)
        rest_days_away = _rest_days(last_match_at.get(away_id), kickoff)

        normalized.append(
            {
                "match_id": f"api-football-{fixture['id']}",
                "kickoff_utc": kickoff.isoformat().replace("+00:00", "Z"),
                "team_a": home["name"],
                "team_b": away["name"],
                "stage": _normalize_stage(str(league.get("round") or "")),
                "venue": _venue_name(fixture.get("venue") or {}),
                "neutral_site": True,
                "rest_days_a": rest_days_home,
                "rest_days_b": rest_days_away,
                "status_short": (fixture.get("status") or {}).get("short"),
                "goals_a": (item.get("goals") or {}).get("home"),
                "goals_b": (item.get("goals") or {}).get("away"),
            }
        )

        last_match_at[home_id] = kickoff
        last_match_at[away_id] = kickoff

    return normalized


def _parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rest_days(previous: datetime | None, kickoff: datetime) -> float | None:
    if previous is None:
        return None
    return round((kickoff - previous).total_seconds() / 86400, 1)


def _normalize_stage(round_name: str) -> str:
    text = round_name.casefold()
    if "group" in text:
        return "group"
    if "round of 32" in text:
        return "round_of_32"
    if "round of 16" in text:
        return "round_of_16"
    if "quarter" in text:
        return "quarter_final"
    if "semi" in text:
        return "semi_final"
    if "third" in text:
        return "third_place"
    if "final" in text:
        return "final"
    return round_name or "unknown"


def _venue_name(venue: dict[str, Any]) -> str | None:
    name = venue.get("name")
    city = venue.get("city")
    if name and city:
        return f"{name}, {city}"
    return name or city


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


if __name__ == "__main__":
    main()
