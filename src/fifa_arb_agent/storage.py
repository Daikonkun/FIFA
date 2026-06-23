from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fifa_arb_agent.models import Edge, MatchForecast, PolymarketMarket


class ReportStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT NOT NULL,
                  report TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_items (
                  scan_id INTEGER NOT NULL,
                  match_id TEXT NOT NULL,
                  forecast_json TEXT NOT NULL,
                  markets_json TEXT NOT NULL,
                  edges_json TEXT NOT NULL,
                  FOREIGN KEY(scan_id) REFERENCES scans(id)
                )
                """
            )

    def save(
        self,
        report: str,
        forecasts: list[MatchForecast],
        market_map: dict[str, list[PolymarketMarket]],
        edge_map: dict[str, list[Edge]],
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO scans (created_at, report) VALUES (?, ?)",
                (datetime.now(UTC).isoformat(), report),
            )
            scan_id = int(cursor.lastrowid)
            for forecast in forecasts:
                match_id = forecast.fixture.match_id
                conn.execute(
                    """
                    INSERT INTO scan_items
                      (scan_id, match_id, forecast_json, markets_json, edges_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        match_id,
                        forecast.model_dump_json(),
                        json.dumps([market.model_dump(mode="json") for market in market_map[match_id]]),
                        json.dumps([edge.model_dump(mode="json") for edge in edge_map[match_id]]),
                    ),
                )
            return scan_id
