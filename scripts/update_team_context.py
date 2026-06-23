from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde Islands": "Cape Verde Islands",
    "Congo DR": "Congo DR",
    "Curaçao": "Curaçao",
    "South Korea": "South Korea",
    "Türkiye": "Turkey",
    "USA": "USA",
}


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Update API-Football team context data.")
    parser.add_argument("--fixtures", default=os.getenv("FIXTURES_PATH", "data/fixtures.json"))
    parser.add_argument("--output", default=os.getenv("TEAM_CONTEXT_PATH", "data/team_context.json"))
    parser.add_argument("--season", type=int, default=int(os.getenv("API_FOOTBALL_SEASON", "2026")))
    parser.add_argument("--league", type=int, default=_optional_int(os.getenv("API_FOOTBALL_LEAGUE_ID")) or 1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fixture_teams = _fixture_teams(Path(args.fixtures))
    client = ApiFootballClient.from_env()
    teams_payload = client.get("teams", {"league": args.league, "season": args.season})
    standings_payload = client.get("standings", {"league": args.league, "season": args.season})

    api_teams = _match_api_teams(fixture_teams, teams_payload)
    contexts = {}
    for fixture_team, api_team in api_teams.items():
        team_id = api_team["team"]["id"]
        squad_payload = client.get("players/squads", {"team": team_id})
        stats_payload = client.get(
            "teams/statistics", {"league": args.league, "season": args.season, "team": team_id}
        )
        injuries_payload = client.get(
            "injuries", {"league": args.league, "season": args.season, "team": team_id}
        )
        contexts[fixture_team] = build_team_context(
            api_team,
            squad_payload,
            stats_payload,
            standings_payload,
            injuries_payload,
        )

    payload = {
        "metadata": {
            "source": "API-Football / API-Sports",
            "league": args.league,
            "season": args.season,
            "generated_at": datetime.now(UTC).isoformat(),
            "notes": [
                "Squads come from /players/squads.",
                "Tournament stats come from /teams/statistics.",
                "Group position comes from /standings.",
                "Injury counts come from /injuries when the endpoint has data.",
            ],
        },
        "teams": contexts,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:5000])
        print(f"teams={len(contexts)}")
        return

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(contexts)} team contexts to {output}")


class ApiFootballClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-apisports-key": api_key}

    @classmethod
    def from_env(cls) -> "ApiFootballClient":
        api_key = os.getenv("API_FOOTBALL_KEY")
        if not api_key:
            raise RuntimeError("API_FOOTBALL_KEY is required.")
        return cls(os.getenv("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"), api_key)

    def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        response = httpx.get(
            f"{self.base_url}/{endpoint}",
            params=params,
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football {endpoint} returned errors: {payload['errors']}")
        return payload.get("response")


def build_team_context(
    api_team: dict[str, Any],
    squad_payload: list[dict[str, Any]],
    stats_payload: dict[str, Any],
    standings_payload: list[dict[str, Any]],
    injuries_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    team = api_team["team"]
    venue = api_team.get("venue") or {}
    players = _players_from_squad_payload(squad_payload)
    standing = _find_standing(standings_payload, team["id"])
    stats = _stats_summary(stats_payload)

    return {
        "api_team_id": team.get("id"),
        "code": team.get("code"),
        "logo": team.get("logo"),
        "founded": team.get("founded"),
        "venue_name": venue.get("name"),
        "squad_size": len(players),
        "avg_age": _avg_age(players),
        "position_counts": _position_counts(players),
        "tournament_played": stats["played"],
        "tournament_wins": stats["wins"],
        "tournament_draws": stats["draws"],
        "tournament_losses": stats["losses"],
        "tournament_points": standing.get("points", stats["wins"] * 3 + stats["draws"]),
        "goals_for": stats["goals_for"],
        "goals_against": stats["goals_against"],
        "goals_diff": standing.get("goalsDiff", stats["goals_for"] - stats["goals_against"]),
        "group": standing.get("group"),
        "standing_rank": standing.get("rank"),
        "standing_description": standing.get("description"),
        "tournament_form": standing.get("form") or stats_payload.get("form"),
        "injury_count": len(injuries_payload or []),
    }


def _fixture_teams(path: Path) -> list[str]:
    fixtures = json.loads(path.read_text())
    return sorted({fixture["team_a"] for fixture in fixtures} | {fixture["team_b"] for fixture in fixtures})


def _match_api_teams(fixture_teams: list[str], teams_payload: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index = {}
    for item in teams_payload:
        team = item["team"]
        names = {team.get("name"), team.get("country"), team.get("code")}
        for name in names:
            if name:
                index[_norm(name)] = item

    matched = {}
    missing = []
    for fixture_team in fixture_teams:
        lookup = TEAM_ALIASES.get(fixture_team, fixture_team)
        item = index.get(_norm(lookup))
        if item is None:
            missing.append(fixture_team)
        else:
            matched[fixture_team] = item

    if missing:
        raise RuntimeError(f"Missing API-Football team profiles: {', '.join(missing)}")
    return matched


def _players_from_squad_payload(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not payload:
        return []
    return payload[0].get("players") or []


def _avg_age(players: list[dict[str, Any]]) -> float | None:
    ages = [player["age"] for player in players if isinstance(player.get("age"), int)]
    if not ages:
        return None
    return round(sum(ages) / len(ages), 1)


def _position_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        position = player.get("position") or "Unknown"
        counts[position] = counts.get(position, 0) + 1
    return counts


def _stats_summary(payload: dict[str, Any]) -> dict[str, int]:
    fixtures = payload.get("fixtures") or {}
    goals = payload.get("goals") or {}
    goals_for = ((goals.get("for") or {}).get("total") or {}).get("total") or 0
    goals_against = ((goals.get("against") or {}).get("total") or {}).get("total") or 0
    return {
        "played": ((fixtures.get("played") or {}).get("total")) or 0,
        "wins": ((fixtures.get("wins") or {}).get("total")) or 0,
        "draws": ((fixtures.get("draws") or {}).get("total")) or 0,
        "losses": ((fixtures.get("loses") or {}).get("total")) or 0,
        "goals_for": goals_for,
        "goals_against": goals_against,
    }


def _find_standing(payload: list[dict[str, Any]], team_id: int) -> dict[str, Any]:
    for league_item in payload or []:
        league = league_item.get("league") or {}
        for group in league.get("standings") or []:
            for standing in group:
                if (standing.get("team") or {}).get("id") == team_id:
                    return standing
    return {}


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def _norm(value: str) -> str:
    value = value.replace("&", "and").replace("ç", "c").replace("Ç", "C")
    return " ".join(value.casefold().split())


if __name__ == "__main__":
    main()
