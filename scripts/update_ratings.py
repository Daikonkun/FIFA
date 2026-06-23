from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


ELO_BASE_URL = "https://www.eloratings.net"
REGIONS = ("UEFA", "CONMEBOL", "CONCACAF", "CAF", "AFC", "OFC")
HOSTS = {"Canada", "Mexico", "USA", "United States"}

TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
    "Curaçao": "Curaçao",
    "Czechia": "Czechia",
    "South Korea": "South Korea",
    "Türkiye": "Turkey",
    "USA": "United States",
}

WC_POINTS_LAST_3 = {
    "Argentina": 25,
    "Australia": 11,
    "Belgium": 18,
    "Brazil": 24,
    "Canada": 0,
    "Colombia": 14,
    "Costa Rica": 10,
    "Croatia": 24,
    "Denmark": 7,
    "Ecuador": 4,
    "Egypt": 0,
    "England": 23,
    "France": 35,
    "Germany": 19,
    "Ghana": 1,
    "Iran": 7,
    "Japan": 13,
    "Mexico": 14,
    "Morocco": 11,
    "Netherlands": 17,
    "New Zealand": 0,
    "Poland": 7,
    "Portugal": 17,
    "Qatar": 0,
    "Saudi Arabia": 6,
    "Senegal": 10,
    "Serbia": 3,
    "South Korea": 11,
    "Spain": 17,
    "Switzerland": 16,
    "Tunisia": 7,
    "United States": 9,
    "Uruguay": 19,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Update complete team ratings for fixture teams.")
    parser.add_argument("--fixtures", default="data/fixtures.json")
    parser.add_argument("--output", default="data/team_ratings.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    fixture_teams = _fixture_teams(Path(args.fixtures))
    try:
        elo_rows = _load_elo_rows()
        confederations = _load_confederations()
        ratings = build_ratings(fixture_teams, elo_rows, confederations)
    except httpx.HTTPError:
        if not output.exists():
            raise
        print(f"Rating source unavailable; keeping existing {output}")
        return

    payload = {
        "metadata": {
            "elo_source": f"{ELO_BASE_URL}/World.tsv",
            "confederation_sources": [f"{ELO_BASE_URL}/{region}.tsv" for region in REGIONS],
            "notes": [
                "elo is World Football Elo rating.",
                "fifa_rank is populated with the World Football Elo global rank as a ranking prior.",
                "form_delta is derived from recent Elo rating change and clamped for model stability.",
                "injury_penalty defaults to 0.0 and should be manually updated near kickoff.",
            ],
        },
        "teams": ratings,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:5000])
        print(f"teams={len(ratings)}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(ratings)} team ratings to {output}")


def build_ratings(
    fixture_teams: list[str], elo_rows: dict[str, dict[str, Any]], confederations: dict[str, str]
) -> dict[str, dict[str, Any]]:
    ratings: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for fixture_team in fixture_teams:
        source_name = TEAM_ALIASES.get(fixture_team, fixture_team)
        row = elo_rows.get(_norm(source_name))
        if row is None:
            missing.append(fixture_team)
            continue

        canonical_name = row["name"]
        form_delta = _clamp(row["rating_three_month_change"] / 250, -0.18, 0.18)
        ratings[fixture_team] = {
            "elo": row["rating"],
            "fifa_rank": row["global_rank"],
            "wc_points_last_3": WC_POINTS_LAST_3.get(fixture_team)
            or WC_POINTS_LAST_3.get(canonical_name)
            or 0,
            "confederation": confederations.get(row["code"], "UNKNOWN"),
            "host": fixture_team in HOSTS or canonical_name in HOSTS,
            "form_delta": round(form_delta, 3),
            "injury_penalty": 0.0,
        }

    if missing:
        raise RuntimeError(f"Missing Elo ratings for fixture teams: {', '.join(missing)}")
    return ratings


def _fixture_teams(path: Path) -> list[str]:
    fixtures = json.loads(path.read_text())
    return sorted({fixture["team_a"] for fixture in fixtures} | {fixture["team_b"] for fixture in fixtures})


def _load_elo_rows() -> dict[str, dict[str, Any]]:
    team_names = _load_team_names()
    text = _get_text(f"{ELO_BASE_URL}/World.tsv")
    rows: dict[str, dict[str, Any]] = {}

    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        code = fields[2]
        names = team_names.get(code)
        if not names:
            continue
        row = {
            "code": code,
            "name": names[0],
            "global_rank": _int(fields[1]),
            "rating": _int(fields[3]),
            "rating_three_month_change": _int(fields[11]),
        }
        for name in names:
            rows[_norm(name)] = row

    return rows


def _load_team_names() -> dict[str, list[str]]:
    text = _get_text(f"{ELO_BASE_URL}/en.teams.tsv")
    team_names: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        code, *names = line.split("\t")
        team_names[code] = names
    return team_names


def _load_confederations() -> dict[str, str]:
    confederations: dict[str, str] = {}
    for region in REGIONS:
        text = _get_text(f"{ELO_BASE_URL}/{region}.tsv")
        for line in text.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            confederations[fields[2]] = region
    return confederations


def _get_text(url: str) -> str:
    last_error: httpx.HTTPError | None = None
    for attempt in range(3):
        try:
            response = httpx.get(url, timeout=30, trust_env=False)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _int(value: str) -> int:
    return int(value.replace("−", "-").replace("+", ""))


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _norm(value: str) -> str:
    value = (
        value.replace("&", "and")
        .replace("Côte", "Ivory")
        .replace("ç", "c")
        .replace("Ç", "C")
    )
    return " ".join(value.casefold().split())


if __name__ == "__main__":
    main()
