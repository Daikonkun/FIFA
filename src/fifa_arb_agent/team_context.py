from __future__ import annotations

import json
from pathlib import Path

from fifa_arb_agent.models import TeamContext


class TeamContexts:
    def __init__(self, teams: dict[str, TeamContext]) -> None:
        self.teams = teams
        self._normalized_teams = {_norm_team(name): value for name, value in teams.items()}

    @classmethod
    def load(cls, path: Path | None) -> "TeamContexts":
        if path is None or not path.exists():
            return cls({})
        payload = json.loads(path.read_text())
        raw_teams = payload.get("teams", payload)
        return cls({name: TeamContext.model_validate(value) for name, value in raw_teams.items()})

    def get(self, team: str) -> TeamContext | None:
        return self.teams.get(team) or self._normalized_teams.get(_norm_team(team))


def _norm_team(value: str) -> str:
    aliases = {
        "usa": "united states",
        "u s a": "united states",
        "us": "united states",
        "south korea": "korea republic",
        "korea republic": "korea republic",
    }
    normalized = " ".join(value.casefold().replace("&", " and ").split())
    return aliases.get(normalized, normalized)
