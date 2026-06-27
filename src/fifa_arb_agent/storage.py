from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fifa_arb_agent.models import Edge, MatchForecast, PolymarketMarket, PropEdge
from fifa_arb_agent.recommendations import build_combo_recommendation


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
                  prop_edges_json TEXT NOT NULL DEFAULT '[]',
                  combo_json TEXT,
                  model_version TEXT,
                  calibration_json TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(scan_id) REFERENCES scans(id)
                )
                """
            )
            self._ensure_scan_item_columns(conn)

    def _ensure_scan_item_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(scan_items)")}
        additions = {
            "prop_edges_json": "TEXT NOT NULL DEFAULT '[]'",
            "combo_json": "TEXT",
            "model_version": "TEXT",
            "calibration_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, definition in additions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE scan_items ADD COLUMN {column} {definition}")

    def save(
        self,
        report: str,
        forecasts: list[MatchForecast],
        market_map: dict[str, list[PolymarketMarket]],
        edge_map: dict[str, list[Edge]],
        prop_edge_map: dict[str, list[PropEdge]] | None = None,
    ) -> int:
        prop_edge_map = prop_edge_map or {}
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO scans (created_at, report) VALUES (?, ?)",
                (datetime.now(UTC).isoformat(), report),
            )
            scan_id = int(cursor.lastrowid)
            for forecast in forecasts:
                match_id = forecast.fixture.match_id
                markets = market_map.get(match_id, [])
                combo = build_combo_recommendation(forecast, markets)
                conn.execute(
                    """
                    INSERT INTO scan_items
                      (
                        scan_id,
                        match_id,
                        forecast_json,
                        markets_json,
                        edges_json,
                        prop_edges_json,
                        combo_json,
                        model_version,
                        calibration_json
                      )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        match_id,
                        forecast.model_dump_json(),
                        json.dumps([market.model_dump(mode="json") for market in markets]),
                        json.dumps([edge.model_dump(mode="json") for edge in edge_map.get(match_id, [])]),
                        json.dumps(
                            [
                                edge.model_dump(mode="json")
                                for edge in prop_edge_map.get(match_id, [])
                            ]
                        ),
                        combo.model_dump_json(),
                        forecast.model_version,
                        json.dumps(forecast.calibration_params),
                    ),
                )
            return scan_id
