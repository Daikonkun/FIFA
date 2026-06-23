from __future__ import annotations

import asyncio

from fifa_arb_agent.config import Settings
from fifa_arb_agent.fixtures import FixtureLoader, upcoming_fixtures
from fifa_arb_agent.polymarket import PolymarketClient
from fifa_arb_agent.ratings import TeamRatings, WorldCupCalibrator
from fifa_arb_agent.report import build_combined_alert_report, build_report, find_edges, find_stage_edges
from fifa_arb_agent.storage import ReportStore
from fifa_arb_agent.team_context import TeamContexts
from fifa_arb_agent.telegram import TelegramClient
from fifa_arb_agent.tournament import TournamentSimulator, summarize_stage_probabilities


class FifaArbAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fixture_loader = FixtureLoader(
            settings.fixtures_path,
            settings.fixtures_url,
            settings.request_timeout_seconds,
        )
        self.ratings = TeamRatings.load(settings.team_ratings_path)
        self.team_contexts = TeamContexts.load(settings.team_context_path)
        self.calibrator = WorldCupCalibrator()
        self.polymarket = PolymarketClient(
            settings.polymarket_gamma_base_url,
            settings.polymarket_clob_base_url,
            settings.polymarket_search_template,
            settings.request_timeout_seconds,
        )
        self.store = ReportStore(settings.database_path)

    async def run(self, dry_run: bool = False) -> str:
        all_fixtures = await self.fixture_loader.load()
        fixtures = upcoming_fixtures(all_fixtures, self.settings.report_lookahead_hours)
        forecasts = [
            self.calibrator.forecast(fixture, self.ratings, self.team_contexts)
            for fixture in fixtures
        ]

        market_map = {}
        edge_map = {}
        for forecast in forecasts:
            markets = await self.polymarket.find_match_markets(forecast.fixture)
            markets = await self.polymarket.enrich_orderbook_prices(markets)
            market_map[forecast.fixture.match_id] = markets
            edge_map[forecast.fixture.match_id] = find_edges(
                forecast,
                markets,
                self.settings.edge_threshold,
                self.settings.min_market_liquidity,
            )

        tournament_probabilities, tournament_report = self._build_tournament_report(all_fixtures)
        stage_markets = await self.polymarket.find_stage_markets()
        stage_edges = find_stage_edges(
            tournament_probabilities,
            stage_markets,
            self.settings.edge_threshold,
            self.settings.min_market_liquidity,
        )

        report = build_report(forecasts, market_map, edge_map, self.settings.timezone)
        report = f"{report}\n\n{tournament_report}"
        if stage_edges:
            alert_summary = build_combined_alert_report(
                forecasts, market_map, edge_map, stage_edges, self.settings.timezone
            )
            report = f"{report}\n\n{alert_summary}"
        scan_id = self.store.save(report, forecasts, market_map, edge_map)
        total_edges = sum(len(items) for items in edge_map.values()) + len(stage_edges)
        telegram_report = build_combined_alert_report(
            forecasts, market_map, edge_map, stage_edges, self.settings.timezone
        )
        delivery_note = ""

        if not dry_run:
            if self.settings.telegram_alerts_only and total_edges == 0:
                delivery_note = "\n\nTelegram: skipped; no probability arbitrage alerts above threshold."
            elif not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
                raise ValueError(
                    "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required unless --dry-run is used."
                )
            else:
                telegram = TelegramClient(
                    self.settings.telegram_bot_token,
                    self.settings.telegram_chat_id,
                    self.settings.request_timeout_seconds,
                )
                await telegram.send_message(
                    telegram_report if self.settings.telegram_alerts_only else report
                )
                delivery_note = "\n\nTelegram: sent arbitrage alert report."

        return f"{report}\n\nSaved scan #{scan_id}{delivery_note}"

    def _build_tournament_report(self, fixtures):
        simulator = TournamentSimulator(
            self.ratings,
            self.team_contexts,
            self.calibrator,
            seed=self.settings.tournament_seed,
        )
        probabilities = simulator.simulate(fixtures, self.settings.tournament_simulations)
        return probabilities, summarize_stage_probabilities(probabilities)


def run_agent(settings: Settings, dry_run: bool = False) -> str:
    return asyncio.run(FifaArbAgent(settings).run(dry_run=dry_run))
