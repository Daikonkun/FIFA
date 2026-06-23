from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from fifa_arb_agent.models import Fixture


class FixtureLoader:
    def __init__(self, path: Path, url: str | None = None, timeout: float = 20.0) -> None:
        self.path = path
        self.url = url
        self.timeout = timeout

    async def load(self) -> list[Fixture]:
        raw = await self._load_raw()
        fixtures = [Fixture.model_validate(item) for item in raw]
        return sorted(fixtures, key=lambda item: item.kickoff_utc)

    async def _load_raw(self) -> list[dict]:
        if self.url:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.url)
                response.raise_for_status()
                payload = response.json()
        else:
            payload = json.loads(self.path.read_text())

        if isinstance(payload, dict) and "fixtures" in payload:
            payload = payload["fixtures"]
        if not isinstance(payload, list):
            raise ValueError("Fixture feed must be a list or an object with a fixtures list.")
        return payload


def upcoming_fixtures(
    fixtures: list[Fixture], lookahead_hours: int, now: datetime | None = None
) -> list[Fixture]:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    cutoff = now + timedelta(hours=lookahead_hours)
    return [fixture for fixture in fixtures if now <= fixture.kickoff_utc <= cutoff]
